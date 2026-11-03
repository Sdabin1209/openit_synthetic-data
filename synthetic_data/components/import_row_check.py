"""학습 데이터 한 줄 검증. RawRow -> RowVerdict.

각 행의 형태는 실제 C1 파일 6개(64,459행)로 확인했다(2026-10-28, docs/design.md 부록 A):
  {"messages":[{"role":"system",..},{"role":"user","content":<입력 JSON 문자열>},{"role":"assistant","content":<A는 출력 JSON 문자열, B는 응답 문장>}], "scenario_id":..., "split":..., "human_review":...}
검증은 3단계다(docs/adr/0003): 줄 모양(TrainingDataRow 스키마) -> user/assistant 내용(계약 입출력 스키마) -> 조립한 샘플(계약 샘플 스키마).
사유는 '<단계>: <경로>#<스키마 키워드>' 코드뿐이고 입력 값(행 내용, 스키마 메시지)은 담지 않는다(SD-1)."""
from __future__ import annotations

import json

from boundary_contracts import PIPELINE_SCHEMA_VERSION

from ..types.schema_registry import check, codes, contract_codes

_IN_SCHEMA = {"LORA_A": "ActionExtractionInput", "LORA_B": "ResponseRequest"}
_OUT_SCHEMA = {"LORA_A": "ActionExtraction", "LORA_B": "ResponseText"}
_SAMPLE_SCHEMA = {"LORA_A": "ActionExtractionSample", "LORA_B": "ResponseSample"}
_ID_PREFIX = {"LORA_A": "as", "LORA_B": "rs"}
_SPLIT_FILE = {"TRAIN": "train", "VALIDATION": "validation", "EVAL": "eval"}
_WS = " \t\n\r\x0b\x0c"     # bytes.strip()와 같은 공백(유니코드 공백은 JSON 오류로 집계되던 동작 유지)


def _verdict(sample, reasons, row_split):
    out = {"sample": sample, "reasons": reasons, "row_split": row_split}
    check("RowVerdict", out)
    return out


def run(inp: dict) -> dict:
    check("RawRow", inp)
    role, split, lineno, text = inp["role"], inp["split"], inp["lineno"], inp["text"]
    if text is None:
        return _verdict(None, ["record_encoding: UTF-8이 아니다"], None)
    if not text.strip(_WS):
        return _verdict(None, ["record_blank: 빈 줄"], None)
    try:
        row = json.loads(text)
    except json.JSONDecodeError as e:
        return _verdict(None, [f"record_json: JSON이 아니다({e.msg})"], None)
    if not isinstance(row, dict):
        return _verdict(None, ["record_shape: 행이 객체가 아니다"], None)
    rs = row.get("split")
    row_split = None if rs is None else str(rs)
    shape = codes("TrainingDataRow", row)
    if "messages" not in row or any(c.startswith("messages") for c in shape):
        return _verdict(None, ["record_shape: messages가 [system,user,assistant] 각각 문자열 content를 가진 3개가 아니다"], row_split)
    msgs = row["messages"]
    reasons: list[str] = []
    try:
        user = json.loads(msgs[1]["content"])
    except json.JSONDecodeError:
        user = None
        reasons.append("record_user_json: user 내용이 JSON이 아니다")
    if role == "LORA_A":
        try:
            out = json.loads(msgs[2]["content"])
        except json.JSONDecodeError:
            out = None
            reasons.append("record_assistant_json: LoRA-A assistant 내용이 JSON이 아니다")
    else:
        out = msgs[2]["content"]
    if user is not None:
        reasons += [f"input_schema: {m}" for m in contract_codes(_IN_SCHEMA[role], user)[:3]]
    if out is not None:
        reasons += [f"output_schema: {m}" for m in contract_codes(_OUT_SCHEMA[role], out)[:3]]
    sid = row.get("scenario_id")
    if "scenario_id" not in row or any(c.startswith("scenario_id") for c in shape):     # split·human_review 위반은 여기서 거부하지 않는다(split은 읽지 않고, human_review는 샘플 스키마 단계가 거부한다)
        reasons.append("row_scenario_id: scenario_id가 문자열이 아니다")
    if reasons:
        return _verdict(None, reasons, row_split)
    rec = {"pipeline_schema_version": PIPELINE_SCHEMA_VERSION, "sample_id": f"{_ID_PREFIX[role]}-{_SPLIT_FILE[split]}-{lineno:06d}",
           "scenario_id": sid, "split": split, "origin": "SYNTHETIC", "input": user, "expected": out}
    if "human_review" in row:
        rec["human_review"] = row["human_review"]
    errs = contract_codes(_SAMPLE_SCHEMA[role], rec)
    if errs:
        return _verdict(None, [f"sample_schema: {e}" for e in errs[:3]], row_split)
    return _verdict(rec, [], row_split)
