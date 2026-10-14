"""이웃 영역 대역(test double). 소유 영역(question-authoring, ops-feedback)의 메모리 구현이 나오면 이 파일의 클래스를
그쪽 구현으로 바꾼다. 둘 다 boundary_contracts.sdk의 Protocol(I1 QuestionReader, I7 FailureStore)만 따른다.
오류와 멱등성은 CONVENTIONS.md대로 BoundaryError를 던진다."""
from __future__ import annotations

import copy
from datetime import datetime
from typing import Optional

from boundary_contracts import canonical
from boundary_contracts.errors import BoundaryError


# ---------- 문항 세트 ----------
def _slot(slot_id, *, units=None, choices=None, yes_no=None, catalog=None, required=True):
    s = {"slot_id": slot_id, "units": units or [], "choices": choices or [], "yes_no_map": yes_no,
         "required": required, "reask_sentence": f"{slot_id} 값을 다시 말씀해 주세요.", "risk_rule": None}
    if catalog:
        s["choice_catalog"] = catalog
        s["choices"] = []
    return s


def _q(qid, order, name, sentence, slots, guide=None):
    return {"question_id": qid, "name": name, "order": order, "prerequisite": None, "question_sentence": sentence,
            "refusal_explanation": f"{name}은 건강 상태를 파악하는 데 쓰여서 여쭙니다.",
            "guide_sentences": guide or [], "affected_followups": [],
            "policy": {"question_limit": 3, "unknown_accept_after": 2, "refusal_accept_after": 2},
            "repeat_keys": [], "slots": slots}


def make_bank(flavor: str = "main", *, wording: str = "") -> dict:
    fixed = [{"key": k, "sentence": s} for k, s in [
        ("ASK_REPEAT", "다시 말씀드릴게요."), ("OOS_NOTICE", "그 내용은 이번 문진에서 받지 않습니다."),
        ("CALL_STAFF", "직원을 불러 드리겠습니다."), ("FAREWELL", "문진이 끝났습니다. 감사합니다."),
        ("ASK_CONFIRM", "맞으면 네라고 말씀해 주세요."), ("ASK_CORRECTION_TARGET", "어떤 답을 고칠까요?"),
        ("ASK_FINISH", "마칠까요?"), ("RISK_NOTICE", "위험할 수 있어 직원이 곧 도와드리겠습니다."),
        ("RESUME", "이어서 하겠습니다."), ("SURVEY_STOPPED", "문진을 멈췄습니다."),
        ("WAIT_NOTICE", "천천히 말씀해 주세요."), ("ASK_STOP", "문진을 그만할까요?"),
        ("STAFF_NOTICE", "직원이 확인하고 있습니다."), ("DEFERRED", "나중에 다시 여쭙겠습니다.")]]
    if flavor == "main":
        qs = [
            _q("Q1", 1, "흡연", "담배를 피우시나요?" + wording,
               [_slot("status", choices=["피우지 않음", "과거에 피움", "현재 피움"])],
               guide=[{"guide_id": "g1", "sentence": "흡연은 담배를 피우는 습관을 말합니다."}]),
            _q("Q2", 2, "음주", "일주일에 술을 몇 번 드세요?",
               [_slot("times", units=[{"name": "번", "synonyms": ["회"], "range": [1, 7], "convert_to": None}])]),
            _q("Q3", 3, "수면", "하루에 몇 시간 주무세요?",
               [_slot("hours", units=[{"name": "시간", "synonyms": [], "range": [1, 12], "convert_to": None}])]),
            _q("Q4", 4, "운동", "일주일에 며칠, 하루 몇 분 운동하세요?",
               [_slot("days", units=[{"name": "일", "synonyms": ["날"], "range": [1, 7], "convert_to": None}]),
                _slot("minutes", units=[{"name": "분", "synonyms": [], "range": [10, 120], "convert_to": None}])]),
            _q("Q5", 5, "폭음", "한 번에 많이 마신 적이 있으세요?",
               [_slot("binge", yes_no={"yes": "예", "no": "아니오"})]),
        ]
    else:
        qs = [
            _q("U1", 1, "커피", "하루에 커피를 몇 잔 드세요?",
               [_slot("cups", units=[{"name": "잔", "synonyms": [], "range": [1, 10], "convert_to": None}])]),
            _q("U2", 2, "식사", "식사는 규칙적인가요?",
               [_slot("regular", catalog=[
                   {"code": "REG", "label": "규칙적", "synonyms": ["꼬박꼬박"]},
                   {"code": "IRR", "label": "불규칙", "synonyms": ["들쭉날쭉"]}])]),
        ]
    return {"version": 1, "questions": qs, "session_settings": {
        "risk_phrases": ["가슴이 너무 아파요"], "confirm_limit": 2, "unrecognized_streak_limit": 3, "ask_limit": 5,
        "fixed_sentences": fixed,
        "guide_list": [{"guide_id": "g1", "selection_criterion": "용어의 뜻을 물을 때", "per_question": False,
                        "sentence": None, "fill_value": None}]}}


