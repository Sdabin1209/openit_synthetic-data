"""시드 잡 패키징. RunPackageInput -> PackagedDataset.

파일: <role>/<split>.jsonl. 학습에 쓰지 않은 문항 세트(HELD_OUT_EVAL)의 평가 샘플은 <role>/eval_unseen.jsonl로 따로 쓰고,
모든 파일의 files[].question_sets에 그 파일의 샘플이 쓰는 문항 세트를 적는다(D32). 직렬화는 키 정렬·샘플 ID 순이라 같은 샘플 집합은 항상 같은 바이트다.
해시는 boundary_contracts.canonical로만 계산한다."""
from __future__ import annotations

import json
import tempfile

from boundary_contracts import canonical

from ..types.schema_registry import check

EXT = "synthetic-data"


def _file_hash(text: str) -> str:
    # 왜 임시 파일: 해시는 boundary_contracts.canonical로만 계산한다(자체 구현 금지, 시험 test_hashes_only_via_canonical). canonical의 파일 해시는 경로를 받는다
    with tempfile.NamedTemporaryFile() as f:
        f.write(text.encode("utf-8"))
        f.flush()
        return canonical.file_hash(f.name)


def _line(rec: dict) -> str:
    return json.dumps(rec, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"


def _ref_sort(refs):
    return sorted(refs, key=lambda r: (r["id"], r["version"], r["content_hash"]))


def run(inp: dict) -> dict:
    check("RunPackageInput", inp)
    usage = {c["ref"]["id"]: c["usage"] for c in inp["contexts"]}
    groups: dict[str, list] = {}
    meta: dict[str, tuple] = {}
    for s in inp["samples"]:
        role = "LORA_A" if s["sample_id"].startswith("as-") else "LORA_B"
        unseen = s["split"] == "EVAL" and usage[s["question_set"]["id"]] == "HELD_OUT_EVAL"
        name = "eval_unseen" if unseen else s["split"].lower()
        path = f"{role.lower()}/{name}.jsonl"
        groups.setdefault(path, []).append(s)
        meta[path] = (role, s["split"])
    files, entries, seeds = [], [], set()
    for path in sorted(groups):
        recs = sorted(groups[path], key=lambda r: r["sample_id"])
        text = "".join(_line(r) for r in recs)
        seeds.update(r["seed_case_id"] for r in recs if "seed_case_id" in r)
        refs = {(r["question_set"]["id"], r["question_set"]["version"]): r["question_set"] for r in recs}
        role, split = meta[path]
        entries.append({"path": path, "role": role, "split": split, "sample_count": len(recs),
                        "content_hash": _file_hash(text), "question_sets": _ref_sort(refs.values())})
        files.append({"path": path, "text": text})
    qsets = _ref_sort([c["ref"] for c in inp["contexts"]])
    digest = canonical.sha256_hash({
        "files": [[e["path"], e["content_hash"]] for e in entries], "question_sets": qsets,
        "runtime_contract_version": inp["contract_version"], "generator_version": inp["generator_version"],
        "seed_case_ids": sorted(seeds), "action_rules_version": inp["action_rules_version"]})
    manifest = {
        "pipeline_schema_version": inp["pipeline_schema_version"], "dataset_id": inp["dataset_id"],
        "version": inp["version"] or ("v" + digest[7:39]), "created_at": inp["created_at"],
        "runtime_contract_version": inp["contract_version"], "question_sets": qsets, "generator_version": inp["generator_version"],
        "seed_case_ids": sorted(seeds), "action_rules_version": inp["action_rules_version"],
        "scenario_disjoint_across_splits": True, "files": entries,
        "ext": {EXT: {"dataset_digest": digest,
                      "unseen_eval_files": [e["path"] for e in entries if e["path"].endswith("eval_unseen.jsonl")]}}}
    manifest["content_hash"] = canonical.content_hash(manifest)
    out = {"manifest": manifest, "digest": digest, "files": files}
    check("PackagedDataset", out)
    return out
