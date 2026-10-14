"""시나리오 설계기가 만드는 '계획'과 생성기가 돌려주는 '초안'. 생성기가 규칙 기반이든 LLM이든 이 형식으로 주고받는다."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class FactPlan:
    """발화가 담아야 할 사실 하나(= ParserOutput 항목 하나의 의도된 모습)."""
    intent: str
    target: Optional[dict] = None
    intended: Any = None              # 의도된 표준 값(Value). 답함·정정에만 있다
    progress_op: Optional[str] = None
    guide_id: Optional[str] = None
    retracted: Any = None             # 발화 안에서 스스로 고친 앞 값(발화에만 나오고 라벨에는 없다)
    hints: dict = field(default_factory=dict)   # slot_kind, yes_no, unit_names, phrase 등 생성기 참고용


@dataclass
class ParserPlan:
    scenario_id: str
    kind: str
    question_set: dict
    base_input: dict                  # UtteranceParserInput에서 utterance만 빠진 것
    facts: list[FactPlan]
    hints: dict = field(default_factory=dict)


@dataclass
class FactSurface:
    source: str                       # 발화에서 이 사실을 담은 글자(발화의 부분 문자열)
    value: Optional[str]              # 값 글자(source의 부분 문자열). 값 없는 의도는 None


@dataclass
class UtteranceDraft:
    utterance: str
    facts: list[FactSurface]          # plan.facts와 같은 순서·개수


@dataclass
class GeneratorPlan:
    scenario_id: str
    kind: str
    question_set: dict
    directive: dict                   # Directive
    utterance: Optional[str]          # 사용자 발화(없으면 None)
    hints: dict = field(default_factory=dict)
