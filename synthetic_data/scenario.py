"""시나리오 설계기. 문항 세트(QuestionBank)에서 '무엇을 말하고 무엇이 정답이어야 하는가'의 계획을 만든다.

시나리오 ID는 (문항 세트 id, 종류, 문항, 슬롯, 변형 번호)에서만 정해지고 문항 세트 버전과 생성기에는 의존하지 않는다.
그래서 같은 상황의 다른 버전 샘플이 학습과 평가에 갈라지지 않고(분할 단위 = 시나리오), 생성기를 바꿔도 분할이 유지된다.
생성기의 무작위는 시나리오마다 (시드, 시나리오 ID)로 파생하므로 다른 시나리오의 개수가 바뀌어도 이 시나리오는 같다.
"""
from __future__ import annotations

import copy
from dataclasses import dataclass
from typing import Callable, Optional

from . import bank as bk
from . import directives as dv
from .generators.rule import MEDICAL_QUESTIONS, OOS_POOL
from .plans import FactPlan, GeneratorPlan, ParserPlan
from .rng import rng_for, short_hash


@dataclass
class QuestionSetContext:
    ref: dict           # ArtifactRef
    bank: dict          # QuestionBank
    usage: str          # TRAIN_POOL | HELD_OUT_EVAL


def scenario_id(prefix: str, qs_id: str, kind: str, qid: str, slot_id: str, variant: int) -> str:
    return f"{prefix}-{short_hash(qs_id, kind, qid, slot_id, variant)}"


def _guide_list(bank: dict) -> list[dict]:
    return [{"guide_id": g["guide_id"], "selection_criterion": g["selection_criterion"]}
            for g in bank["session_settings"]["guide_list"]]


def _last_directive(q: dict) -> dict:
    """질문 q를 막 물은 직전 응답 지시(ASK_NEXT)."""
    m = dv.empty_materials()
    m["question_sentences"] = [{"question_id": q["question_id"], "sentence": q["question_sentence"]}]
    return dv.directive("ASK_NEXT", bk.question_slot_refs(q), materials=m)


def _base_input(ctx: QuestionSetContext, q: dict, *, last_directive, answered=None) -> dict:
    return {"utterance": "", "last_directive": last_directive,
            "awaiting_questions": [copy.deepcopy(q)], "question_names": bk.question_names(ctx.bank),
            "answered_slots": answered or [], "guide_list": _guide_list(ctx.bank)}


# ---- 값 ----
def _std_value(slot: dict, v: int, rng):
    """슬롯의 v번째 변형 표준 값과 생성기용 힌트."""
    kind = bk.slot_kind(slot)
    hints = {"slot_kind": kind}
    if kind == "NUMERIC":
        unit = slot["units"][v % len(slot["units"])]
        n = bk.pick_amount(unit, rng)
        val = {"amount": n, "unit": unit["name"]}
        if unit.get("code"):
            val["unit_code"] = unit["code"]
        hints["unit_names"] = [unit["name"]] + list(unit.get("synonyms") or [])
        hints["bare"] = len(slot["units"]) == 1 and v % 2 == 1
        return val, hints
    if kind == "CHOICE":
        if slot.get("choice_catalog"):
            cat = slot["choice_catalog"]
            c = cat[v % len(cat)]
            hints["choice_surfaces"] = {x["code"]: [x["label"]] + list(x["synonyms"]) for x in cat}
            return {"code": c["code"], "label": c["label"]}, hints
        ch = slot["choices"]
        hints["choice_surfaces"] = {x: [x] for x in ch}
        return ch[v % len(ch)], hints
    if kind == "YESNO":
        yes = v % 2 == 0
        hints["yes_no"] = "yes" if yes else "no"
        return slot["yes_no_map"]["yes" if yes else "no"], hints
    pool = ["가끔 배가 아파요", "조금 어지러워요", "특별히 없어요", "잠을 잘 못 자요"]
    return pool[v % len(pool)], hints