def ref_of(set_id: str, version: str, bank: dict) -> dict:
    return {"id": set_id, "version": version, "content_hash": canonical.sha256_hash(bank)}


class FakeQuestionReader:
    """I1 QuestionReader 대역."""

    def __init__(self):
        self._banks: dict[tuple, dict] = {}
        self._order: dict[str, list] = {}
        self._reviews: dict[tuple, list] = {}
        self._changes: dict[tuple, dict] = {}
        self.calls: list[str] = []

    def add(self, set_id: str, version: str, bank: dict, *, approved: bool = True, change: Optional[dict] = None) -> dict:
        ref = ref_of(set_id, version, bank)
        self._banks[(set_id, version)] = copy.deepcopy(bank)
        self._order.setdefault(set_id, []).append(ref)
        self._reviews[(set_id, version)] = ([{"review_id": f"rv-{set_id}-{version}", "decision": "APPROVED",
                                              "clinical_basis_approved": True}] if approved else [])
        if change is not None:
            self._changes[(set_id, version)] = change
        return ref

    def get_question_bank(self, ref):
        self.calls.append("get_question_bank")
        b = self._banks.get((ref["id"], ref["version"]))
        if b is None:
            raise BoundaryError("NOT_FOUND", "문항 세트가 없다")
        if canonical.sha256_hash(b) != ref["content_hash"]:
            raise BoundaryError("INTEGRITY_ERROR", "해시 불일치")
        return copy.deepcopy(b)

    def latest(self, question_set_id, *, reviewed_only=False):
        refs = self._order.get(question_set_id, [])
        if reviewed_only:
            refs = [r for r in refs if self._reviews[(r["id"], r["version"])]]
        if not refs:
            raise BoundaryError("NOT_FOUND", "문항 세트가 없다")
        return dict(refs[-1])

    def list_versions(self, question_set_id, *, cursor=None, limit=100):
        refs = self._order.get(question_set_id, [])
        start = int(cursor or 0)
        page = refs[start:start + limit]
        return [dict(r) for r in page], (str(start + limit) if start + limit < len(refs) else None)

    def get_reviews(self, ref):
        return copy.deepcopy(self._reviews.get((ref["id"], ref["version"]), []))

    def get_change(self, ref):
        return copy.deepcopy(self._changes.get((ref["id"], ref["version"])))


def make_question_reader(**_ignored) -> FakeQuestionReader:
    """설정 파일의 adapters.question_reader.factory가 부르는 공장."""
    r = FakeQuestionReader()
    r.add("qs-main", "1", make_bank("main"))
    r.add("qs-unseen", "1", make_bank("unseen"))
    return r


# ---------- 실패 사례 ----------
def make_trace(case_id: str, *, parser_input=None, parser_output=None, generator_input=None, generator_output=None) -> dict:
    keys = ["frontend_message", "intervention_decision", "orchestrator_input", "parser_input", "parser_output",
            "normalizer_input", "normalizer_output", "judge_input", "judge_output", "record_writer_input",
            "record_writer_output", "planner_input", "planner_output", "generator_input", "generator_output",
            "frontend_input", "staff_console_input", "dispatch_input", "dispatch_output", "orchestrator_output",
            "session_before", "session_after", "log_entry", "persistence_load_request", "persistence_load_result",
            "persistence_commit_request", "persistence_commit_result"]
    t = {k: None for k in keys}
    t.update(session_id="sess-" + case_id, turn_id="t1", contract_version=1, turn_index=0,
             parser_input=parser_input, parser_output=parser_output, generator_input=generator_input,
             generator_output=generator_output)
    return t


