"""샘플 품질 검사. QualityInput -> QualityVerdict.

2.0.0(D74): 샘플은 LoRA-A(ActionExtractionSample)와 LoRA-B(ResponseSample)다. 지금 검사하는 것은 경계 계약 스키마 통과뿐이다
(input·expected는 ActionExtraction*·ResponseRequest·ResponseText로 샘플 스키마가 함께 검증한다).
v1의 의미 검사는 v1 필드에 묶여 있어 뺐다. v2 의미 검사(targets, next_item, 건너뛰기 순서, save 규칙)는 계약의 규칙 검사기
(boundary_contracts.action_rules.check_action_extraction, D104)가 맡을 자리이며 연결은 아직 안 했다. 어떻게 이을지는 미정이다."""
from __future__ import annotations

from ..types.schema_registry import check, contract_codes

_SCHEMA = {"LORA_A": "ActionExtractionSample", "LORA_B": "ResponseSample"}


def run(inp: dict) -> dict:
    check("QualityInput", inp)
    out = {"reasons": ["schema_sample"] if contract_codes(_SCHEMA[inp["role"]], inp["sample"]) else []}
    check("QualityVerdict", out)
    return out
