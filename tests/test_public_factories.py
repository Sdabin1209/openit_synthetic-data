"""공개 진입점(ADR 0022): 잡 설정 adapters.*.factory가 가리키는 이름이 import되고 호출 시그니처가 맞는지 지킨다."""
from __future__ import annotations

import importlib
import inspect

import pytest

# 배포 설정(deploy e2e)과 계약 SyntheticJobConfigRun이 가리키는 공개 factory. 이름을 지우거나 옮기려면 ADR 0022를 대체하는 새 ADR이 먼저다.
PUBLIC_FACTORIES = {
    "synthetic_data.adapters:http_question_reader": "HttpQuestionReader",
    "synthetic_data.adapters:http_failure_store": "HttpFailureStore",
}


def load(spec: str):
    mod, _, fn = spec.partition(":")
    return getattr(importlib.import_module(mod), fn)


@pytest.mark.parametrize("spec", sorted(PUBLIC_FACTORIES))
def test_public_factory_imports_and_signature(spec):
    f = load(spec)
    sig = inspect.signature(f)
    assert list(sig.parameters) == ["base_url", "token_env", "timeout"]
    assert sig.parameters["timeout"].default == 10.0
    assert sig.parameters["base_url"].default is inspect.Parameter.empty and sig.parameters["token_env"].default is inspect.Parameter.empty


@pytest.mark.parametrize("spec", sorted(PUBLIC_FACTORIES))
def test_public_factory_builds_client_with_secret_file(spec, tmp_path, monkeypatch):
    tok = tmp_path / "tok"
    tok.write_text("t" * 40)
    monkeypatch.setenv("SD_TEST_TOKEN_FILE", str(tok))
    client = load(spec)(base_url="http://127.0.0.1:1", token_env="SD_TEST_TOKEN")      # kwargs 이름은 배포 설정이 쓰는 것
    assert type(client).__name__ == PUBLIC_FACTORIES[spec]


def test_public_factory_missing_secret_is_a_clear_error(monkeypatch):
    from synthetic_data.components.link_question_reader import TokenError
    monkeypatch.delenv("SD_TEST_TOKEN", raising=False)
    monkeypatch.delenv("SD_TEST_TOKEN_FILE", raising=False)
    with pytest.raises(TokenError):
        load("synthetic_data.adapters:http_question_reader")("http://127.0.0.1:1", "SD_TEST_TOKEN")
