"""읽어 온 문항 세트를 이번 실행에 쓸지 판정한다. QuestionSetAdmitInput -> QuestionSetAdmission.

판정 규칙: (1) 버전을 지정하고 reviewed_only면 승인(APPROVED이고 clinical_basis_approved)이 있어야 한다, (2) QuestionBank의 해시가 ArtifactRef와 같아야 한다,
(3) QuestionBank가 문진 스키마를 통과해야 한다, (4) regeneration.mode가 affected_only면 변경 분류에 REGENERATE_SAMPLES가 있어야 하고, 그때 영향 문항(affected_slots의 문항 ID)만 다시 만든다(context.affected_question_ids; 목록이 비었으면 제한 없음).
문진 스키마 검사는 wiring이 주입한다(survey_check): 이 컴포넌트는 문진 스키마 파일 위치를 모른다. 위반은 예외가 아니라 REJECTED 출력이다."""
from __future__ import annotations

from boundary_contracts import canonical

from ..types.schema_registry import check


def _reject(code: str, message: str) -> dict:
    return {"status": "REJECTED", "context": None, "note": None, "error": {"code": code, "message": message}}


def _decide(inp: dict, survey_check) -> dict:
    f, spec = inp["fetch"], inp["spec"]
    ref, bank = f["ref"], f["bank"]
    if f["approvals"] is not None and not any(r["decision"] == "APPROVED" and r["clinical_basis_approved"] for r in f["approvals"]):
        return _reject("FAILED_PRECONDITION", f"검수 승인이 없는 문항 세트 버전이다: {spec['id']}@{spec['version']}")
    if canonical.sha256_hash(bank) != ref["content_hash"]:
        return _reject("INTEGRITY_ERROR", f"QuestionBank 해시가 ArtifactRef와 다르다: {ref['id']}@{ref['version']}")
    errs = survey_check("QuestionBank", bank)
    if errs:
        return _reject("INVALID_RECORD", f"QuestionBank {ref['id']}@{ref['version']}이(가) 문진 스키마 QuestionBank을 위반한다: {errs[0]}")
    if inp["regeneration_mode"] == "affected_only" and (f["follow_ups"] is None or "REGENERATE_SAMPLES" not in f["follow_ups"]):
        return {"status": "SKIPPED", "context": None, "error": None, "note": f"{ref['id']}@{ref['version']}: REGENERATE_SAMPLES 후속 작업이 없어 제외"}
    return {"status": "ADMITTED", "context": {"ref": ref, "bank": bank, "usage": spec["usage"],
                                              "affected_question_ids": f["affected_question_ids"] if inp["regeneration_mode"] == "affected_only" else None},
            "note": None, "error": None}


def run(inp: dict, *, survey_check) -> dict:
    check("QuestionSetAdmitInput", inp)
    out = _decide(inp, survey_check)
    out.setdefault("note", None)
    check("QuestionSetAdmission", out)
    return out
