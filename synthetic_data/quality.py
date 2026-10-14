"""품질 검사기. 샘플마다 사유 코드 목록을 돌려준다(빈 목록이면 통과).

검사하는 것: (1) 경계 계약·문진 스키마 통과 (2) 라벨이 발화·문항 정의와 모순되지 않는다 (3) 응답 문장이 응답 지시 밖의 값을 말하지 않는다.
시드(FAILURE_CASE_SEED) 샘플은 사람이 확정한 정답이므로 (1)만 검사한다(대상이 문항 정의에 없는 항목도 실제 데이터에서는 나온다)."""
from __future__ import annotations

import re
from typing import Optional

from . import bank as bk
from .schemas import Validators

_NATIVE = "한|두|세|네|다섯|여섯|일곱|여덟|아홉|열|스물|서른"
_MAX_UTTERANCE = 200
_MAX_RESPONSE = 600
_CTRL = re.compile(r"[\x00-\x08\x0b-\x1f]")


def _schema_reasons(rec: dict, role: str, v: Validators) -> list[str]:
    name = "ParserSample" if role == "PARSER" else "GeneratorSample"
    ins, outs = ("UtteranceParserInput", "ParserOutput") if role == "PARSER" else ("ResponseGeneratorInput", "GeneratorOutput")
    r = []
    if v.check_boundary(name, rec):
        r.append("schema_sample")
    if v.check_survey(ins, rec["input"]):
        r.append("schema_input")
    if v.check_survey(outs, rec["expected"]):
        r.append("schema_expected")
    return r


def check_parser_sample(rec: dict, bank: Optional[dict], v: Validators) -> list[str]:
    reasons = _schema_reasons(rec, "PARSER", v)
    if reasons or rec["origin"] != "SYNTHETIC" or bank is None:
        return reasons
    utt, items = rec["input"]["utterance"], rec["expected"]["items"]
    if len(utt) > _MAX_UTTERANCE or _CTRL.search(utt):
        reasons.append("utterance_form")
    if (utt.strip() == "") != (not items):
        reasons.append("empty_utterance_items_mismatch")
    seen_value, seen_nonvalue = set(), set()
    for i, it in enumerate(items):
        if it["item_no"] != i:
            reasons.append("item_no_order")
        if it["source_text"] not in utt:
            reasons.append("source_not_in_utterance")
        if it["value"] is not None and it["value"] not in it["source_text"]:
            reasons.append("value_not_in_source")
        reasons += _intent_reasons(it, bank, rec["input"])
        t = it["target"]
        if t and "slot_id" in t:
            key = (t["question_id"], t["repeat_key"], t["slot_id"])
            (seen_value if it["intent"] in ("ANSWERED_INTENT", "CORRECTION_MARKED") else seen_nonvalue).add(key)
    if seen_value & seen_nonvalue:
        reasons.append("same_slot_value_and_nonvalue")   # 규칙 8
    return sorted(set(reasons))


def _intent_reasons(it: dict, bank: dict, inp: dict) -> list[str]:
    r, intent, t = [], it["intent"], it["target"]
    q = bk.find_question(bank, t["question_id"]) if t else None
    if t and q is None:
        r.append("target_question_unknown")
    if t and q is not None and "slot_id" in t and bk.find_slot(q, t["slot_id"]) is None:
        r.append("target_slot_unknown")
    if intent in ("ANSWERED_INTENT", "CORRECTION_MARKED"):
        if t is None or "slot_id" not in t:
            r.append("answer_target_not_slot")        # 규칙 1: 문항 전체에 값을 붙이지 않는다
        if it["value"] is None and intent == "ANSWERED_INTENT":
            r.append("answer_without_value")
        if q is not None and t and "slot_id" in t and it["value"] is not None:
            slot = bk.find_slot(q, t["slot_id"])
            if slot is not None and not _value_fits(it["value"], slot):
                r.append("value_contradicts_definition")
    elif intent in ("SAYS_UNKNOWN", "SAYS_REFUSAL"):
        if q is not None:
            single = len(q["slots"]) == 1
            if single != (t is not None and "slot_id" in t):
                r.append("unknown_refusal_target_rule")  # 규칙 1
        if it["value"] is not None:
            r.append("unexpected_value")
    elif intent == "GUIDE_REQUEST":
        if not (t and t.get("whole_question")):
            r.append("guide_target_not_question")
        if it["guide_id"] not in {g["guide_id"] for g in inp["guide_list"]}:
            r.append("guide_id_unknown")
    elif intent == "PROGRESS_OP":
        if it["progress_op"] is None:
            r.append("progress_op_missing")
        if (it["progress_op"] == "LATER") != bool(t and t.get("whole_question")):
            r.append("later_target_rule")
    elif intent in ("CONFIRM_YES", "CONFIRM_NO"):
        if t is not None or it["value"] is not None:
            r.append("confirm_has_target_or_value")      # 규칙 1
    else:
        if t is not None or it["value"] is not None:
            r.append("unexpected_target_or_value")
    if intent != "PROGRESS_OP" and it["progress_op"] is not None:
        r.append("progress_op_unexpected")
    if intent != "GUIDE_REQUEST" and it["guide_id"] is not None:
        r.append("guide_id_unexpected")
    return r


