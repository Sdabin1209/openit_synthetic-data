"""한 실행이 읽은 문항 세트 하나(참조, 본문, 용도). 시드 샘플 조립과 패키저가 쓴다."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class QuestionSetContext:
    ref: dict           # ArtifactRef
    bank: dict          # QuestionBank
    usage: str          # TRAIN_POOL | HELD_OUT_EVAL
