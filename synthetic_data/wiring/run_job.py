"""시드 잡(run) 연결: 설정 -> 문항 읽기(I1) -> 시드 읽기(I7) -> 시드 수집 -> 개인정보 관문 -> 짝짓기 -> 조립 -> 품질 검사 -> 중복 정리 -> 분할 -> 감수 샘플링 -> 패키징 -> 게시 -> 보고서.
v1 생성 경로(시나리오 설계·발화/응답 생성·노이즈·정답 구성)는 ADR 0010으로 제거했다. 학습 데이터 본체는 import가 게시한다.
같은 입력(문항 세트 내용, 시드 사례, 설정)과 시드는 같은 dataset_digest를 낸다. created_at을 고정하면 매니페스트 content_hash도 같다.
이 모듈은 컴포넌트 출력을 다음 컴포넌트 입력으로 옮길 뿐 판정하지 않는다."""
from __future__ import annotations

import importlib
import json
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional

from boundary_contracts import PIPELINE_SCHEMA_VERSION
from boundary_contracts.errors import BoundaryError

from .. import __version__
from ..components import (link_failure_reader, link_question_reader, pii_scan, question_set_admit, review_sample, run_package, run_report,
                          sample_dedupe, sample_quality, seed_assemble, seed_collect, seed_pairing, seed_pii_gate, split_assign)
from .plans import Plan, load_config
from .publishing import publish as publish_dataset
from .stores import build_store
from .survey import Survey


@dataclass
class JobResult:
    status: str                      # PUBLISHED | ALREADY_PUBLISHED | NOTHING_TO_DO
    dataset_id: str
    version: Optional[str] = None
    content_hash: Optional[str] = None
    dataset_digest: Optional[str] = None
    counts: dict = field(default_factory=dict)
    report_path: Optional[str] = None


def load_factory(spec: dict) -> Callable:
    mod, _, fn = spec["factory"].partition(":")
    return getattr(importlib.import_module(mod), fn)


