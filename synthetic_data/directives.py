"""ResponseGeneratorInput.directive(Directive)와 UtteranceParserInput.last_directive를 손으로 짓는 도우미.

주의: 실제 Directive는 turn-engine의 plan()이 만든다(I8). turn-engine이 이 환경에 없어서 이 영역은 규칙 문서
(dialogue_planner.md)의 형태에 맞춰 직접 짓는다. 그래서 샘플 ext에 directive_source="hand-built"를 남긴다
(docs/change-requests/CR-002 참고)."""
from __future__ import annotations

from typing import Optional


def empty_materials() -> dict:
    return {"question_sentences": [], "refusal_explanations": [], "reask_sentences": [], "choices": [],
            "guide_sentences": [], "fixed_sentences": []}


def directive(action: str, targets: list, *, awaiting: Optional[dict] = None, say_values: Optional[list] = None,
              reask_reasons: Optional[list] = None, notices: Optional[list] = None,
              materials: Optional[dict] = None, target_pending_id: Optional[str] = None) -> dict:
    return {"action": action, "targets": targets, "target_pending_id": target_pending_id, "awaiting": awaiting,
            "say_values": say_values or [], "reask_reasons": reask_reasons or [], "notices": notices or [],
            "sentence_materials": materials or empty_materials()}


def ask_directive(action: str, targets: list, *, say_values: Optional[list] = None,
                  target_pending_id: Optional[str] = None) -> dict:
    return {"action": action, "targets": targets, "target_pending_id": target_pending_id,
            "say_values": say_values or []}


def notice(kind: str, *, guide_id: Optional[str] = None, question_id: Optional[str] = None,
           question_name: Optional[str] = None) -> dict:
    return {"kind": kind, "guide_id": guide_id, "question_id": question_id, "question_name": question_name,
            "slot": None, "previous_value": None, "value": None}


def say_value(slot: dict, question_name: str, value, role: str) -> dict:
    return {"slot": slot, "question_name": question_name, "value": value, "role": role}
