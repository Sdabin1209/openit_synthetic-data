"""생성 잡: 설정 하나로 문항 읽기 -> 시나리오 설계 -> 생성 -> 노이즈 -> 정답 -> 품질 검사 -> 분할 -> 패키징 -> 게시를 끝까지 돈다.
같은 입력(문항 세트 내용, 시드 사례, 설정)과 시드는 같은 dataset_digest를 낸다. created_at을 고정하면 매니페스트 content_hash도 같다."""
from __future__ import annotations

import importlib
import json
import tempfile
from collections import Counter
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional

from boundary_contracts import canonical
from boundary_contracts.errors import BoundaryError
from boundary_contracts.sdk import DatasetStore, FailureStore, QuestionReader

from . import __version__
from .config import JobConfig, load_config
from .generators import load_response_generator, load_utterance_generator
from .package import dumps_line, package
from .pipeline import build_generator_samples, build_parser_samples, build_seed_samples
from .quality import check_generator_sample, check_parser_sample
from .rng import derive_int
from .scenario import QuestionSetContext, design_generator_plans, design_parser_plans
from .schemas import Validators
from .seeds import collect_seeds
from .split import assign_split
from .store import FileDatasetStore, MemoryDatasetStore

NOISE_VERSION = "0.1.0"


@dataclass
class JobResult:
    status: str                      # PUBLISHED | ALREADY_PUBLISHED | NOTHING_TO_DO
    dataset_id: str
    version: Optional[str] = None
    content_hash: Optional[str] = None
    dataset_digest: Optional[str] = None
    counts: dict = field(default_factory=dict)
    report_path: Optional[str] = None


def load_factory(spec) -> Callable:
    mod, _, fn = spec.factory.partition(":")
    return getattr(importlib.import_module(mod), fn)


def resolve_turn_engine_version(cfg: JobConfig) -> str:
    """turn-engine이 설치돼 있으면 ENGINE_VERSION, 아니면 설정 값. 둘 다 없으면 오류(매니페스트 필수 필드)."""
    try:
        import turn_engine  # type: ignore
        return str(turn_engine.ENGINE_VERSION)
    except ImportError:
        pass
    if cfg.turn_engine_version:
        return cfg.turn_engine_version
    raise BoundaryError("FAILED_PRECONDITION", "turn-engine 버전을 알 수 없다: turn_engine이 없고 설정 turn_engine_version도 없다")


def _find_ref(reader: QuestionReader, qid: str, version: str) -> dict:
    cursor = None
    while True:
        items, cursor = reader.list_versions(qid, cursor=cursor, limit=100)
        for r in items:
            if r["version"] == version:
                return r
        if cursor is None:
            raise BoundaryError("NOT_FOUND", f"문항 세트 버전이 없다: {qid}@{version}")


def _affected_questions(change: dict) -> Optional[set]:
    """affected_slots(SlotRef 문자열 '<question_id>.<slot_id>', CONVENTIONS 10절)에서 문항 ID를 뽑는다.
    마지막 '.'에서 나눈다(문항 ID에는 '.'이 있을 수 있다). 비어 있으면 None(전체)."""
    if not change["affected_slots"]:
        return None
    return {s.rsplit(".", 1)[0] for s in change["affected_slots"]}