def _value_fits(value: str, slot: dict) -> bool:
    kind = bk.slot_kind(slot)
    if kind == "YESNO":
        return value in ("네", "아니요")
    if kind == "CHOICE":
        names = list(slot.get("choices") or [])
        for c in slot.get("choice_catalog") or []:
            names += [c["label"]] + list(c["synonyms"])
        return any(n and n in value for n in names)
    if kind == "NUMERIC":
        if not (re.search(r"\d", value) or re.search(_NATIVE, value)):
            return False
        names = []
        for u in slot["units"]:
            names += [u["name"]] + list(u.get("synonyms") or [])
        stripped = [n.replace("N", "").strip() for n in names]
        bare = len(slot["units"]) == 1 and re.fullmatch(r"\d+(\.\d+)?", value)
        return bool(bare) or any(s and s in value for s in stripped)
    return bool(value.strip())


def _material_text(d: dict) -> str:
    m = d["sentence_materials"]
    parts = []
    for key in ("question_sentences", "refusal_explanations", "reask_sentences", "guide_sentences", "fixed_sentences"):
        parts += [x["sentence"] for x in m[key]]
    for c in m["choices"]:
        parts += c["choices"]
    for s in d["say_values"]:
        parts += [s["question_name"], bk.render_value(s["value"])]
    for n in d["notices"]:
        parts += [n["question_name"] or "", bk.render_value(n["value"]) if n["value"] is not None else "",
                  bk.render_value(n["previous_value"]) if n["previous_value"] is not None else ""]
    return " ".join(parts)


def check_generator_sample(rec: dict, bank: Optional[dict], v: Validators) -> list[str]:
    reasons = _schema_reasons(rec, "GENERATOR", v)
    if reasons or rec["origin"] != "SYNTHETIC":
        return reasons
    d, text = rec["input"]["directive"], rec["expected"]["response_text"]
    if len(text) > _MAX_RESPONSE or _CTRL.search(text):
        reasons.append("response_form")
    if rec["expected"]["is_fallback"]:
        reasons.append("synthetic_fallback")
    allowed = _material_text(d)
    for num in bk.contains_digit_or_amount(text):
        if num not in allowed:
            reasons.append("value_not_in_directive")     # 응답 지시에 없는 값을 말했다
            break
    m = d["sentence_materials"]
    fixed = {x["key"]: x["sentence"] for x in m["fixed_sentences"]}
    if d["action"] in fixed and d["action"] in ("RISK_NOTICE", "CALL_STAFF", "FAREWELL", "WAIT_NOTICE", "STAFF_NOTICE",
                                                "ASK_STOP", "ASK_FINISH", "ASK_CORRECTION_TARGET"):
        if text != fixed[d["action"]]:
            reasons.append("fixed_sentence_not_verbatim")  # 규칙 4
    if d["action"] in ("ASK_NEXT", "REDIRECT", "ASK_AFTER_UNKNOWN", "ASK_AFTER_REFUSAL", "ASK_REPEAT"):
        for qs in m["question_sentences"]:
            if qs["sentence"] not in text:
                reasons.append("question_sentence_missing")
    return sorted(set(reasons))