def _distinct_value(slot: dict, v: int, rng):
    """v번째와 다른 값(정정·확인 부정용)."""
    a, ha = _std_value(slot, v, rng)
    for i in range(1, 6):
        b, hb = _std_value(slot, v + i, rng)
        if b != a:
            return a, ha, b, hb
    return None


def _pq(pid: str, kind: str, qs: QuestionSetContext, q: dict, base: dict, facts: list[FactPlan], hints=None) -> ParserPlan:
    return ParserPlan(pid, kind, qs.ref, base, facts, hints or {})


# ---- 파서 종류: (범위, 적용 조건, 계획 함수). 계획 함수는 (ctx, q, slot, v, rng, sid) -> ParserPlan | None ----
def _k_answer(ctx, q, slot, v, rng, sid):
    val, h = _std_value(slot, v, rng)
    fact = FactPlan("ANSWERED_INTENT", bk.slot_ref(q, slot), val, hints=h)
    kind = "ANSWER_" + h["slot_kind"]
    return _pq(sid, kind, ctx, q, _base_input(ctx, q, last_directive=_last_directive(q)), [fact])


def _k_unknown_refusal(intent):
    def f(ctx, q, slot, v, rng, sid):
        tgt = bk.slot_ref(q, q["slots"][0]) if len(q["slots"]) == 1 else bk.whole_question(q)   # 규칙 1
        return _pq(sid, intent, ctx, q, _base_input(ctx, q, last_directive=_last_directive(q)), [FactPlan(intent, tgt)])
    return f


def _k_progress(op):
    def f(ctx, q, slot, v, rng, sid):
        tgt = bk.whole_question(q) if op == "LATER" else None                                    # 규칙 1
        return _pq(sid, "PROGRESS_" + op, ctx, q, _base_input(ctx, q, last_directive=_last_directive(q)),
                   [FactPlan("PROGRESS_OP", tgt, progress_op=op)])
    return f


def _k_guide(ctx, q, slot, v, rng, sid):
    gl = ctx.bank["session_settings"]["guide_list"]
    if len(gl) != 1:        # 어느 안내 항목인지 발화만으로 정해지지 않으면 만들지 않는다
        return None
    return _pq(sid, "GUIDE_REQUEST", ctx, q, _base_input(ctx, q, last_directive=_last_directive(q)),
               [FactPlan("GUIDE_REQUEST", bk.whole_question(q), guide_id=gl[0]["guide_id"])])


def _confirm_directive(ctx, q, slot, val):
    sref = bk.slot_ref(q, slot)
    m = dv.empty_materials()
    m["question_sentences"] = [{"question_id": q["question_id"], "sentence": q["question_sentence"]}]
    s = bk.fixed_sentence(ctx.bank, "ASK_CONFIRM")
    if s:
        m["fixed_sentences"] = [{"key": "ASK_CONFIRM", "sentence": s}]
    return dv.directive("ASK_CONFIRM", [sref], say_values=[dv.say_value(sref, q["name"], val, "PENDING")],
                        materials=m, target_pending_id="pend-1")


def _k_confirm(intent):
    def f(ctx, q, slot, v, rng, sid):
        val, h = _std_value(slot, v, rng)
        base = _base_input(ctx, q, last_directive=_confirm_directive(ctx, q, slot, val))
        return _pq(sid, intent, ctx, q, base, [FactPlan(intent, None)])
    return f


def _k_confirm_no_value(ctx, q, slot, v, rng, sid):
    d = _distinct_value(slot, v, rng)
    if d is None:
        return None
    a, _, b, hb = d
    base = _base_input(ctx, q, last_directive=_confirm_directive(ctx, q, slot, a))
    return _pq(sid, "CONFIRM_NO_WITH_VALUE", ctx, q, base,
               [FactPlan("CONFIRM_NO", None), FactPlan("ANSWERED_INTENT", bk.slot_ref(q, slot), b, hints=hb)])


def _answered(q, slot, val) -> list[dict]:
    return [{"slot": bk.slot_ref(q, slot), "value": val}]