def run_job(cfg: JobConfig, *, question_reader: QuestionReader, store: DatasetStore,
            failure_store: Optional[FailureStore] = None, validators: Optional[Validators] = None,
            clock: Optional[Callable[[], str]] = None) -> JobResult:
    v = validators or Validators(cfg.survey_schema_dir)
    contract = v.runtime_contract_version
    te_version = resolve_turn_engine_version(cfg)
    cfg.work_dir.mkdir(parents=True, exist_ok=True)
    report: dict = {"job_version": __version__, "dataset_id": cfg.dataset_id, "notes": [], "dropped": {}, "skipped_seeds": []}

    # 1. 문항 읽기 (I1)
    ctxs, qfilter = [], {}
    for spec in cfg.question_sets:
        ref = _find_ref(question_reader, spec.id, spec.version) if spec.version else \
            question_reader.latest(spec.id, reviewed_only=cfg.reviewed_only)
        if spec.version and cfg.reviewed_only:
            if not any(r["decision"] == "APPROVED" and r["clinical_basis_approved"] for r in question_reader.get_reviews(ref)):
                raise BoundaryError("FAILED_PRECONDITION", f"검수 승인이 없는 문항 세트 버전이다: {spec.id}@{spec.version}")
        bank = question_reader.get_question_bank(ref)
        if canonical.sha256_hash(bank) != ref["content_hash"]:
            raise BoundaryError("INTEGRITY_ERROR", f"QuestionBank 해시가 ArtifactRef와 다르다: {ref['id']}@{ref['version']}")
        v.survey("QuestionBank", bank, what=f"QuestionBank {ref['id']}@{ref['version']}")
        if cfg.regeneration_mode == "affected_only":
            ch = question_reader.get_change(ref)
            if ch is None or "REGENERATE_SAMPLES" not in ch["follow_ups"]:
                report["notes"].append(f"{ref['id']}@{ref['version']}: REGENERATE_SAMPLES 후속 작업이 없어 제외")
                continue
            qfilter[ref["id"], ref["version"]] = _affected_questions(ch)
        ctxs.append(QuestionSetContext(ref, bank, spec.usage))
    if not ctxs:
        return JobResult("NOTHING_TO_DO", cfg.dataset_id, report_path=_write_report(cfg, report))

    # 2~4. 시나리오 설계 -> 생성 -> 노이즈 -> 정답
    ugen, rgen = load_utterance_generator(cfg.utterance_generator), load_response_generator(cfg.response_generator)
    samples: list[dict] = []
    gen_stats = Counter()
    banks = {}
    for c in ctxs:
        banks[(c.ref["id"], c.ref["version"])] = c.bank
        qf = qfilter.get((c.ref["id"], c.ref["version"]))
        pp, s1 = design_parser_plans(c, variants=cfg.variants, seed=cfg.seed, kinds=cfg.kinds, question_filter=qf)
        gp, s2 = design_generator_plans(c, variants=cfg.variants, seed=cfg.seed, question_filter=qf)
        ps, s3 = build_parser_samples(pp, ugen, cfg, contract)
        gs, s4 = build_generator_samples(gp, rgen, cfg, contract)
        samples += ps + gs
        gen_stats.update({"plans_parser": len(pp), "plans_generator": len(gp), "not_applicable": s1["not_applicable"] + s2["not_applicable"]})
        gen_stats.update(s3)
        gen_stats.update(s4)

    # 시드 (I7)
    if cfg.seeds_enabled:
        if failure_store is None:
            raise BoundaryError("FAILED_PRECONDITION", "seeds.enabled인데 failure_store가 없다")
        seeds, skipped = collect_seeds(failure_store, v)
        report["skipped_seeds"] += skipped
        pool = {(c.ref["id"], c.ref["version"], c.ref["content_hash"]): c for c in ctxs if c.usage == "TRAIN_POOL"}
        fallback = sorted((c for c in pool.values() if c.ref["id"] == cfg.seeds_question_set_id),
                          key=lambda c: c.ref["version"])
        pairs = []
        for sd in seeds:
            if sd.question_set is not None:                       # 1.1 레코드: 수집 영역이 채운 값
                ref = sd.question_set
                c = pool.get((ref["id"], ref["version"], ref["content_hash"]))
                why = "시드의 문항 세트가 이번 실행의 학습 풀에 없음"
            else:                                                 # 1.0 레코드 폴백: 설정의 문항 세트
                c = fallback[-1] if fallback else None
                why = "시드에 문항 세트 참조가 없고 seeds.question_set_id도 없음"
            if c is None:
                report["skipped_seeds"].append({"case_id": sd.case_id, "reason": why})
            else:
                pairs.append((sd, c))
        ss, skipped2, s5 = build_seed_samples(pairs, cfg, contract)
        samples += ss
        report["skipped_seeds"] += skipped2
        gen_stats.update(s5)

    # 5. 품질 검사 + 중복 제거
    kept, dropped = [], Counter()
    for s in sorted(samples, key=lambda r: r["sample_id"]):
        bank = banks[(s["question_set"]["id"], s["question_set"]["version"])]
        role = "PARSER" if s["sample_id"].startswith("ps-") else "GENERATOR"
        reasons = (check_parser_sample if role == "PARSER" else check_generator_sample)(s, bank, v)
        if reasons:
            dropped.update(reasons)
            continue
        kept.append(s)
    by_input: dict[str, list] = {}
    for s in kept:
        by_input.setdefault(canonical.sha256_hash([s["sample_id"][:2], s["input"]]), []).append(s)
    final = []
    for key in sorted(by_input):
        group = by_input[key]
        seed_first = sorted(group, key=lambda r: (r["origin"] != "FAILURE_CASE_SEED", r["sample_id"]))
        if seed_first[0]["origin"] == "FAILURE_CASE_SEED":     # 사람이 확정한 정답이 이긴다
            keep = seed_first[0]
            dropped["synthetic_dropped_for_seed_input"] += sum(1 for g in group if g["origin"] != "FAILURE_CASE_SEED")
            dropped["duplicate_input"] += sum(1 for g in group if g["origin"] == "FAILURE_CASE_SEED") - 1
            final.append(keep)
        elif len({canonical.sha256_hash(g["expected"]) for g in group}) > 1:
            dropped["input_label_conflict"] += len(group)      # 같은 입력에 다른 정답: 라벨 잡음이라 전부 뺀다
        else:
            final.append(seed_first[0])
            dropped["duplicate_input"] += len(group) - 1
    report["dropped"] = dict(sorted(dropped.items()))
    report["generation"] = dict(sorted(gen_stats.items()))
    usage = {c.ref["id"]: c.usage for c in ctxs}

    # 6. 분할 (시나리오 단위)
    for s in final:
        s["split"] = assign_split(s["scenario_id"], usage[s["question_set"]["id"]], cfg.ratios, cfg.seed)
    if not final:
        report["notes"].append("남은 샘플이 없다")
        return JobResult("NOTHING_TO_DO", cfg.dataset_id, report_path=_write_report(cfg, report))

    # 7. 감수 샘플링
    _write_review_sample(cfg, final)

    # 8. 패키징과 게시
    gv = f"{ugen.name}@{ugen.version}+{rgen.name}@{rgen.version}+noise@{NOISE_VERSION}+job@{__version__}"
    created_at = cfg.created_at or (clock() if clock else datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"))
    with tempfile.TemporaryDirectory(prefix="dsbuild-", dir=cfg.work_dir) as td:
        manifest, files, digest = package(final, ctxs, cfg, staging=Path(td) / "files", contract=contract,
                                          generator_version=gv, turn_engine_version=te_version, created_at=created_at)
        report["counts"] = _counts(final)
        report["dataset_digest"] = digest
        res = JobResult("PUBLISHED", cfg.dataset_id, manifest["version"], None, digest, report["counts"])
        if cfg.version is None:
            try:
                ex = store.get_manifest(cfg.dataset_id, manifest["version"])
                if ex.get("ext", {}).get("synthetic-data", {}).get("dataset_digest") == digest:
                    res.status, res.content_hash = "ALREADY_PUBLISHED", ex["content_hash"]
            except BoundaryError as e:
                if e.code != "NOT_FOUND":
                    raise
        if res.status == "PUBLISHED":
            res.content_hash = store.publish(manifest, files)["content_hash"]
    report["result"] = {"status": res.status, "version": res.version, "content_hash": res.content_hash}
    res.report_path = _write_report(cfg, report)
    return res


def _counts(final: list) -> dict:
    c = Counter()
    for s in final:
        role = "parser" if s["sample_id"].startswith("ps-") else "generator"
        c[f"{role}.{s['split']}"] += 1
        c[f"origin.{s['origin']}"] += 1
        c[f"kind.{s['ext']['synthetic-data']['kind']}"] += 1
    return dict(sorted(c.items()))


def _write_report(cfg: JobConfig, report: dict) -> str:
    p = cfg.work_dir / "report.json"
    p.write_text(json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    return str(p)


def _write_review_sample(cfg: JobConfig, final: list) -> None:
    """감수 샘플링: (역할, 종류)마다 해시 순으로 per_kind개. 사람 감수용 목록이고 게시 대상이 아니다."""
    groups: dict[tuple, list] = {}
    for s in final:
        groups.setdefault((s["sample_id"][:2], s["ext"]["synthetic-data"]["kind"]), []).append(s)
    out = []
    for key in sorted(groups):
        pick = sorted(groups[key], key=lambda r: derive_int(cfg.seed, "review", r["sample_id"]))[:cfg.review_per_kind]
        out += sorted(pick, key=lambda r: r["sample_id"])
    with open(cfg.work_dir / "review_sample.jsonl", "w", encoding="utf-8", newline="\n") as fh:
        for s in out:
            fh.write(dumps_line({"sample_id": s["sample_id"], "kind": s["ext"]["synthetic-data"]["kind"], "split": s["split"],
                                 "input": s["input"].get("utterance", s["input"].get("directive", {}).get("action")),
                                 "expected": s["expected"]}))


def build_from_config(config_path: Path, *, created_at: Optional[str] = None) -> JobResult:
    """CLI 진입점이 쓴다. 어댑터(문항 읽기, 실패 사례 읽기)를 설정의 factory로 만든다. 환경 변수는 여기서만 읽을 수 있다(현재 없음)."""
    cfg = load_config(config_path)
    if created_at:
        cfg.created_at = created_at
    v = Validators(cfg.survey_schema_dir)
    reader = load_factory(cfg.question_reader)(**cfg.question_reader.kwargs)
    fstore = load_factory(cfg.failure_store)(**cfg.failure_store.kwargs) if cfg.failure_store else None
    store = FileDatasetStore(cfg.store_root, v) if cfg.store_kind == "file" else MemoryDatasetStore(v)
    return run_job(cfg, question_reader=reader, failure_store=fstore, store=store, validators=v)
