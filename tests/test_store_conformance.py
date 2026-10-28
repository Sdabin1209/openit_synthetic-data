"""I2 DatasetStore 적합성 시험. 파일 구현과 메모리 구현이 같은 시험을 통과해야 한다."""
from __future__ import annotations

import copy
import json

import pytest
from boundary_contracts import canonical
from doubles import OLD_PIPELINE_SCHEMA_VERSION
from boundary_contracts.errors import BoundaryError
from boundary_contracts.sdk import DatasetStore

from conftest import write_files
from synthetic_data.store.base import DatasetStoreBase


def code(excinfo):
    return excinfo.value.code


def rebuild(manifest, blobs, tmp_path, *, mutate_manifest=None, mutate_blob=None):
    """블롭/매니페스트를 바꾸고 해시·줄 수를 맞춰 다시 만든다(바꾼 것만 위반이 되게)."""
    m, b = copy.deepcopy(manifest), dict(blobs)
    if mutate_blob:
        mutate_blob(b)
    for e in m["files"]:
        p = tmp_path / "_h" / e["path"]
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b[e["path"]])
        e["content_hash"] = canonical.file_hash(p)
    if mutate_manifest:
        mutate_manifest(m)
    m["content_hash"] = canonical.content_hash(m)
    return m, write_files(tmp_path / "files", b)


def lines(blob):
    return [json.loads(x) for x in blob.decode().splitlines()]