def _k_correction(ctx, q, slot, v, rng, sid):
    d = _distinct_value(slot, v, rng)
    if d is None:
        return None
    a, _, b, hb = d
    base = _base_input(ctx, q, last_directive=_last_directive(q), answered=_answered(q, slot, a))
    return _pq(sid, "CORRECTION_MARKED", ctx, q, base,
               [FactPlan("CORRECTION_MARKED", bk.slot_ref(q, slot), b, hints=hb)])


def _k_self_correct(ctx, q, slot, v, rng, sid):
    d = _distinct_value(slot, v, rng)
    if d is None:
        return None
    a, _, b, hb = d
    return _pq(sid, "SELF_CORRECT", ctx, q, _base_input(ctx, q, last_directive=_last_directive(q)),
               [FactPlan("ANSWERED_INTENT", bk.slot_ref(q, slot), b, retracted=a, hints=hb)])


def _k_multi(ctx, q, slot, v, rng, sid):
    facts = []
    for i, s in enumerate(q["slots"][:2]):
        val, h = _std_value(s, v + i, rng)
        facts.append(FactPlan("ANSWERED_INTENT", bk.slot_ref(q, s), val, hints=h))
    return _pq(sid, "MULTI_SLOT", ctx, q, _base_input(ctx, q, last_directive=_last_directive(q)), facts)


def _bank_q(ctx, v):
    qs = ctx.bank["questions"]
    return qs[v % len(qs)]


def _k_staff(restart):
    def f(ctx, q, slot, v, rng, sid):
        return _pq(sid, "RESTART_REQUEST" if restart else "STAFF_REQUEST", ctx, q,
                   _base_input(ctx, q, last_directive=_last_directive(q)),
                   [FactPlan("USER_CALLED_STAFF", None, hints={"restart": restart})])
    return f


def _oos_pool(ctx):
    texts = " ".join(bk.question_texts(ctx.bank))
    return [p for p, key in OOS_POOL if key not in texts]


def _k_oos(ctx, q, slot, v, rng, sid):
    pool = _oos_pool(ctx)
    if not pool:
        return None
    return _pq(sid, "OUT_OF_SCOPE", ctx, q, _base_input(ctx, q, last_directive=_last_directive(q)),
               [FactPlan("OUT_OF_SCOPE", None, hints={"phrase": pool[v % len(pool)]})])


def _k_risk(ctx, q, slot, v, rng, sid):
    phrases = ctx.bank["session_settings"]["risk_phrases"]
    if not phrases:
        return None
    return _pq(sid, "RISK_SIGNAL", ctx, q, _base_input(ctx, q, last_directive=_last_directive(q)),
               [FactPlan("RISK_SIGNAL", None, hints={"phrase": phrases[v % len(phrases)]})])


def _k_unrec(ctx, q, slot, v, rng, sid):
    return _pq(sid, "UNRECOGNIZED", ctx, q, _base_input(ctx, q, last_directive=_last_directive(q)),
               [FactPlan("UNRECOGNIZED", None)])


def _k_empty(ctx, q, slot, v, rng, sid):
    return _pq(sid, "EMPTY_UTTERANCE", ctx, q, _base_input(ctx, q, last_directive=_last_directive(q)), [])


