"""규칙·템플릿 기반 생성기. 모델이 필요 없다. 품질이 아니라 파이프라인이 끝까지 도는 것이 목적이다."""
from __future__ import annotations

import random
from typing import Optional

from .. import bank as bk
from .. import josa
from ..rng import derive_int
from ..plans import FactPlan, FactSurface, GeneratorPlan, ParserPlan, UtteranceDraft

_LEADS = ["", "", "", "네, ", "아 그러니까 ", "음 ", "저는 ", "아 "]
_ANSWER_TEMPLATES = ["{s}요", "{s}입니다", "{s} 정도예요", "{s}쯤 돼요", "그냥 {s} 정도요"]
_PHRASES = {
    "SAYS_UNKNOWN": ["모르겠어요", "잘 모르겠는데요", "기억이 안 나요", "글쎄요 모르겠어요"],
    "SAYS_REFUSAL": ["말하기 싫어요", "대답하고 싶지 않아요", "그건 말 안 할래요", "거절할게요"],
    "REPEAT": ["다시 말해 주세요", "한 번만 더 말해 주세요", "뭐라고요"],
    "WAIT": ["잠깐만요", "잠시만 기다려 주세요"],
    "LATER": ["나중에 할게요", "이건 나중에 답할게요", "좀 있다가 할게요"],
    "STOP": ["그만할래요", "여기까지만 할게요", "그만 하고 싶어요"],
    "GUIDE_REQUEST": ["이게 무슨 뜻이에요", "설명해 주세요", "좀 더 알려 주세요"],
    "CONFIRM_YES": ["네", "네 맞아요", "맞아요"],
    "CONFIRM_NO": ["아니요", "아니요 틀려요", "아니에요"],
    "STAFF": ["직원 불러 주세요", "사람이랑 얘기하고 싶어요", "간호사 선생님 불러 주세요"],
    "RESTART": ["처음부터 다시 할래요", "처음부터 다시 해 주세요"],
    "UNRECOGNIZED": ["으으 아아 흐으", "ㅋㅋㅋㅋ", "어어어 그그 음음"],
}
_CORRECTION = ["아니 사실 {s}요", "아 잠깐 {s}예요 잘못 말했어요", "틀렸어요 {s}요"]
_RISK = ["갑자기 {p}", "{p} 같아요", "지금 {p}"]

# 발화 풀: (문장, 문항 이름·문장에 있으면 안 되는 핵심어)
OOS_POOL = [("저 당뇨도 있어요", "당뇨"), ("요즘 날씨가 참 덥네요", "날씨"), ("화장실이 어디예요", "화장실"),
            ("주차장은 어디에 있어요", "주차장"), ("무릎을 다친 적이 있어요", "무릎"), ("이거 몇 시에 끝나요", "몇 시에")]
MEDICAL_QUESTIONS = ["이 약 먹어도 돼요", "저 수술받아도 되나요", "이거 심각한 거예요"]
ACKS = ["네, 알겠습니다.", "알겠습니다.", "네.", "확인했습니다."]


def _surface(fact: FactPlan, rng: random.Random, value=None) -> str:
    v = fact.intended if value is None else value
    kind = fact.hints.get("slot_kind")
    if kind == "NUMERIC":
        n = int(v["amount"]) if float(v["amount"]).is_integer() else v["amount"]
        if fact.hints.get("bare"):
            return str(n)
        return bk.unit_surface(rng.choice(fact.hints["unit_names"]), n)
    if kind == "CHOICE":
        return rng.choice(fact.hints["choice_surfaces"][_choice_key(v)])
    if kind == "YESNO":
        return "네" if fact.hints.get("yes_no") == "yes" else "아니요"
    return v if isinstance(v, str) else bk.render_value(v)


def _choice_key(v) -> str:
    return v if isinstance(v, str) else v["code"]