class FakeFailureStore:
    """I7 FailureStore 대역."""

    def __init__(self):
        self._cases: dict[str, list] = {}
        self._traces: dict[str, dict] = {}

    def add(self, case: dict, trace: Optional[dict] = None):
        self._cases.setdefault(case["case_id"], []).append(copy.deepcopy(case))
        if trace is not None:
            self._traces[case["deidentified_trace_ref"]] = copy.deepcopy(trace)

    def publish_case(self, case):
        self.add(case)
        return case

    def get_case(self, case_id, *, version=None):
        vs = self._cases.get(case_id)
        if not vs:
            raise BoundaryError("NOT_FOUND", "사례가 없다")
        return copy.deepcopy(vs[-1] if version is None else next(c for c in vs if c["version"] == version))

    def list_cases(self, *, review_status=None, failure_type=None, source_release_id=None,
                   updated_since: Optional[datetime] = None, latest_only=True, cursor=None, limit=100):
        allc = [(vs[-1] if latest_only else c) for vs in self._cases.values() for c in (vs if not latest_only else [vs[-1]])]
        allc = [c for c in sorted(allc, key=lambda c: (c["case_id"], c["version"]))
                if review_status in (None, c["review_status"]) and failure_type in (None, c["failure_type"])]
        start = int(cursor or 0)
        page = allc[start:start + limit]
        return copy.deepcopy(page), (str(start + limit) if start + limit < len(allc) else None)

    def get_trace(self, deidentified_trace_ref):
        t = self._traces.get(deidentified_trace_ref)
        if t is None:
            raise BoundaryError("NOT_FOUND", "trace가 없다")
        return copy.deepcopy(t)


def failure_case(case_id: str, trace_ref: str, expected: Optional[dict], *, status="CONFIRMED", deidentified=True) -> dict:
    c = {"pipeline_schema_version": "1.0", "case_id": case_id, "version": 1, "created_at": "2026-10-15T00:00:00Z",
         "source_release_id": "rel-0001", "runtime_contract_version": 1, "deidentified": deidentified,
         "deidentified_trace_ref": trace_ref, "failure_type": "UNCLASSIFIED", "detection_method": "HUMAN",
         "review_status": status}
    if expected is not None:
        c["expected"] = expected
    return c


def make_failure_store(bank: dict) -> FakeFailureStore:
    """확정 사례 1건(파서)과 확정 사례 1건(생성기), 건너뛰어야 할 PENDING 1건."""
    from synthetic_data import directives as dv, bank as bk
    q = bank["questions"][2]   # Q3 수면
    pin = {"utterance": "한 다섯 시간 정도 자요", "last_directive": None, "awaiting_questions": [q],
           "question_names": bk.question_names(bank), "answered_slots": [], "guide_list": []}
    pout = {"items": [{"item_no": 0, "target": bk.slot_ref(q, q["slots"][0]), "value": "다섯 시간", "source_text": "다섯 시간",
                       "intent": "ANSWERED_INTENT", "progress_op": None, "guide_id": None}]}
    m = dv.empty_materials()
    m["question_sentences"] = [{"question_id": q["question_id"], "sentence": q["question_sentence"]}]
    gin = {"directive": dv.directive("ASK_NEXT", bk.question_slot_refs(q), materials=m), "utterance": "네"}
    gout = {"response_text": "알겠습니다. " + q["question_sentence"], "is_fallback": False}
    fs = FakeFailureStore()
    fs.add(failure_case("fc-p", "tr-p", pout), make_trace("fc-p", parser_input=pin, parser_output=pout))
    fs.add(failure_case("fc-g", "tr-g", gout), make_trace("fc-g", generator_input=gin, generator_output=gout))
    fs.add(failure_case("fc-pending", "tr-x", None, status="PENDING"), make_trace("fc-pending"))
    return fs


def make_failure_store_factory(**_ignored) -> FakeFailureStore:
    return make_failure_store(make_bank("main"))