_S, _Q, _B = "slot", "question", "bank"
PARSER_KINDS: dict[str, tuple[str, Callable, Callable]] = {
    "ANSWER": (_S, lambda ctx, q, s: True, _k_answer),
    "SAYS_UNKNOWN": (_Q, lambda ctx, q, s: True, _k_unknown_refusal("SAYS_UNKNOWN")),
    "SAYS_REFUSAL": (_Q, lambda ctx, q, s: True, _k_unknown_refusal("SAYS_REFUSAL")),
    "PROGRESS_REPEAT": (_Q, lambda ctx, q, s: True, _k_progress("REPEAT")),
    "PROGRESS_WAIT": (_Q, lambda ctx, q, s: True, _k_progress("WAIT")),
    "PROGRESS_LATER": (_Q, lambda ctx, q, s: True, _k_progress("LATER")),
    "PROGRESS_STOP": (_Q, lambda ctx, q, s: True, _k_progress("STOP")),
    "GUIDE_REQUEST": (_Q, lambda ctx, q, s: len(ctx.bank["session_settings"]["guide_list"]) == 1, _k_guide),
    "CONFIRM_YES": (_S, lambda ctx, q, s: True, _k_confirm("CONFIRM_YES")),
    "CONFIRM_NO": (_S, lambda ctx, q, s: True, _k_confirm("CONFIRM_NO")),
    "CONFIRM_NO_WITH_VALUE": (_S, lambda ctx, q, s: bk.slot_kind(s) in ("NUMERIC", "CHOICE"), _k_confirm_no_value),
    "CORRECTION_MARKED": (_S, lambda ctx, q, s: bk.slot_kind(s) in ("NUMERIC", "CHOICE"), _k_correction),
    "SELF_CORRECT": (_S, lambda ctx, q, s: bk.slot_kind(s) in ("NUMERIC", "CHOICE"), _k_self_correct),
    "MULTI_SLOT": (_Q, lambda ctx, q, s: len(q["slots"]) >= 2 and all(
        bk.slot_kind(x) in ("NUMERIC", "CHOICE") for x in q["slots"][:2]), _k_multi),
    "STAFF_REQUEST": (_B, lambda ctx, q, s: True, _k_staff(False)),
    "RESTART_REQUEST": (_B, lambda ctx, q, s: True, _k_staff(True)),
    "OUT_OF_SCOPE": (_B, lambda ctx, q, s: bool(_oos_pool(ctx)), _k_oos),
    "RISK_SIGNAL": (_B, lambda ctx, q, s: bool(ctx.bank["session_settings"]["risk_phrases"]), _k_risk),
    "UNRECOGNIZED": (_B, lambda ctx, q, s: True, _k_unrec),
    "EMPTY_UTTERANCE": (_B, lambda ctx, q, s: True, _k_empty),
}


def _iter_targets(ctx, scope, applies, question_filter):
    qs = [q for q in ctx.bank["questions"] if question_filter is None or q["question_id"] in question_filter]
    if scope == _B:
        if qs:
            yield None, None
        return
    for q in qs:
        if scope == _Q:
            if applies(ctx, q, None):
                yield q, None
        else:
            for s in q["slots"]:
                if applies(ctx, q, s):
                    yield q, s


def design_parser_plans(ctx: QuestionSetContext, *, variants: int, seed: int, kinds: Optional[list] = None,
                        question_filter: Optional[set] = None) -> tuple[list[ParserPlan], dict]:
    plans, stats = [], {"not_applicable": 0}
    for kind, (scope, applies, fn) in PARSER_KINDS.items():
        if kinds and kind not in kinds:
            continue
        if scope == _B and not applies(ctx, None, None):
            stats["not_applicable"] += 1
            continue
        for q, s in _iter_targets(ctx, scope, applies, question_filter):
            for v in range(variants):
                qq = q if q is not None else _bank_q(ctx, v)
                if scope == _B and question_filter is not None and qq["question_id"] not in question_filter:
                    continue
                sid = scenario_id("sc", ctx.ref["id"], kind, qq["question_id"], s["slot_id"] if s else "-", v)
                p = fn(ctx, qq, s, v, rng_for(seed, "plan", sid), sid)
                if p is None:
                    stats["not_applicable"] += 1
                else:
                    plans.append(p)
    return plans, stats


# ---- 생성기(LoRA-B) 종류 ----
FIXED_ONLY = ["RISK_NOTICE", "CALL_STAFF", "FAREWELL", "WAIT_NOTICE", "STAFF_NOTICE", "ASK_STOP", "ASK_FINISH",
              "ASK_CORRECTION_TARGET"]


