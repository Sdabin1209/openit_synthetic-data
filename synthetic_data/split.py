"""분할기. 분할 단위는 시나리오다: 같은 scenario_id의 샘플(노이즈 변형, 역할이 달라도)은 항상 같은 쪽에 간다.

- HELD_OUT_EVAL 문항 세트의 시나리오는 전부 EVAL이다(학습에 쓰지 않은 문항 세트 평가, D32).
- 나머지는 (시드, scenario_id)의 해시를 비율 구간에 대응시킨다. 입력이 늘거나 줄어도 남은 시나리오의 소속은 바뀌지 않는다.
- 비율은 설정에서 온다. 평가셋 구성(O11)은 사용자 결정이라 이 모듈에 기본값이 없다."""
from __future__ import annotations

from .rng import derive_int


def assign_split(scenario_id: str, usage: str, ratios: dict, seed: int) -> str:
    if usage == "HELD_OUT_EVAL":
        return "EVAL"
    total = sum(ratios.values())
    u = (derive_int(seed, "split", scenario_id) % 10**9) / 10**9 * total
    acc = 0.0
    for name in ("TRAIN", "VALIDATION", "EVAL"):
        acc += ratios[name]
        if u < acc:
            return name
    return "TRAIN" if ratios["TRAIN"] > 0 else "EVAL"
