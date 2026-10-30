"""시드를 문항 세트에 짝짓는다. SeedPairingInput -> SeedPairing.
1.1 레코드는 수집 영역이 채운 question_set 참조로, 1.0 레코드는 설정의 seeds.question_set_id의 가장 높은 버전으로 짝짓는다. 후보는 학습 풀(TRAIN_POOL)의 문항 세트뿐이다."""
from __future__ import annotations

from ..types.schema_registry import check


def run(inp: dict) -> dict:
    check("SeedPairingInput", inp)
    pool = {(c["ref"]["id"], c["ref"]["version"], c["ref"]["content_hash"]): c["ref"] for c in inp["contexts"] if c["usage"] == "TRAIN_POOL"}
    fallback = sorted((r for r in pool.values() if r["id"] == inp["fallback_question_set_id"]), key=lambda r: r["version"])
    pairs, skipped = [], []
    for sd in inp["seeds"]:
        if sd["question_set"] is not None:                       # 1.1 레코드: 수집 영역이 채운 값
            q = sd["question_set"]
            ref = pool.get((q["id"], q["version"], q["content_hash"]))
            why = "시드의 문항 세트가 이번 실행의 학습 풀에 없음"
        else:                                                    # 1.0 레코드 폴백: 설정의 문항 세트
            ref = fallback[-1] if fallback else None
            why = "시드에 문항 세트 참조가 없고 seeds.question_set_id도 없음"
        if ref is None:
            skipped.append({"case_id": sd["case_id"], "reason": why})
        else:
            pairs.append({"seed": sd, "ref": ref})
    out = {"pairs": pairs, "skipped": skipped}
    check("SeedPairing", out)
    return out
