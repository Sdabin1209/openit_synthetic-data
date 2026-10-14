"""정답 구성기: 발화 초안의 글자 위치로 ParserOutput을 만든다. 라벨 기준은 docs/rules/utterance_parser.md 4절이다.
의도·대상·진행 조작·안내 ID는 시나리오 계획(FactPlan)이 정하고, 이 모듈은 값 글자와 원문 위치만 채운다."""
from __future__ import annotations

from .plans import FactPlan, FactSurface


class LabelError(ValueError):
    pass


def build_parser_expected(facts: list, utterance: str, surfaces: list) -> dict:
    if len(facts) != len(surfaces):
        raise LabelError("사실 수와 초안의 사실 수가 다르다")
    items, pos = [], 0
    for i, (fp, fs) in enumerate(zip(facts, surfaces)):
        a = utterance.find(fs.source, pos)
        if a < 0 or not fs.source:
            raise LabelError(f"원문을 발화에서 찾을 수 없다: {fs.source!r}")
        item = {"item_no": i, "target": fp.target, "value": fs.value, "source_text": fs.source,
                "intent": fp.intent, "progress_op": fp.progress_op, "guide_id": fp.guide_id}
        if fs.value is not None:
            rel = fs.source.find(fs.value)
            if rel < 0:
                raise LabelError(f"값이 원문 안에 없다: {fs.value!r}")
            s = a + rel
            item["evidence"] = [{"start": s, "end": s + len(fs.value), "offset_unit": "unicode_code_point", "text": fs.value}]
        pos = a + len(fs.source)
        items.append(item)
    return {"items": items}
