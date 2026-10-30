"""보내는 쪽 통신: 확정된 실패 사례 읽기(I7, ops-feedback). FailureReadRequest -> ConfirmedCases.
계약 클라이언트(openit_link.clients, D118)로 CONFIRMED의 최신 버전만 쪽 단위로 모두 읽는다. 클라이언트 공장(http_failure_store)은 설정의 factory가 가리킨다."""
from __future__ import annotations

from boundary_contracts import SecretError, read_secret
from openit_link.clients import HttpFailureStore

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


def http_failure_store(base_url: str, token_env: str, timeout: float = 10.0) -> HttpFailureStore:
    return HttpFailureStore(base_url, _token(token_env), timeout)


def fetch(inp: dict, *, store) -> dict:
    check("FailureReadRequest", inp)
    cases, cursor = [], None
    while True:
        items, cursor = store.list_cases(review_status="CONFIRMED", latest_only=True, cursor=cursor, limit=inp["page_size"])
        cases += items
        if cursor is None:
            break
    out = {"cases": cases}
    check("ConfirmedCases", out)
    return out
