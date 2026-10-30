"""게시기 보고서 조립. ImportReportInput -> ReportDocument(계약 SyntheticImportReport).

왜 계약으로 자기 검사하나: deploy와 사람이 읽는 형식이라 내보내기 전에 검사한다(D107). 값은 담지 않고 건수와 사유 코드만."""
from __future__ import annotations

from ..types.schema_registry import check, check_contract

FORMAT_ASSUMPTION = "행 형식은 C1 빌드 실제 파일로 확인(docs/design.md 부록 A). 다른 빌드는 이 보고서의 invalid 건수로 확인"


def run(inp: dict) -> dict:
    check("ImportReportInput", inp)
    r: dict = {"job_version": inp["tool_version"], "mode": "import", "dataset_id": inp["dataset_id"], "notes": [],
               "format_assumption": FORMAT_ASSUMPTION, "tolerance": inp["tolerance"]}
    s = inp["summary"]
    if s is not None:
        r["inputs"] = s["inputs"]
        r["total_rows"], r["valid_rows"], r["invalid_rows"] = s["total_rows"], s["valid_rows"], s["invalid_rows"]
        r["invalid_reasons_by_file"] = s["invalid_reasons_by_file"]
        r["invalid_reasons_total"] = s["invalid_reasons_total"]
        r["first_invalid_line"] = s["first_invalid_line"]
        r["row_split_field"] = s["row_split_field"]
        r["human_review_counts"] = s["human_review_counts"]
        r["pending_policy"] = inp["pending_policy"]
        r["origin_assumed"] = "SYNTHETIC"      # 모든 행에 고정. 입력에 origin 정보가 없다(가정)
        r["deid_attested"] = False             # 비식별 확인은 이 게시기가 하지 않는다. 아래 pii는 의심 패턴 경고일 뿐이다
        r["deid_note"] = "비식별 확인 주체는 데이터셋 담당이다. 게시기는 확인하지 않았고 패턴 경고만 센다"
        r["semantic_checks"] = {"performed": False, "reason": "v2 의미 검사(targets, next_item, 건너뛰기 순서, save)는 패키지에 없다(CR-006). 스키마 검증만 했다"}
        r["pii_suspect"] = {"rows_by_file": s["pii_rows_by_file"], "rows_by_kind": s["pii_rows_by_kind"], "rows_total": s["pii_rows_total"],
                            "patterns": sorted(inp["pii_patterns"])}
        r["pending_rows"] = sum(s["pending_by_file"].values())
        r["pending_excluded"] = inp["pending_excluded"]
        if inp["overlap"] is not None:
            r["cross_split_duplicate_utterances"] = inp["overlap"]["duplicate_utterances"]     # 참고(발화+맥락): 허용치 판정에 쓰지 않는다
            r["cross_split_duplicate_inputs"] = inp["overlap"]["duplicate_inputs"]            # 허용치 판정: 같은 입력
    if inp["error"] is not None:
        r["error"] = inp["error"]
    elif inp["rejected"]:
        r["result"] = {"status": "REJECTED", "reasons": inp["rejected"]}
    elif inp["published"] is not None:
        p = inp["published"]
        r["dataset_digest"] = p["dataset_digest"]
        r["result"] = {"status": p["status"], "version": p["version"], "content_hash": p["content_hash"]}
    check_contract("SyntheticImportReport", r)
    return {"report": r}
