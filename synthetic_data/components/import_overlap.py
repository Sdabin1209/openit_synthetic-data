"""분할 사이 겹침 판정(평가 누수 방지). OverlapInput -> OverlapOutcome.

- 같은 입력: 정규화한 발화 + 입력의 나머지 전부의 해시가 두 분할에 다 있으면 겹침(허용치 판정에 쓴다).
- 같은 발화+맥락: 참고용 집계(판정에 쓰지 않는다).
- 같은 scenario_id가 두 분할에 걸치면 거부(같은 입력 판정을 통과했을 때만 본다).
왜 엄격한 키인가(실측 2026-10-28, docs/adr/0004): 실제 C1 데이터에서 발화+문항만 보면 LoRA-A 8건이 겹쳤지만 모두 state가 달라 입력도 정답도 달랐다."""
from __future__ import annotations

import unicodedata
from typing import Optional

from boundary_contracts import canonical

from ..types.schema_registry import check

_PUNCT = {"P", "S", "Z", "C"}   # 유니코드 General Category(UAX #44): 구두점·기호·구분자·제어. 근거 docs/adr/0004
_PAIRS = (("EVAL", "TRAIN"), ("EVAL", "VALIDATION"), ("TRAIN", "VALIDATION"))


def _normalize(text: str) -> str:
    # 왜 NFKC: 전각/반각 등 호환 문자를 같은 글자로 합치는 유니코드 표준(UAX #15). 실제 데이터의 효과는 측정 안 함(docs/adr/0004)
    t = unicodedata.normalize("NFKC", text).lower()
    return "".join(c for c in t if unicodedata.category(c)[0] not in _PUNCT)


def _input_key(role: str, inp: dict) -> Optional[str]:
    u = _normalize(str(inp.get("user_utterance", "")))
    if not u:
        return None
    return canonical.sha256_hash([role, u, {k: v for k, v in inp.items() if k != "user_utterance"}])


def _utterance_key(role: str, inp: dict) -> Optional[str]:
    u = _normalize(str(inp.get("user_utterance", "")))
    if not u:
        return None
    ctx = [inp.get("question_id")] if role == "LORA_A" else [inp.get("action"), (inp.get("next") or {}).get("question_id")]
    return canonical.sha256_hash([role, u, ctx])


def run(inp: dict) -> dict:
    check("OverlapInput", inp)
    keys = {s: set() for s in ("TRAIN", "VALIDATION", "EVAL")}
    skeys = {s: set() for s in keys}
    scen = {s: set() for s in keys}
    for it in inp["items"]:
        k = _utterance_key(it["role"], it["input"])
        if k:
            keys[it["split"]].add(k)
        k2 = _input_key(it["role"], it["input"])
        if k2:
            skeys[it["split"]].add(k2)
        scen[it["split"]].add(it["scenario_id"])
    dup_utt = {f"{a}~{b}": len(keys[a] & keys[b]) for a, b in _PAIRS}
    dup_in = {f"{a}~{b}": len(skeys[a] & skeys[b]) for a, b in _PAIRS}
    reasons = []
    if max(dup_in.values()) > inp["max_cross_split_duplicates"]:
        reasons.append(f"분할 사이 같은 입력(정규화한 발화+입력 나머지 해시)이 허용 {inp['max_cross_split_duplicates']}건을 넘는다: {dup_in}")
    if not reasons:
        for a, b in _PAIRS:
            both = scen[a] & scen[b]
            if both:
                reasons.append(f"같은 scenario_id가 {a}와 {b}에 걸친다({len(both)}건)")
    out = {"duplicate_utterances": dup_utt, "duplicate_inputs": dup_in, "reasons": reasons}
    check("OverlapOutcome", out)
    return out
