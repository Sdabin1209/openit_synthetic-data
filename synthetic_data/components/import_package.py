"""게시기 패키징. ImportPackageInput -> PackagedDataset.

같은 입력(파일 바이트)과 같은 설정이면 같은 dataset_digest와 같은 version이 나온다(docs/adr/0006). 해시는 boundary_contracts.canonical로 계산한다.
파일 본문은 키 정렬·샘플 순서 그대로의 JSONL이라 같은 샘플 집합은 항상 같은 바이트다."""
from __future__ import annotations

import json
import tempfile

from boundary_contracts import canonical

from ..types.schema_registry import check

EXT = "synthetic-data"
IMPORT_GENERATOR_PREFIX = "external-import"
_ROLE_DIR = {"LORA_A": "lora_a", "LORA_B": "lora_b"}
_SPLIT_FILE = {"TRAIN": "train", "VALIDATION": "validation", "EVAL": "eval"}


def _file_hash(text: str) -> str:
    # 왜 임시 파일: 해시는 boundary_contracts.canonical로만 계산한다(자체 구현 금지, 시험 test_hashes_only_via_canonical). canonical의 파일 해시는 경로를 받는다
    with tempfile.NamedTemporaryFile() as f:
        f.write(text.encode("utf-8"))
        f.flush()
        return canonical.file_hash(f.name)


def _line(rec: dict) -> str:
    return json.dumps(rec, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"


def run(inp: dict) -> dict:
    check("ImportPackageInput", inp)
    summary, overlap = inp["summary"], inp["overlap"]
    entries, files = [], []
    for f in inp["files"]:
        rel = f"{_ROLE_DIR[f['role']]}/{_SPLIT_FILE[f['split']]}.jsonl"
        text = "".join(_line(r) for r in f["samples"])
        entries.append({"path": rel, "role": f["role"], "split": f["split"], "sample_count": len(f["samples"]),
                        "content_hash": _file_hash(text)})
        files.append({"path": rel, "text": text})
    entries.sort(key=lambda e: e["path"])
    qsets = sorted(inp["question_sets"], key=lambda r: (r["id"], r["version"], r["content_hash"]))
    gv = f"{IMPORT_GENERATOR_PREFIX}:{inp['source_label']}@importer-{inp['tool_version']}"
    digest = canonical.sha256_hash({
        "inputs": {k: summary["inputs"][k]["sha256"] for k in sorted(summary["inputs"])},
        "files": [[e["path"], e["content_hash"]] for e in entries], "question_sets": qsets,
        "runtime_contract_version": inp["contract_version"], "generator_version": gv, "action_rules_version": inp["action_rules_version"],
        "pending_policy": inp["pending_policy"]})
    # 왜 digest 앞 32자리(128비트): 48비트(12자리)는 근거가 없어 바꿨다(docs/adr/0006 보강, 2026-10-29)
    manifest = {
        "pipeline_schema_version": inp["pipeline_schema_version"], "dataset_id": inp["dataset_id"],
        "version": inp["version"] or ("v" + digest[7:39]), "created_at": inp["created_at"], "runtime_contract_version": inp["contract_version"],
        "question_sets": qsets, "generator_version": gv, "seed_case_ids": [], "action_rules_version": inp["action_rules_version"],
        "scenario_disjoint_across_splits": True, "files": entries,
        "ext": {EXT: {"dataset_digest": digest, "import": {
            "inputs": summary["inputs"], "rows_total": summary["total_rows"], "rows_valid": summary["valid_rows"], "rows_invalid": summary["invalid_rows"],
            "invalid_reasons": summary["invalid_reasons_total"], "human_review_counts": summary["human_review_counts"],
            "pending_policy": inp["pending_policy"], "pending_excluded": inp["pending_excluded"], "origin_assumed": "SYNTHETIC",
            "deid_attested": False, "semantic_checks_performed": False, "pii_suspect_rows": summary["pii_rows_total"],
            "cross_split_duplicate_utterances": overlap["duplicate_utterances"], "cross_split_duplicate_inputs": overlap["duplicate_inputs"],
            "tolerance": inp["tolerance"]}}}}
    manifest["content_hash"] = canonical.content_hash(manifest)
    out = {"manifest": manifest, "digest": digest, "files": files}
    check("PackagedDataset", out)
    return out
