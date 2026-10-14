"""발화·문장 생성기의 교체 가능한 인터페이스.

규칙 기반(rule)과, 나중에 LLM을 쓰는 생성기가 같은 Protocol을 따른다. 생성기는 '계획'만 받고 라벨(정답)은 만들지 않는다.
정답은 정답 구성기(labeler)가 초안의 글자 위치로 만든다. 그래서 생성기가 바뀌어도 라벨 기준(docs/rules/utterance_parser.md)이 흔들리지 않는다.
생성기는 무엇을 만들 수 없으면 None을 돌려주고, 파이프라인이 그 건수를 보고서에 남긴다. 난수는 인자로 받은 rng만 쓴다."""
from __future__ import annotations

import random
from typing import Optional, Protocol, runtime_checkable

from ..plans import GeneratorPlan, ParserPlan, UtteranceDraft


@runtime_checkable
class UtteranceGenerator(Protocol):
    name: str
    version: str

    def generate(self, plan: ParserPlan, rng: random.Random) -> Optional[UtteranceDraft]: ...


@runtime_checkable
class ResponseGenerator(Protocol):
    name: str
    version: str

    def generate(self, plan: GeneratorPlan, rng: random.Random) -> Optional[str]: ...