def _write_report(cfg: Plan, state: dict) -> tuple[str, dict]:
    doc = run_report.run(state)["report"]
    p = cfg.work_dir / "report.json"
    p.write_text(json.dumps(doc, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    return str(p), doc


def run_job(cfg: Plan, *, question_reader, store, failure_store=None, survey: Optional[Survey] = None,
            clock: Optional[Callable[[], str]] = None) -> JobResult:
    """경계 호출이 실패하면 report.json의 `error`(BoundaryError 레코드)를 남기고 같은 예외를 다시 던진다."""
    cfg.work_dir.mkdir(parents=True, exist_ok=True)
    state: dict = {"dataset_id": cfg.dataset_id, "tool_version": __version__, "notes": [], "dropped": {}, "skipped_seeds": []}
    try:
        return _run(cfg, question_reader, store, failure_store, survey, clock, state)
    except BoundaryError as e:
        state["error"] = e.to_record()
        _write_report(cfg, state)
        raise


def _read_question_sets(cfg: Plan, reader, survey: Survey, state: dict) -> list:
    ctxs = []
    for spec in cfg.question_sets:
        fetched = link_question_reader.fetch(
            {"id": spec["id"], "version": spec["version"], "reviewed_only": cfg.reviewed_only,
             "want_approvals": bool(spec["version"] and cfg.reviewed_only), "want_change": cfg.regeneration_mode == "affected_only"}, reader=reader)
        adm = question_set_admit.run({"fetch": fetched, "spec": spec, "reviewed_only": cfg.reviewed_only, "regeneration_mode": cfg.regeneration_mode},
                                     survey_check=survey.check)
        if adm["status"] == "REJECTED":
            raise BoundaryError(adm["error"]["code"], adm["error"]["message"])
        if adm["status"] == "SKIPPED":
            state["notes"].append(adm["note"])
        else:
            ctxs.append(adm["context"])
    return ctxs


def _seed_samples(cfg: Plan, ctxs: list, failure_store, survey: Survey, state: dict) -> tuple[list, Counter]:
    if failure_store is None:
        raise BoundaryError("FAILED_PRECONDITION", "seeds.enabled인데 failure_store가 없다")
    cases = link_failure_reader.fetch({"page_size": 100}, store=failure_store)["cases"]
    collected = seed_collect.run({"cases": cases, "survey_contract_version": survey.contract_version})
    state["notes"] += collected["notes"]
    state["skipped_seeds"] += collected["skipped"]
    seeds = collected["seeds"]
    scanned = pii_scan.run({"items": [{"input": s["input"], "expected": s["expected"]} for s in seeds]})
    hits = {s["case_id"]: k for s, k in zip(seeds, scanned["kinds"]) if k}
    gate = seed_pii_gate.run({"hits": hits, "patterns": scanned["patterns"], "max_suspect": cfg.seeds_max_pii_suspect})
    state["pii_suspect"] = {"rows_total": gate["suspect_rows"], "patterns": gate["patterns"]}
    if gate["rejected"]:
        raise BoundaryError("INVALID_RECORD", gate["message"])
    paired = seed_pairing.run({"seeds": seeds, "contexts": [{"ref": c["ref"], "usage": c["usage"]} for c in ctxs],
                               "fallback_question_set_id": cfg.seeds_question_set_id})
    state["skipped_seeds"] += paired["skipped"]
    qids = {(c["ref"]["id"], c["ref"]["version"], c["ref"]["content_hash"]): [q["question_id"] for q in c["bank"]["questions"]] for c in ctxs}
    affected = {(c["ref"]["id"], c["ref"]["version"], c["ref"]["content_hash"]): c["affected_question_ids"] for c in ctxs}
    assembled = seed_assemble.run({"pairs": [{"seed": p["seed"], "ref": p["ref"],
                                              "question_ids": qids[(p["ref"]["id"], p["ref"]["version"], p["ref"]["content_hash"])],
                                              "affected_question_ids": affected[(p["ref"]["id"], p["ref"]["version"], p["ref"]["content_hash"])]} for p in paired["pairs"]]})
    state["skipped_seeds"] += assembled["skipped"]
    return assembled["samples"], Counter(assembled["stats"])


def _run(cfg: Plan, question_reader, store, failure_store, survey, clock, state: dict) -> JobResult:
    survey = survey or Survey(cfg.survey_schema_dir)
    contract = survey.contract_version
    ctxs = _read_question_sets(cfg, question_reader, survey, state)
    if not ctxs:
        return JobResult("NOTHING_TO_DO", cfg.dataset_id, report_path=_write_report(cfg, state)[0])

    samples: list = []
    gen_stats: Counter = Counter()
    if cfg.seeds_enabled:
        samples, gen_stats = _seed_samples(cfg, ctxs, failure_store, survey, state)

    kept, dropped = [], Counter()
    for s in sorted(samples, key=lambda r: r["sample_id"]):
        reasons = sample_quality.run({"role": "LORA_A" if s["sample_id"].startswith("as-") else "LORA_B", "sample": s})["reasons"]
        if reasons:
            dropped.update(reasons)
        else:
            kept.append(s)
    deduped = sample_dedupe.run({"samples": kept})
    dropped.update(deduped["dropped"])
    state["dropped"] = dict(sorted(dropped.items()))
    state["generation"] = dict(sorted(gen_stats.items()))

    final = split_assign.run({"samples": deduped["samples"], "usage_by_question_set": {c["ref"]["id"]: c["usage"] for c in ctxs},
                              "ratios": cfg.ratios, "seed": cfg.seed})["samples"]
    if not final:
        state["notes"].append("남은 샘플이 없다(시드가 꺼져 있거나 쓸 수 있는 시드가 없다)")
        return JobResult("NOTHING_TO_DO", cfg.dataset_id, report_path=_write_report(cfg, state)[0])

    (cfg.work_dir / "review_sample.jsonl").write_text(
        review_sample.run({"samples": final, "seed": cfg.seed, "per_kind": cfg.review_per_kind})["text"], encoding="utf-8", newline="\n")

    created_at = cfg.created_at or (clock() if clock else datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"))
    packaged = run_package.run({
        "samples": final, "contexts": [{"ref": c["ref"], "usage": c["usage"]} for c in ctxs], "dataset_id": cfg.dataset_id, "version": cfg.version,
        "contract_version": contract, "generator_version": f"seed-only+job@{__version__}", "action_rules_version": cfg.action_rules_version,
        "created_at": created_at, "pipeline_schema_version": PIPELINE_SCHEMA_VERSION})
    state["samples"] = final
    state["dataset_digest"] = packaged["digest"]
    out = publish_dataset(packaged, store, cfg.work_dir, "dsbuild-")
    version = packaged["manifest"]["version"]
    state["result"] = {"status": out["status"], "version": version, "content_hash": out["content_hash"]}
    path, doc = _write_report(cfg, state)
    return JobResult(out["status"], cfg.dataset_id, version, out["content_hash"], packaged["digest"], doc["counts"], path)


def build_from_config(config_path: Path, *, created_at: Optional[str] = None) -> JobResult:
    """CLI 진입점이 쓴다. 어댑터(문항 읽기, 실패 사례 읽기)를 설정의 factory로 만든다."""
    from ..config import ConfigError
    cfg = load_config(config_path)
    if created_at:
        cfg.created_at = created_at
    survey = Survey(cfg.survey_schema_dir)
    try:
        reader = load_factory(cfg.question_reader)(**cfg.question_reader["kwargs"])
        fstore = load_factory(cfg.failure_store)(**cfg.failure_store["kwargs"]) if cfg.failure_store else None
    except (link_question_reader.TokenError, link_failure_reader.TokenError) as e:
        raise ConfigError(str(e)) from None
    return run_job(cfg, question_reader=reader, failure_store=fstore, store=build_store(cfg.store, survey), survey=survey)
