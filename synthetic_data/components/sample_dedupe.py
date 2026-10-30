"""같은 입력의 중복을 정리한다. DedupeInput -> DedupeResult.
사람이 확정한 정답(FAILURE_CASE_SEED)이 이긴다. 같은 입력에 다른 정답이면 라벨 잡음이라 전부 뺀다. 같은 입력·같은 정답은 하나만 남긴다."""
from __future__ import annotations

from collections import Counter

from boundary_contracts import canonical

from ..types.schema_registry import check


def run(inp: dict) -> dict:
    check("DedupeInput", inp)
    dropped = Counter()
    by_input: dict = {}
    for s in sorted(inp["samples"], key=lambda r: r["sample_id"]):
        by_input.setdefault(canonical.sha256_hash([s["sample_id"][:2], s["input"]]), []).append(s)
    final = []
    for key in sorted(by_input):
        group = by_input[key]
        seed_first = sorted(group, key=lambda r: (r["origin"] != "FAILURE_CASE_SEED", r["sample_id"]))
        if seed_first[0]["origin"] == "FAILURE_CASE_SEED":     # 사람이 확정한 정답이 이긴다
            dropped["synthetic_dropped_for_seed_input"] += sum(1 for g in group if g["origin"] != "FAILURE_CASE_SEED")
            dropped["duplicate_input"] += sum(1 for g in group if g["origin"] == "FAILURE_CASE_SEED") - 1
            final.append(seed_first[0])
        elif len({canonical.sha256_hash(g["expected"]) for g in group}) > 1:
            dropped["input_label_conflict"] += len(group)      # 같은 입력에 다른 정답: 라벨 잡음이라 전부 뺀다
        else:
            final.append(seed_first[0])
            dropped["duplicate_input"] += len(group) - 1
    out = {"samples": final, "dropped": dict(dropped)}
    check("DedupeResult", out)
    return out
