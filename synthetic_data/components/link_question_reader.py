"""보내는 쪽 통신: 문항 읽기(I1, question-authoring). QuestionSetQuery -> QuestionSetFetch.

계약 클라이언트(openit_link.clients, D118)로 문항 세트 하나를 읽어 영역 내부 타입으로 바꾼다. 업무 컴포넌트는 계약 타입이나 HTTP를 모른다(DESIGN.md 4절).
클라이언트를 만드는 공장(http_question_reader)은 설정의 adapters.question_reader.factory가 가리킨다(계약 SyntheticJobConfigRun이 정한 설정 값)."""
from __future__ import annotations

from boundary_contracts import SecretError, read_secret
from openit_link.clients import HttpQuestionReader

from ..types.schema_registry import check


class TokenError(ValueError):
    """토큰이 없다(메시지에는 값이 없고 이름·경로만 있다)."""


def _token(token_env: str) -> str:
    try:
        tok = read_secret(token_env)
    except SecretError as e:
        raise TokenError(str(e)) from None
    if not tok:
        raise TokenError(f"토큰 {token_env}이(가) 없다: {token_env}_FILE(파일 경로) 또는 {token_env}(개발용)를 설정한다")
    return tok


def http_question_reader(base_url: str, token_env: str, timeout: float = 10.0) -> HttpQuestionReader:
    # 읽기 클라이언트는 읽기 모드다: 모르는 필드·열거값은 받아들이고, MAJOR 불일치는 UNSUPPORTED_VERSION, 형식·해시 위반은 INTEGRITY_ERROR로 올라온다.
    return HttpQuestionReader(base_url, _token(token_env), timeout)


def _find_ref(reader, qid: str, version: str) -> dict:
    from boundary_contracts.errors import BoundaryError
    cursor = None
    while True:
        items, cursor = reader.list_versions(qid, cursor=cursor, limit=100)
        for r in items:
            if r["version"] == version:
                return r
        if cursor is None:
            raise BoundaryError("NOT_FOUND", f"문항 세트 버전이 없다: {qid}@{version}")


def fetch(inp: dict, *, reader) -> dict:
    check("QuestionSetQuery", inp)
    ref = _find_ref(reader, inp["id"], inp["version"]) if inp["version"] else reader.latest(inp["id"], reviewed_only=inp["reviewed_only"])
    approvals = ([{"decision": r["decision"], "clinical_basis_approved": r["clinical_basis_approved"]} for r in reader.get_reviews(ref)]
                 if inp["want_approvals"] else None)
    bank = reader.get_question_bank(ref)
    follow_ups = None
    if inp["want_change"]:
        ch = reader.get_change(ref)
        follow_ups = None if ch is None else list(ch["follow_ups"])
    out = {"ref": ref, "bank": bank, "approvals": approvals, "change_checked": bool(inp["want_change"]), "follow_ups": follow_ups}
    check("QuestionSetFetch", out)
    return out
