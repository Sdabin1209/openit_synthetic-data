"""감수 샘플링. ReviewSampleInput -> ReviewSample. (역할, 종류)마다 해시 순으로 per_kind개. 사람 감수용 목록이고 게시 대상이 아니다."""
from __future__ import annotations

import json

from boundary_contracts import canonical

from ..types.schema_registry import check


def _derive_int(*parts) -> int:
    return int(canonical.sha256_hash(list(parts))[7:23], 16)


def run(inp: dict) -> dict:
    check("ReviewSampleInput", inp)
    groups: dict[tuple, list] = {}
    for s in inp["samples"]:
        groups.setdefault((s["sample_id"][:2], s["ext"]["synthetic-data"]["kind"]), []).append(s)
    out = []
    for key in sorted(groups):
        pick = sorted(groups[key], key=lambda r: _derive_int(inp["seed"], "review", r["sample_id"]))[:inp["per_kind"]]
        out += sorted(pick, key=lambda r: r["sample_id"])
    text = "".join(json.dumps({"sample_id": s["sample_id"], "kind": s["ext"]["synthetic-data"]["kind"], "split": s["split"],
                               "input": s["input"].get("utterance", s["input"].get("directive", {}).get("action")), "expected": s["expected"]},
                              ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n" for s in out)
    res = {"text": text}
    check("ReviewSample", res)
    return res
