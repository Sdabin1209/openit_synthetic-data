"""생성기 모음. 설정의 generators.utterance / generators.response에 'rule' 또는 'module:attr'(인자 없는 호출 가능 객체)를 쓴다."""
from __future__ import annotations

import importlib

from .base import ResponseGenerator, UtteranceGenerator
from .rule import RuleResponseGenerator, RuleUtteranceGenerator


def _load(spec: str):
    mod, _, attr = spec.partition(":")
    return getattr(importlib.import_module(mod), attr)()


def load_utterance_generator(spec: str = "rule") -> UtteranceGenerator:
    return RuleUtteranceGenerator() if spec == "rule" else _load(spec)


def load_response_generator(spec: str = "rule") -> ResponseGenerator:
    return RuleResponseGenerator() if spec == "rule" else _load(spec)


__all__ = ["UtteranceGenerator", "ResponseGenerator", "RuleUtteranceGenerator", "RuleResponseGenerator",
           "load_utterance_generator", "load_response_generator"]