class RuleUtteranceGenerator:
    name = "rule-utterance"
    version = "0.1.0"

    def generate(self, plan: ParserPlan, rng: random.Random) -> Optional[UtteranceDraft]:
        k = plan.kind
        if k == "EMPTY_UTTERANCE":
            return UtteranceDraft("", [])
        lead = rng.choice(_LEADS)
        f = plan.facts
        if k == "MULTI_SLOT":
            s1, s2 = _surface(f[0], rng), _surface(f[1], rng)
            src2 = rng.choice(_ANSWER_TEMPLATES).format(s=s2)
            return UtteranceDraft(f"{lead}{s1}이고 {src2}",
                                  [FactSurface(s1, s1), FactSurface(src2, s2)])
        if k == "CONFIRM_NO_WITH_VALUE":
            s = _surface(f[1], rng)
            no = rng.choice(_PHRASES["CONFIRM_NO"][:1])
            src2 = rng.choice(_ANSWER_TEMPLATES).format(s=s)
            return UtteranceDraft(f"{no}, {src2}", [FactSurface(no, None), FactSurface(src2, s)])
        if len(f) != 1:
            return None
        fact = f[0]
        it = fact.intent
        if it == "ANSWERED_INTENT" and fact.retracted is not None:
            r, s = _surface(fact, rng, fact.retracted), _surface(fact, rng)
            if r == s:
                return None
            src = f"{r}요, 아니 {s}요"
            return UtteranceDraft(lead + src, [FactSurface(src, s)])
        if it == "ANSWERED_INTENT":
            s = _surface(fact, rng)
            src = s if fact.hints.get("slot_kind") == "YESNO" else rng.choice(_ANSWER_TEMPLATES).format(s=s)
            return UtteranceDraft(lead + src, [FactSurface(src, s)])
        if it == "CORRECTION_MARKED":
            s = _surface(fact, rng)
            src = rng.choice(_CORRECTION).format(s=s)
            return UtteranceDraft(src, [FactSurface(src, s)])
        if it == "RISK_SIGNAL":
            src = rng.choice(_RISK).format(p=fact.hints["phrase"])
            return UtteranceDraft(src, [FactSurface(src, None)])
        if it == "OUT_OF_SCOPE":
            src = fact.hints["phrase"]
            return UtteranceDraft(lead + src, [FactSurface(src, None)])
        key = {"SAYS_UNKNOWN": "SAYS_UNKNOWN", "SAYS_REFUSAL": "SAYS_REFUSAL", "GUIDE_REQUEST": "GUIDE_REQUEST",
               "CONFIRM_YES": "CONFIRM_YES", "CONFIRM_NO": "CONFIRM_NO", "UNRECOGNIZED": "UNRECOGNIZED"}.get(it)
        if it == "PROGRESS_OP":
            key = fact.progress_op
        elif it == "USER_CALLED_STAFF":
            key = "RESTART" if fact.hints.get("restart") else "STAFF"
        if key is None or key not in _PHRASES:
            return None
        src = rng.choice(_PHRASES[key])
        use_lead = lead if it not in ("CONFIRM_YES", "CONFIRM_NO") else ""
        return UtteranceDraft(use_lead + src, [FactSurface(src, None)])


class RuleResponseGenerator:
    """Directive의 구조(행동, 알릴 것, 문장 재료)에서 응답 문장을 만든다. 지시에 없는 값·문항을 말하지 않는다(response_generator.md 1절)."""
    name = "rule-response"
    version = "0.1.0"

    def generate(self, plan: GeneratorPlan, rng: random.Random) -> Optional[str]:
        d = plan.directive
        m = d["sentence_materials"]
        fixed = {x["key"]: x["sentence"] for x in m["fixed_sentences"]}
        act = d["action"]
        qs = " ".join(x["sentence"] for x in m["question_sentences"])
        # 받아 주는 말은 입력(지시+발화)의 함수다: 같은 입력이 다른 정답을 갖지 않게 한다
        ack = ACKS[derive_int(plan.directive, plan.utterance) % len(ACKS)]
        if act == "RISK_NOTICE":                     # 4절: 받아 주지 않고 재료대로만
            return fixed.get("RISK_NOTICE")
        if act in ("CALL_STAFF", "FAREWELL", "WAIT_NOTICE", "STAFF_NOTICE", "ASK_STOP", "ASK_FINISH",
                   "ASK_CORRECTION_TARGET"):
            return fixed.get(act)
        if act == "ASK_REPEAT":
            return " ".join(x for x in (fixed.get("ASK_REPEAT"), qs) if x) or None
        guide = " ".join(x["sentence"] for x in m["guide_sentences"])
        ack_notice = self._correction_ack(d)
        if act == "REDIRECT":
            if plan.hints.get("medical_question"):
                return f"죄송하지만 그 질문에는 도와드리기 어렵습니다. {qs}".strip() if qs else None
            oos = fixed.get("OOS_NOTICE")
            return " ".join(x for x in (ack, oos, qs) if x) if qs else None
        if act in ("ASK_NEXT",):
            parts = [ack_notice or ack, guide, qs]
            return " ".join(x for x in parts if x) if qs else None
        if act in ("ASK_MISSING", "ASK_CLARIFY"):
            re_ = " ".join(x["sentence"] for x in m["reask_sentences"])
            ch = ", ".join(c for x in m["choices"] for c in x["choices"])
            tail = f"{ch} 중에서 말씀해 주세요." if ch else ""
            return " ".join(x for x in (re_, tail) if x) if re_ else None
        if act == "ASK_CONFIRM":
            sv = d["say_values"]
            if not sv or "ASK_CONFIRM" not in fixed:
                return None
            said = ", ".join(f"{s['question_name']} {bk.render_value(s['value'])}" for s in sv)
            return f"{said}. {fixed['ASK_CONFIRM']}"
        if act == "ASK_AFTER_UNKNOWN":
            return " ".join(x for x in (ack, qs) if x) if qs else None
        if act == "ASK_AFTER_REFUSAL":
            rf = " ".join(x["sentence"] for x in m["refusal_explanations"])
            return " ".join(x for x in (rf, qs) if x) if rf and qs else None
        return None

    @staticmethod
    def _correction_ack(d: dict) -> Optional[str]:
        for n in d["notices"]:
            if n["kind"] == "CORRECTION_ACK" and n["value"] is not None and n["previous_value"] is not None:
                name = n["question_name"] or ""
                return (f"{josa.eul_reul(name)} {josa.euro(bk.render_value(n['value']))} 고쳤습니다."
                        if name else None)
        return None
