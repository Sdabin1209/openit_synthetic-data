"""패키저: 분할된 샘플을 JSONL 파일로 쓰고 DatasetManifest를 만든다. 해시는 boundary_contracts.canonical로만 계산한다.

파일: <role>/<split>.jsonl. 학습에 쓰지 않은 문항 세트(HELD_OUT_EVAL)의 평가 샘플은 <role>/eval_unseen.jsonl로 따로 쓰고,
모든 파일의 files[].question_sets에 그 파일의 샘플이 쓰는 문항 세트를 적는다(D32).
직렬화는 키 정렬·샘플 ID 순이라 같은 샘플 집합은 항상 같은 바이트다."""
from __future__ import annotations

import json
from pathlib import Path

from boundary_contracts import canonical

from . import PIPELINE_SCHEMA_VERSION
from .config import JobConfig
from .context import QuestionSetContext

EXT = "synthetic-data"


def dumps_line(rec: dict) -> str:
    return json.dumps(rec, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"


def _ref_sort(refs):
    return sorted(refs, key=lambda r: (r["id"], r["version"], r["content_hash"]))


def package(samples: list, ctxs: list[QuestionSetContext], cfg: JobConfig, *, staging: Path, contract: int,
            generator_version: str, turn_engine_version: str, created_at: str) -> tuple[dict, dict, str]:
    usage = {c.ref["id"]: c.usage for c in ctxs}
    groups: dict[str, list] = {}
    meta: dict[str, tuple] = {}
    for s in samples:
        role = "LORA_A" if s["sample_id"].startswith("as-") else "LORA_B"
        unseen = s["split"] == "EVAL" and usage[s["question_set"]["id"]] == "HELD_OUT_EVAL"
        name = "eval_unseen" if unseen else s["split"].lower()
        path = f"{role.lower()}/{name}.jsonl"
        groups.setdefault(path, []).append(s)
        meta[path] = (role, s["split"])
    staging.mkdir(parents=True, exist_ok=True)
    files, entries, seeds = {}, [], set()
    for path in sorted(groups):
        recs = sorted(groups[path], key=lambda r: r["sample_id"])
        p = staging / path
        p.parent.mkdir(parents=True, exist_ok=True)
        with open(p, "w", encoding="utf-8", newline="\n") as fh:
            for r in recs:
                fh.write(dumps_line(r))
                if "seed_case_id" in r:
                    seeds.add(r["seed_case_id"])
        refs = {(r["question_set"]["id"], r["question_set"]["version"]): r["question_set"] for r in recs}
        role, split = meta[path]
        entries.append({"path": path, "role": role, "split": split, "sample_count": len(recs),
                        "content_hash": canonical.file_hash(p), "question_sets": _ref_sort(refs.values())})
        files[path] = p
    qsets = _ref_sort([c.ref for c in ctxs])
    digest = canonical.sha256_hash({
        "files": [[e["path"], e["content_hash"]] for e in entries], "question_sets": qsets,
        "runtime_contract_version": contract, "generator_version": generator_version,
        "seed_case_ids": sorted(seeds), "turn_engine_version": turn_engine_version})
    manifest = {
        "pipeline_schema_version": PIPELINE_SCHEMA_VERSION, "dataset_id": cfg.dataset_id,
        "version": cfg.version or ("v" + digest[7:19]), "created_at": created_at,
        "runtime_contract_version": contract, "question_sets": qsets, "generator_version": generator_version,
        "seed_case_ids": sorted(seeds), "turn_engine_version": turn_engine_version,
        "scenario_disjoint_across_splits": True, "files": entries,
        "ext": {EXT: {"dataset_digest": digest,
                      "unseen_eval_files": [e["path"] for e in entries if e["path"].endswith("eval_unseen.jsonl")]}}}
    manifest["content_hash"] = canonical.content_hash(manifest)
    return manifest, files, digest
