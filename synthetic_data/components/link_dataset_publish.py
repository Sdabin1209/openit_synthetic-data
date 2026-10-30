"""보내는 쪽 통신: 데이터셋 게시(I2, dataset-store 서버). 저장소 표면(publish, get_manifest)을 HTTP 클라이언트로 낸다.
계약 클라이언트(openit_link.clients, D118)를 감싼다. 쓰기 토큰은 값이 아니라 비밀 이름(token_env)으로 받고 read_secret(D84)이 읽는다:
`<NAME>_FILE`이 가리키는 파일의 내용이 우선이고, 없으면 환경 변수 `<NAME>`(개발·시험용)."""
from __future__ import annotations

from boundary_contracts import SecretError, read_secret
from openit_link.clients import HttpDatasetStore

from ..types.schema_registry import check


class TokenError(ValueError):
    """쓰기 토큰이 없다(메시지에는 값이 없고 이름·경로만 있다)."""


def build(spec: dict) -> HttpDatasetStore:
    check("HttpStoreSpec", spec)
    try:
        tok = read_secret(spec["token_env"])
    except SecretError as e:
        raise TokenError(str(e)) from None
    if not tok:
        raise TokenError(f"쓰기 토큰 {spec['token_env']}이(가) 없다: {spec['token_env']}_FILE(파일 경로) 또는 {spec['token_env']}(개발용)를 설정한다")
    return HttpDatasetStore(spec["base_url"], tok, spec["timeout"])