def dump(recs):
    return "".join(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n" for r in recs).encode()


def test_is_protocol(store):
    assert isinstance(store, DatasetStore)


def test_publish_and_read(store, captured, tmp_path):
    m, b = captured
    files = write_files(tmp_path, b)
    got = store.publish(m, files)
    assert got == m
    assert store.get_manifest(m["dataset_id"], m["version"]) == m
    assert store.list_versions(m["dataset_id"]) == [m["version"]]
    for e in m["files"]:
        data = store.open_file(m["dataset_id"], m["version"], e["path"]).read()
        assert data == b[e["path"]]
        assert len(data.splitlines()) == e["sample_count"]


def test_publish_idempotent(store, captured, tmp_path):
    m, b = captured
    files = write_files(tmp_path, b)
    first = store.publish(m, files)
    again = store.publish(m, files)
    assert first == again and store.list_versions(m["dataset_id"]) == [m["version"]]


def test_same_version_different_content_conflict(store, captured, tmp_path):
    m, b = captured
    store.publish(m, write_files(tmp_path / "a", b))
    m2 = copy.deepcopy(m)
    m2["created_at"] = "2026-10-16T00:00:00Z"
    m2["content_hash"] = canonical.content_hash(m2)
    with pytest.raises(BoundaryError) as e:
        store.publish(m2, write_files(tmp_path / "b", b))
    assert code(e) == "CONFLICT" and not e.value.retryable


def test_list_versions_oldest_first_and_unknown(store, captured, tmp_path):
    m, b = captured
    assert store.list_versions("nope") == []
    order = []
    for v in ("v-b", "v-a", "v-c"):
        mm, files = rebuild(m, b, tmp_path / v, mutate_manifest=lambda x, v=v: x.update(version=v))
        store.publish(mm, files)
        order.append(v)
    assert store.list_versions(m["dataset_id"]) == order


def test_not_found(store, captured, tmp_path):
    m, b = captured
    with pytest.raises(BoundaryError) as e:
        store.get_manifest("nope", "1")
    assert code(e) == "NOT_FOUND"
    store.publish(m, write_files(tmp_path, b))
    with pytest.raises(BoundaryError) as e:
        store.open_file(m["dataset_id"], m["version"], "lora_a/none.jsonl")
    assert code(e) == "NOT_FOUND"
    with pytest.raises(BoundaryError) as e:
        store.get_manifest(m["dataset_id"], "other")
    assert code(e) == "NOT_FOUND"


def test_file_hash_mismatch(store, captured, tmp_path):
    m, b = captured
    path = m["files"][0]["path"]
    bad = dict(b)
    bad[path] = b[path] + b" "
    with pytest.raises(BoundaryError) as e:
        store.publish(m, write_files(tmp_path, bad))
    assert code(e) == "INTEGRITY_ERROR"


def test_manifest_content_hash_mismatch(store, captured, tmp_path):
    m, b = captured
    m2 = copy.deepcopy(m)
    m2["generator_version"] += "x"
    with pytest.raises(BoundaryError) as e:
        store.publish(m2, write_files(tmp_path, b))
    assert code(e) == "INTEGRITY_ERROR"


def test_sample_count_mismatch(store, captured, tmp_path):
    m, b = captured
    def mm(x): x["files"][0]["sample_count"] += 1
    m2, files = rebuild(m, b, tmp_path, mutate_manifest=mm)
    with pytest.raises(BoundaryError) as e:
        store.publish(m2, files)
    assert code(e) == "INVALID_RECORD" and "sample_count" in e.value.message


def test_split_mismatch(store, captured, tmp_path):
    m, b = captured
    ent = next(f for f in m["files"] if f["split"] == "TRAIN" and f["role"] == "LORA_A")
    def mb(blobs):
        recs = lines(blobs[ent["path"]])
        recs[0]["split"] = "VALIDATION"
        blobs[ent["path"]] = dump(recs)
    m2, files = rebuild(m, b, tmp_path, mutate_blob=mb)
    with pytest.raises(BoundaryError) as e:
        store.publish(m2, files)
    assert code(e) == "INVALID_RECORD" and "split" in e.value.message


def test_eval_scenario_overlap_with_train_rejected(store, captured, tmp_path):
    m, b = captured
    tr = next(f for f in m["files"] if f["split"] == "TRAIN" and f["role"] == "LORA_A")
    ev = next(f for f in m["files"] if f["split"] == "EVAL" and f["role"] == "LORA_A" and "unseen" not in f["path"])
    train0 = lines(b[tr["path"]])[0]
    def mb(blobs):
        recs = lines(blobs[ev["path"]])
        recs[0]["scenario_id"] = train0["scenario_id"]
        blobs[ev["path"]] = dump(recs)
    m2, files = rebuild(m, b, tmp_path, mutate_blob=mb)
    with pytest.raises(BoundaryError) as e:
        store.publish(m2, files)
    assert code(e) == "INVALID_RECORD" and "scenario" in e.value.message


def test_invalid_sample_schema(store, captured, tmp_path):
    m, b = captured
    ent = m["files"][0]
    def mb(blobs):
        recs = lines(blobs[ent["path"]])
        del recs[0]["scenario_id"]
        blobs[ent["path"]] = dump(recs)
    m2, files = rebuild(m, b, tmp_path, mutate_blob=mb)
    with pytest.raises(BoundaryError) as e:
        store.publish(m2, files)
    assert code(e) == "INVALID_RECORD"


def test_expected_violates_sample_schema(store, captured, tmp_path):
    m, b = captured
    ent = next(f for f in m["files"] if f["role"] == "LORA_A" and f["split"] == "TRAIN")
    def mb(blobs):
        recs = lines(blobs[ent["path"]])
        recs[0]["expected"] = {"items": [{"item_no": 0}]}   # v1 형태
        blobs[ent["path"]] = dump(recs)
    m2, files = rebuild(m, b, tmp_path, mutate_blob=mb)
    with pytest.raises(BoundaryError) as e:
        store.publish(m2, files)
    assert code(e) == "INVALID_RECORD" and "ActionExtractionSample" in e.value.message


def test_input_violates_sample_schema(store, captured, tmp_path):
    m, b = captured
    ent = next(f for f in m["files"] if f["role"] == "LORA_B" and f["split"] == "TRAIN")
    def mb(blobs):
        recs = lines(blobs[ent["path"]])
        recs[0]["input"] = {"directive": {}, "utterance": None}   # v1 형태
        blobs[ent["path"]] = dump(recs)
    m2, files = rebuild(m, b, tmp_path, mutate_blob=mb)
    with pytest.raises(BoundaryError) as e:
        store.publish(m2, files)
    assert code(e) == "INVALID_RECORD"


def test_blank_line_and_non_json(store, captured, tmp_path):
    m, b = captured
    ent = m["files"][0]
    for bad in (b"\n" + b[ent["path"]], b[ent["path"]] + b"not json\n"):
        m2, files = rebuild(m, b, tmp_path / str(len(bad)), mutate_blob=lambda blobs, bad=bad: blobs.update({ent["path"]: bad}))
        with pytest.raises(BoundaryError) as e:
            store.publish(m2, files)
        assert code(e) == "INVALID_RECORD"


def test_files_keys_must_match(store, captured, tmp_path):
    m, b = captured
    files = write_files(tmp_path, b)
    extra = dict(files)
    extra["lora_a/extra.jsonl"] = files[m["files"][0]["path"]]
    for bad in (extra, {k: v for k, v in list(files.items())[1:]}):
        with pytest.raises(BoundaryError) as e:
            store.publish(m, bad)
        assert code(e) == "INVALID_RECORD"


def test_unsafe_paths_and_ids(store, captured, tmp_path):
    m, b = captured
    for bad_path in ("../x.jsonl", "/abs.jsonl", "a//b.jsonl"):
        mm2 = copy.deepcopy(m)
        mm2["files"][0]["path"] = bad_path
        mm2["content_hash"] = canonical.content_hash(mm2)
        with pytest.raises(BoundaryError) as e:
            store.publish(mm2, {bad_path: tmp_path / "x"})
        assert code(e) == "INVALID_RECORD"
    mm3 = copy.deepcopy(m)
    mm3["version"] = "../evil"
    mm3["content_hash"] = canonical.content_hash(mm3)
    with pytest.raises(BoundaryError) as e:
        store.publish(mm3, write_files(tmp_path / "y", b))
    assert code(e) == "INVALID_RECORD"


def test_manifest_schema_violation(store, captured, tmp_path):
    m, b = captured
    m2 = copy.deepcopy(m)
    m2["scenario_disjoint_across_splits"] = False
    m2["content_hash"] = canonical.content_hash(m2)
    with pytest.raises(BoundaryError) as e:
        store.publish(m2, write_files(tmp_path, b))
    assert code(e) == "INVALID_RECORD"


def test_contract_version_mismatch(store, captured, tmp_path):
    m, b = captured
    m2 = copy.deepcopy(m)
    m2["runtime_contract_version"] = 2
    m2["content_hash"] = canonical.content_hash(m2)
    with pytest.raises(BoundaryError) as e:
        store.publish(m2, write_files(tmp_path, b))
    assert code(e) == "UNSUPPORTED_VERSION"


def test_question_set_outside_manifest_rejected(store, captured, tmp_path):
    m, b = captured
    ent = m["files"][0]
    def mb(blobs):
        recs = lines(blobs[ent["path"]])
        recs[0]["question_set"]["content_hash"] = "sha256:" + "1" * 64
        blobs[ent["path"]] = dump(recs)
    m2, files = rebuild(m, b, tmp_path, mutate_blob=mb)
    with pytest.raises(BoundaryError) as e:
        store.publish(m2, files)
    assert code(e) == "INVALID_RECORD"


def test_failed_publish_leaves_nothing(store, captured, tmp_path):
    m, b = captured
    bad = dict(b)
    bad[m["files"][0]["path"]] += b"x"
    with pytest.raises(BoundaryError):
        store.publish(m, write_files(tmp_path / "bad", bad))
    assert store.list_versions(m["dataset_id"]) == []
    store.publish(m, write_files(tmp_path / "good", b))   # 실패 뒤에도 정상 게시가 된다


def test_tamper_detected_on_open(captured, validators, tmp_path):
    from synthetic_data.store import FileDatasetStore, MemoryDatasetStore
    m, b = captured
    path = m["files"][0]["path"]
    fs = FileDatasetStore(tmp_path / "s", validators)
    fs.publish(m, write_files(tmp_path / "f", b))
    p = tmp_path / "s" / m["dataset_id"] / m["version"] / "files" / path
    p.write_bytes(p.read_bytes() + b"x")
    with pytest.raises(BoundaryError) as e:
        fs.open_file(m["dataset_id"], m["version"], path)
    assert code(e) == "INTEGRITY_ERROR"
    ms = MemoryDatasetStore(validators)
    ms.publish(m, write_files(tmp_path / "g", b))
    ms._corrupt_for_test(m["dataset_id"], m["version"], path)
    with pytest.raises(BoundaryError) as e:
        ms.open_file(m["dataset_id"], m["version"], path)
    assert code(e) == "INTEGRITY_ERROR"


def test_file_store_persists_across_instances(captured, validators, tmp_path):
    from synthetic_data.store import FileDatasetStore
    m, b = captured
    FileDatasetStore(tmp_path / "s", validators).publish(m, write_files(tmp_path / "f", b))
    again = FileDatasetStore(tmp_path / "s", validators)
    assert again.get_manifest(m["dataset_id"], m["version"]) == m
    assert again.list_versions(m["dataset_id"]) == [m["version"]]


def test_reader_needs_no_survey_dir_but_publish_does(captured, tmp_path):
    from synthetic_data.schemas import Validators
    from synthetic_data.store import MemoryDatasetStore
    m, b = captured
    st = MemoryDatasetStore(Validators())
    with pytest.raises(BoundaryError) as e:
        st.publish(m, write_files(tmp_path, b))
    assert code(e) == "FAILED_PRECONDITION"


def test_unsupported_pipeline_major(store, captured, tmp_path):
    m, b = captured
    m2 = copy.deepcopy(m)
    m2["pipeline_schema_version"] = OLD_PIPELINE_SCHEMA_VERSION
    m2["content_hash"] = canonical.content_hash(m2)
    with pytest.raises(BoundaryError) as e:
        store.publish(m2, write_files(tmp_path, b))
    assert code(e) == "UNSUPPORTED_VERSION"


def test_v1_roles_and_samples_rejected(store, captured, tmp_path):
    """현행 계약: PARSER/GENERATOR 역할은 매니페스트 스키마에서 거부되고, v1 샘플 필드(runtime_contract_version 등)는 샘플 스키마에서 거부된다."""
    m, b = captured
    m2 = copy.deepcopy(m)
    m2["files"][0]["role"] = "PARSER"
    m2["content_hash"] = canonical.content_hash(m2)
    with pytest.raises(BoundaryError) as e:
        store.publish(m2, write_files(tmp_path / "r", b))
    assert code(e) == "INVALID_RECORD"
    ent = m["files"][0]
    def mb(blobs):
        recs = lines(blobs[ent["path"]])
        recs[0]["runtime_contract_version"] = 1
        blobs[ent["path"]] = dump(recs)
    m3, files = rebuild(m, b, tmp_path / "s", mutate_blob=mb)
    with pytest.raises(BoundaryError) as e:
        store.publish(m3, files)
    assert code(e) == "INVALID_RECORD"


def test_roles_cover_lora_a_and_b_with_matching_sample_schema(store, captured, tmp_path):
    m, b = captured
    assert {f["role"] for f in m["files"]} == {"LORA_A", "LORA_B"}
    for f in m["files"]:
        rec = lines(b[f["path"]])[0]
        assert isinstance(rec["expected"], str) == (f["role"] == "LORA_B")   # ResponseText는 문자열, ActionExtraction은 객체
    ent = next(f for f in m["files"] if f["role"] == "LORA_B" and f["split"] == "TRAIN")
    def mb(blobs):                                     # LORA_B 파일에 LoRA-A 샘플을 넣으면 거부
        a = next(f for f in m["files"] if f["role"] == "LORA_A" and f["split"] == "TRAIN")
        blobs[ent["path"]] = blobs[a["path"]]
    m2, files = rebuild(m, b, tmp_path / "x", mutate_blob=mb)
    with pytest.raises(BoundaryError) as e:
        store.publish(m2, files)
    assert code(e) == "INVALID_RECORD"
