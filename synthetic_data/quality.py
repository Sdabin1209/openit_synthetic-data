"""품질 검사기. 샘플마다 사유 코드 목록을 돌려준다(빈 목록이면 통과).

2.0.0(D74): 샘플은 LoRA-A(ActionExtractionSample)와 LoRA-B(ResponseSample)다. 지금 검사하는 것은 경계 계약 스키마 통과뿐이다
(input·expected는 ActionExtraction*·ResponseRequest·ResponseText로 샘플 스키마가 함께 검증한다).
v1의 의미 검사(의도·대상·원문 위치·응답 지시 밖의 값 등)는 v1 필드(items, directive)에 묶여 있어 뺐다. v2 의미 검사(targets, next_item,
건너뛰기 순서, save 규칙)는 계약의 규칙 검사기(boundary_contracts.action_rules.check_action_extraction, D104)가 맡을 자리이며 연결은 아직 안 했다. 어떻게 이을지는 미정이다."""
from __future__ import annotations

from typing import Optional

from .schemas import Validators


def _schema_reasons(rec: dict, role: str, v: Validators) -> list[str]:
    name = "ActionExtractionSample" if role == "LORA_A" else "ResponseSample"
    return ["schema_sample"] if v.check_boundary(name, rec) else []


def check_lora_a_sample(rec: dict, bank: Optional[dict], v: Validators) -> list[str]:
    return _schema_reasons(rec, "LORA_A", v)


def check_lora_b_sample(rec: dict, bank: Optional[dict], v: Validators) -> list[str]:
    return _schema_reasons(rec, "LORA_B", v)
