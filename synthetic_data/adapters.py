"""설정의 adapters.*.factory가 가리키는 HTTP 어댑터 공장(진입점). 토큰은 비밀 이름(token_env)으로 받아 read_secret으로 여기서만 읽는다(NAME_FILE 경로 우선, 없으면 NAME 환경 변수).

설정 예: {"factory": "synthetic_data.adapters:http_question_reader",
          "kwargs": {"base_url": "http://question-authoring:8080", "token_env": "QUESTION_READER_TOKEN", "timeout": 10}}
읽기 클라이언트는 읽기 모드다: 모르는 필드·열거값은 받아들이고, MAJOR 불일치는 UNSUPPORTED_VERSION, 형식·해시 위반은
INTEGRITY_ERROR로 올라온다(잡이 report.json의 error에 남기고 종료 코드 3 또는 75로 끝난다)."""
from __future__ import annotations

from boundary_contracts import SecretError, read_secret
from boundary_contracts.clients import HttpFailureStore, HttpQuestionReader

from .config import ConfigError


def _token(token_env: str) -> str:
    try:
        tok = read_secret(token_env)
    except SecretError as e:
        raise ConfigError(str(e)) from None  # 메시지에 값은 없다(이름·경로만)
    if not tok:
        raise ConfigError(f"토큰 {token_env}이(가) 없다: {token_env}_FILE(파일 경로) 또는 {token_env}(개발용)를 설정한다")
    return tok


def http_question_reader(base_url: str, token_env: str, timeout: float = 10.0) -> HttpQuestionReader:
    return HttpQuestionReader(base_url, _token(token_env), timeout)


def http_failure_store(base_url: str, token_env: str, timeout: float = 10.0) -> HttpFailureStore:
    return HttpFailureStore(base_url, _token(token_env), timeout)