def _gp(sid, kind, ctx, d, utt, hints=None) -> GeneratorPlan:
    return GeneratorPlan(sid, kind, ctx.ref, d, utt, hints or {})


def _mat(ctx, q=None, fixed_keys=(), **extra) -> dict:
    m = dv.empty_materials()
    if q is not None:
        m["question_sentences"] = [{"question_id": q["question_id"], "sentence": q["question_sentence"]}]
    for k in fixed_keys:
        s = bk.fixed_sentence(ctx.bank, k)
        if s:
            m["fixed_sentences"].append({"key": k, "sentence": s})
    m.update(extra)
    return m


def design_generator_plans(ctx: QuestionSetContext, *, variants: int, seed: int,
                           question_filter: Optional[set] = None) -> tuple[list[GeneratorPlan], dict]:
    plans: list[GeneratorPlan] = []
    stats = {"not_applicable": 0}
    qs = [q for q in ctx.bank["questions"] if question_filter is None or q["question_id"] in question_filter]

    def add(p):
        if p is None:
            stats["not_applicable"] += 1
        else:
            plans.append(p)

    for v in range(variants):
        for q in qs:
            refs = bk.question_slot_refs(q)
            qid = q["question_id"]
            prev = [None, "네", "알겠습니다"][v % 3]
            sid = scenario_id("sg", ctx.ref["id"], "GEN_ASK_NEXT", qid, "-", v)
            add(_gp(sid, "GEN_ASK_NEXT", ctx, dv.directive("ASK_NEXT", refs, materials=_mat(ctx, q)), prev))
            for kind, texts in (("GEN_ASK_AFTER_UNKNOWN", ["모르겠어요", "잘 모르겠어요", "기억이 안 나요"]),
                                ("GEN_ASK_AFTER_REFUSAL", ["말하기 싫어요", "대답하고 싶지 않아요", "그건 말 안 할래요"])):
                text = texts[v % len(texts)]
                sid = scenario_id("sg", ctx.ref["id"], kind, qid, "-", v)
                if kind.endswith("REFUSAL"):
                    m = _mat(ctx, q, refusal_explanations=[{"question_id": qid, "sentence": q["refusal_explanation"]}])
                    act = "ASK_AFTER_REFUSAL"
                else:
                    m, act = _mat(ctx, q), "ASK_AFTER_UNKNOWN"
                add(_gp(sid, kind, ctx, dv.directive(act, refs, materials=m), text))
            if q["guide_sentences"]:
                g = q["guide_sentences"][v % len(q["guide_sentences"])]
                m = _mat(ctx, q, guide_sentences=[{"guide_id": g["guide_id"], "question_id": qid, "sentence": g["sentence"]}])
                sid = scenario_id("sg", ctx.ref["id"], "GEN_GUIDE", qid, "-", v)
                add(_gp(sid, "GEN_GUIDE", ctx, dv.directive(
                    "ASK_NEXT", refs, notices=[dv.notice("GUIDE", guide_id=g["guide_id"], question_id=qid, question_name=q["name"])],
                    materials=m), ["설명해 주세요", "이게 무슨 뜻이에요", "좀 더 알려 주세요"][v % 3]))
            for slot in q["slots"]:
                sref, sl = bk.slot_ref(q, slot), slot["slot_id"]
                rng = rng_for(seed, "gplan", qid, sl, v)
                if slot["required"]:
                    sid = scenario_id("sg", ctx.ref["id"], "GEN_ASK_MISSING", qid, sl, v)
                    m = _mat(ctx, q, reask_sentences=[{"slot": sref, "sentence": slot["reask_sentence"]}])
                    add(_gp(sid, "GEN_ASK_MISSING", ctx, dv.directive("ASK_MISSING", [sref], reask_reasons=["MISSING_SLOT"], materials=m), None))
                sid = scenario_id("sg", ctx.ref["id"], "GEN_ASK_CLARIFY", qid, sl, v)
                kind = bk.slot_kind(slot)
                choices = ([c["label"] for c in slot["choice_catalog"]] if slot.get("choice_catalog") else list(slot["choices"]))
                m = _mat(ctx, q, reask_sentences=[{"slot": sref, "sentence": slot["reask_sentence"]}])
                if kind == "CHOICE" and choices:
                    m["choices"] = [{"slot": sref, "choices": choices}]
                reason = "NO_UNIT" if kind == "NUMERIC" and len(slot["units"]) > 1 else "AMBIGUOUS"
                add(_gp(sid, "GEN_ASK_CLARIFY", ctx, dv.directive("ASK_CLARIFY", [sref], reask_reasons=[reason], materials=m), "가끔이요"))
                val, _ = _std_value(slot, v, rng)
                sid = scenario_id("sg", ctx.ref["id"], "GEN_ASK_CONFIRM", qid, sl, v)
                if bk.fixed_sentence(ctx.bank, "ASK_CONFIRM"):
                    add(_gp(sid, "GEN_ASK_CONFIRM", ctx, _confirm_directive(ctx, q, slot, val), "그런 것 같아요"))
                else:
                    stats["not_applicable"] += 1
                d = _distinct_value(slot, v, rng)
                if d and kind in ("NUMERIC", "CHOICE"):
                    a, _, b, _ = d
                    sid = scenario_id("sg", ctx.ref["id"], "GEN_CORRECTION_ACK", qid, sl, v)
                    n = dv.notice("CORRECTION_ACK", question_id=qid, question_name=q["name"])
                    n.update(slot=sref, previous_value=a, value=b)
                    add(_gp(sid, "GEN_CORRECTION_ACK", ctx, dv.directive("ASK_NEXT", refs, notices=[n], materials=_mat(ctx, q)), "아니 사실 다르게 말했어요"))
        if qs:
            q = qs[v % len(qs)]
            refs = bk.question_slot_refs(q)
            aw = dv.ask_directive("ASK_NEXT", refs)
            pool = _oos_pool(ctx)
            if pool and bk.fixed_sentence(ctx.bank, "OOS_NOTICE"):
                sid = scenario_id("sg", ctx.ref["id"], "GEN_REDIRECT", q["question_id"], "-", v)
                add(_gp(sid, "GEN_REDIRECT", ctx, dv.directive("REDIRECT", refs, awaiting=aw, materials=_mat(ctx, q, ["OOS_NOTICE"])), pool[v % len(pool)]))
            else:
                stats["not_applicable"] += 1
            sid = scenario_id("sg", ctx.ref["id"], "GEN_MEDICAL_QUESTION", q["question_id"], "-", v)
            add(_gp(sid, "GEN_MEDICAL_QUESTION", ctx, dv.directive("REDIRECT", refs, awaiting=aw, materials=_mat(ctx, q)),
                    MEDICAL_QUESTIONS[v % len(MEDICAL_QUESTIONS)], {"medical_question": True}))
            for act in FIXED_ONLY:
                if not bk.fixed_sentence(ctx.bank, act):
                    stats["not_applicable"] += 1
                    continue
                utt = None
                if act == "RISK_NOTICE":
                    ph = ctx.bank["session_settings"]["risk_phrases"]
                    utt = ph[v % len(ph)] if ph else None
                sid = scenario_id("sg", ctx.ref["id"], "GEN_" + act, q["question_id"], "-", v)
                add(_gp(sid, "GEN_" + act, ctx, dv.directive(act, refs, awaiting=aw, materials=_mat(ctx, q, [act])), utt))
            if bk.fixed_sentence(ctx.bank, "ASK_REPEAT"):
                sid = scenario_id("sg", ctx.ref["id"], "GEN_ASK_REPEAT", q["question_id"], "-", v)
                add(_gp(sid, "GEN_ASK_REPEAT", ctx, dv.directive("ASK_REPEAT", refs, materials=_mat(ctx, q, ["ASK_REPEAT"])), "다시 말해 주세요"))
            else:
                stats["not_applicable"] += 1
    return plans, stats
