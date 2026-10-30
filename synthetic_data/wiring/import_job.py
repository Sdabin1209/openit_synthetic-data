"""게시기(import) 잡 연결: 설정 -> 입력 읽기 -> 줄 검증 -> 집계 -> 허용치 판정 -> (pending 제외) -> 겹침 판정 -> 패키징 -> 게시 -> 보고서.
데이터셋 담당이 학습 서버에서 만든 최종 학습 데이터를 '그대로 가져와' 검증하고 게시한다(재생성 없음, docs/adr/0001). 같은 입력과 설정이면 같은 version이 나오고
이미 게시돼 있으면 ALREADY_PUBLISHED다(멱등). 이 모듈은 컴포넌트 출력을 다음 컴포넌트 입력으로 옮길 뿐 판정하지 않는다."""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional

from boundary_contracts import PIPELINE_SCHEMA_VERSION
from boundary_contracts.errors import BoundaryError

from .. import __version__
from ..components import (import_judge, import_overlap, import_package, import_report, import_row_check, import_source, import_tally,
                          pending_filter, pii_scan)
from ..components.import_source import INPUT_FILES, InputError as _SourceError
from ..config import ConfigError
from .plans import Plan, load_import_config
from .publishing import publish as publish_dataset
from .stores import build_store
from .survey import Survey


class InputError(ConfigError):
    """입력 디렉터리나 파일 문제(종료 코드 2)."""


@dataclass
class ImportResult:
    status: str                      # PUBLISHED | ALREADY_PUBLISHED | REJECTED
    dataset_id: str
    version: Optional[str] = None
    content_hash: Optional[str] = None
    dataset_digest: Optional[str] = None
    counts: dict = field(default_factory=dict)
    rejected_reasons: list = field(default_factory=list)
    report_path: Optional[str] = None


def _write(cfg: Plan, doc: dict) -> str:
    p = cfg.work_dir / "import_report.json"
    p.write_text(json.dumps(doc["report"], ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    return str(p)


def run_import(cfg: Plan, *, store, survey: Optional[Survey] = None, clock: Optional[Callable[[], str]] = None) -> ImportResult:
    cfg.work_dir.mkdir(parents=True, exist_ok=True)
    state = {"dataset_id": cfg.dataset_id, "tolerance": {k: cfg.tolerance[k] for k in ("max_invalid_rows", "max_invalid_rate")},
             "pending_policy": cfg.pending_policy, "tool_version": __version__, "summary": None, "pii_patterns": [], "pending_excluded": 0,
             "overlap": None, "rejected": [], "published": None, "error": None}
    try:
        return _run(cfg, store, survey, clock, state)
    except BoundaryError as e:
        state["error"] = e.to_record()
        _write(cfg, import_report.run(state))
        raise


def _run(cfg: Plan, store, survey, clock, state: dict) -> ImportResult:
    survey = survey or Survey(cfg.survey_schema_dir)
    contract = survey.contract_version
    try:
        source = import_source.run({"input_dir": str(cfg.input_dir)})
    except _SourceError as e:
        raise InputError(str(e)) from e

    tally_files = []
    for f in source["files"]:
        verdicts = [import_row_check.run({"role": f["role"], "split": f["split"], "lineno": r["lineno"], "text": r["text"]}) for r in f["rows"]]
        scanned = pii_scan.run({"items": [{"input": v["sample"]["input"], "expected": v["sample"]["expected"]} for v in verdicts if v["sample"] is not None]})
        state["pii_patterns"] = scanned["patterns"]
        kinds = iter(scanned["kinds"])
        tally_files.append({"name": f["name"], "role": f["role"], "split": f["split"], "sha256": f["sha256"],
                            "rows": [{"verdict": v, "pii_kinds": next(kinds) if v["sample"] is not None else []} for v in verdicts]})
    tally = import_tally.run({"files": tally_files})
    summary, valid = tally["summary"], tally["valid_samples"]
    state["summary"] = summary

    judged = import_judge.run({"tolerance": cfg.tolerance, "pending_policy": cfg.pending_policy, "total_rows": summary["total_rows"],
                               "invalid_rows": summary["invalid_rows"], "valid_by_file": {n: i["valid"] for n, i in summary["inputs"].items()},
                               "pending_total": sum(summary["pending_by_file"].values()), "pii_rows_total": summary["pii_rows_total"]})
    rejected = list(judged["reasons"])
    if not rejected and judged["exclude_pending"]:
        pf = pending_filter.run({"files": valid})
        valid, rejected = pf["files"], list(pf["reasons"])
        state["pending_excluded"] = pf["excluded"]
    if not rejected:
        ov = import_overlap.run({"items": [{"role": role, "split": split, "scenario_id": r["scenario_id"], "input": r["input"]}
                                           for name, role, split in INPUT_FILES for r in valid[name]],
                                 "max_cross_split_duplicates": cfg.max_cross_split_duplicates})
        state["overlap"] = {"duplicate_utterances": ov["duplicate_utterances"], "duplicate_inputs": ov["duplicate_inputs"]}
        rejected = list(ov["reasons"])
    counts = {"rows_total": summary["total_rows"], "rows_valid": summary["valid_rows"], "rows_invalid": summary["invalid_rows"]}
    for name, _, _ in INPUT_FILES:
        counts[f"{name}.valid"] = summary["inputs"][name]["valid"]
    if rejected:
        state["rejected"] = rejected
        res = ImportResult("REJECTED", cfg.dataset_id, counts=counts, rejected_reasons=rejected)
        res.report_path = _write(cfg, import_report.run(state))
        return res

    created_at = cfg.created_at or (clock() if clock else datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"))
    packaged = import_package.run({
        "dataset_id": cfg.dataset_id, "version": cfg.version, "created_at": created_at, "contract_version": contract,
        "question_sets": cfg.question_sets, "source_label": cfg.source_label, "action_rules_version": cfg.action_rules_version,
        "pending_policy": cfg.pending_policy, "pending_excluded": state["pending_excluded"], "tolerance": state["tolerance"], "tool_version": __version__,
        "pipeline_schema_version": PIPELINE_SCHEMA_VERSION,
        "files": [{"name": n, "role": role, "split": split, "sha256": summary["inputs"][n]["sha256"], "samples": valid[n]} for n, role, split in INPUT_FILES],
        "summary": summary, "overlap": state["overlap"]})
    version = packaged["manifest"]["version"]
    out = publish_dataset(packaged, store, cfg.work_dir, "dsimport-")
    state["published"] = {"status": out["status"], "version": version, "content_hash": out["content_hash"], "dataset_digest": packaged["digest"]}
    res = ImportResult(out["status"], cfg.dataset_id, version, out["content_hash"], packaged["digest"], counts)
    res.report_path = _write(cfg, import_report.run(state))
    return res


def import_from_config(config_path: Path, *, created_at: Optional[str] = None) -> ImportResult:
    cfg = load_import_config(config_path)
    if created_at:
        cfg.created_at = created_at
    survey = Survey(cfg.survey_schema_dir)
    return run_import(cfg, store=build_store(cfg.store, survey), survey=survey)
