"""QuestionBank(문진 스키마) dict를 다루는 읽기 전용 도우미와 값 표현."""
from __future__ import annotations

import re
from typing import Any, Optional


def slot_ref(question: dict, slot: dict) -> dict:
    keys = question.get("repeat_keys") or []
    return {"question_id": question["question_id"], "repeat_key": keys[0] if keys else "", "slot_id": slot["slot_id"]}


def whole_question(question: dict) -> dict:
    return {"question_id": question["question_id"], "whole_question": True}


def question_slot_refs(question: dict) -> list[dict]:
    return [slot_ref(question, s) for s in question["slots"]]


def question_names(bank: dict) -> list[dict]:
    return [{"question_id": q["question_id"], "name": q["name"], "slots": [s["slot_id"] for s in q["slots"]]}
            for q in bank["questions"]]


def slot_kind(slot: dict) -> str:
    if slot.get("yes_no_map"):
        return "YESNO"
    if slot.get("choices") or slot.get("choice_catalog"):
        return "CHOICE"
    if slot.get("units"):
        return "NUMERIC"
    return "FREE"


def render_value(value: Any) -> str:
    """Value(문자열 | {amount, unit} | CodedValue)를 말로 읽는 표기."""
    if isinstance(value, str):
        return value
    if "amount" in value:
        a = value["amount"]
        a = int(a) if float(a).is_integer() else a
        return f"{a}{value['unit']}"
    return value.get("label") or value["code"]


def unit_surface(unit_name: str, n: int) -> str:
    """단위 이름의 수 자리(N)를 채운다. 수 자리가 없으면 수 뒤에 붙인다."""
    return unit_name.replace("N", str(n)) if "N" in unit_name else f"{n}{unit_name}"


def pick_amount(unit: dict, rng) -> int:
    rg = unit.get("range")
    lo, hi = (1, 10)
    if rg:
        lo, hi = max(1, int(-(-rg[0] // 1))), int(rg[1] // 1)
        hi = min(hi, 20)
        if lo > hi:
            lo, hi = 1, 10
    return rng.randint(lo, hi)


def question_texts(bank: dict) -> list[str]:
    out = []
    for q in bank["questions"]:
        out += [q["name"], q["question_sentence"]]
    return out


def find_question(bank: dict, question_id: str) -> Optional[dict]:
    return next((q for q in bank["questions"] if q["question_id"] == question_id), None)


def find_slot(question: dict, slot_id: str) -> Optional[dict]:
    return next((s for s in question["slots"] if s["slot_id"] == slot_id), None)


def fixed_sentence(bank: dict, key: str) -> Optional[str]:
    return next((f["sentence"] for f in bank["session_settings"]["fixed_sentences"] if f["key"] == key), None)


def contains_digit_or_amount(text: str) -> list[str]:
    return re.findall(r"\d+(?:\.\d+)?", text)
