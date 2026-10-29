"""게시기(import) 모드: 데이터셋 담당이 학습 서버에서 만든 최종 학습 데이터를 '그대로 가져와' 검증하고 게시한다(재생성 없음).

입력 디렉터리에 lora_{a,b}_{train,val,test}.jsonl 6개가 있어야 한다. 각 행의 형태는 실제 C1 파일 6개(64,459행)로 확인했다(2026-10-28, docs/design.md 부록 A. 처음에는 boundary-contracts V2_DRAFT의 기록에서 추정했다):
  {"messages":[{"role":"system",..},{"role":"user","content":<입력 JSON 문자열>},{"role":"assistant","content":<A는 출력 JSON 문자열, B는 응답 문장>}],
   "scenario_id":..., "split":..., "human_review":...}
형식이 다르면 그 행은 사유(record_*)와 함께 집계되고, 허용치를 넘으면 게시하지 않는다.

흐름: 읽기 -> 행 단위 검증(boundary-contracts v2 스키마) -> 건수·사유 집계 -> 허용치 판정 -> (통과 시) 샘플 JSONL로 쓰고 DatasetManifest 게시.
같은 입력(파일 바이트)과 같은 설정이면 같은 dataset_digest와 같은 version이 나오고, 이미 게시돼 있으면 ALREADY_PUBLISHED다(멱등)."""
from __future__ import annotations

import json
import re
import tempfile
import unicodedata
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional

from boundary_contracts import canonical
from boundary_contracts.errors import BoundaryError

from . import PIPELINE_SCHEMA_VERSION, __version__
from .config import ConfigError, survey_dir
from .contract_check import check_config, check_output
from .package import EXT, dumps_line
from .pii import PII_PATTERNS, PII_SCAN_LIMIT, pii_kinds   # noqa: F401  (옛 import 경로 호환)
from .publishing import publish_idempotent
from .schemas import Validators
from .store import FileDatasetStore, MemoryDatasetStore
from .store.spec import build_http_store, parse_store
from .store.base import DatasetStoreBase

# 왜: 매니페스트가 파일 단위로 분할을 요구하고 행의 split 값(실측: train/val/test, 파일 이름과 일치)이 파일 이름과 같은 정보라 파일 이름으로 정한다(docs/adr/0002). 파일 이름은 V2_DRAFT 기록의 추정.
SPLIT_OF_FILE = {"train": "TRAIN", "val": "VALIDATION", "test": "EVAL"}
ROLES = (("a", "LORA_A"), ("b", "LORA_B"))
INPUT_FILES = [(f"lora_{r}_{s}.jsonl", role, split) for r, role in ROLES for s, split in SPLIT_OF_FILE.items()]
_IN_SCHEMA = {"LORA_A": "ActionExtractionInput", "LORA_B": "ResponseRequest"}
_OUT_SCHEMA = {"LORA_A": "ActionExtraction", "LORA_B": "ResponseText"}
_SAMPLE_SCHEMA = {"LORA_A": "ActionExtractionSample", "LORA_B": "ResponseSample"}
_ROLE_DIR = {"LORA_A": "lora_a", "LORA_B": "lora_b"}
_ID_PREFIX = {"LORA_A": "as", "LORA_B": "rs"}
_SPLIT_FILE = {"TRAIN": "train", "VALIDATION": "validation", "EVAL": "eval"}
IMPORT_GENERATOR_PREFIX = "external-import"
# 왜: pending을 걸러낼지는 사용자 결정이라 기본 report(보고만)다. 기본값은 정책이 아니다(docs/adr/0005).
PENDING_POLICIES = ("report", "exclude", "reject")
_PUNCT = {"P", "S", "Z", "C"}   # 유니코드 General Category(UAX #44): 구두점·기호·구분자·제어. 근거 docs/adr/0004


def normalize_utterance(text: str) -> str:
    # 왜 NFKC: 전각/반각 등 호환 문자를 같은 글자로 합치는 유니코드 표준(UAX #15). 실제 데이터의 효과는 측정 안 함(docs/adr/0004)
    """공백·구두점·기호를 지우고 NFKC·소문자로 맞춘 발화(중복 발화 검사용, SD-3)."""
    t = unicodedata.normalize("NFKC", text).lower()
    return "".join(c for c in t if unicodedata.category(c)[0] not in _PUNCT)


def input_key(role: str, inp: dict) -> Optional[str]:
    """엄격한 키: 정규화한 발화 + 입력의 나머지 전부(A는 문항·상태, B는 action·known·next 등). 같은 입력이면 같다.
    왜(실측 2026-10-28, docs/adr/0004): 실제 C1 데이터에서 발화+문항만 보면 LoRA-A 8건이 겹쳤지만 모두 state가 달라 입력도 정답도 달랐다."""
    u = normalize_utterance(str(inp.get("user_utterance", "")))
    if not u:
        return None
    return canonical.sha256_hash([role, u, {k: v for k, v in inp.items() if k != "user_utterance"}])


def utterance_key(role: str, inp: dict) -> Optional[str]:
    """같은 입력인지 보는 키: 정규화한 발화 + 맥락(A는 문항 ID, B는 action과 다음 문항). 발화가 비면 None."""
    u = normalize_utterance(str(inp.get("user_utterance", "")))
    if not u:
        return None
    ctx = [inp.get("question_id")] if role == "LORA_A" else [inp.get("action"), (inp.get("next") or {}).get("question_id")]
    return canonical.sha256_hash([role, u, ctx])


class InputError(ConfigError):
    """입력 디렉터리나 파일 문제(종료 코드 2)."""


@dataclass
class ImportConfig:
    dataset_id: str
    input_dir: Path
    survey_schema_dir: Path
    question_sets: list            # ArtifactRef 목록. 외부 데이터에는 문항 세트 출처가 없어 설정으로 받는다(CR-006)
    source_label: str              # 데이터 출처 표시(예: 데이터셋 담당이 정한 버전 이름). generator_version에 들어간다
    turn_engine_version: str
    max_invalid_rows: int
    max_invalid_rate: float
    version: Optional[str]
    created_at: Optional[str]
    work_dir: Path
    max_cross_split_duplicates: int
    max_pii_suspect_rows: Optional[int]
    pending_policy: str
    store_kind: str
    store_root: Optional[Path]
    store_http: Optional[dict] = None


def parse_import_config(raw: dict, base_dir: Path) -> ImportConfig:
    # 왜: 키·형식·허용치 범위·origin·pending_policy 값 검사는 계약 스키마가 정본이다(D107, ADR 0014). 스키마로 쓸 수 없는 불변식은 없다.
    check_config("SyntheticJobConfigImport", raw, ConfigError)
    def path(s):
        p = Path(s)
        return p if p.is_absolute() else (base_dir / p).resolve()

    tol, out = raw["tolerance"], raw["output"]
    store = out["store"]
    return ImportConfig(
        dataset_id=raw["dataset_id"], input_dir=path(raw["input_dir"]), survey_schema_dir=survey_dir(raw["survey_schema_dir"], base_dir),
        question_sets=raw["question_sets"], source_label=raw["source_label"].strip(), turn_engine_version=raw["turn_engine_version"],
        max_invalid_rows=tol["max_invalid_rows"], max_invalid_rate=float(tol["max_invalid_rate"]),
        version=raw.get("version"), created_at=raw.get("created_at"),
        work_dir=path(out["work_dir"]), max_cross_split_duplicates=tol.get("max_cross_split_duplicate_inputs", 0),
        # 왜: 기본은 거부(0건 허용)다. 경고만 하려면 null을 명시한다(ADR 0005 제목 '기본값은 가장 엄격하다', 표준성 점검 B14)
        max_pii_suspect_rows=tol["max_pii_suspect_rows"] if "max_pii_suspect_rows" in tol else 0,
        pending_policy=raw.get("pending_policy", "report"), store_kind=store["kind"],
        store_root=path(store["root"]) if "root" in store else None, store_http=parse_store(store))


def load_import_config(config_path: Path) -> ImportConfig:
    p = Path(config_path).resolve()
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        raise ConfigError(f"설정 파일을 읽을 수 없다: {p}: {e}") from e
    if not isinstance(raw, dict):
        raise ConfigError("설정 파일의 최상위는 객체여야 한다")
    return parse_import_config(raw, p.parent)


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


def validate_row(raw: bytes, role: str, split: str, lineno: int, v: Validators) -> tuple[Optional[dict], list[str]]:
    """한 행을 검증한다. (샘플 레코드 또는 None, 사유 목록). 사유는 '<단계>: <경로>#<스키마 키워드>' 코드뿐이고 입력 값(행 내용, 스키마 메시지)은 담지 않는다(SD-1)."""
    if not raw.strip():
        return None, ["record_blank: 빈 줄"]
    try:
        row = json.loads(raw.decode("utf-8"))
    except UnicodeDecodeError:
        return None, ["record_encoding: UTF-8이 아니다"]
    except json.JSONDecodeError as e:
        return None, [f"record_json: JSON이 아니다({e.msg})"]
    if not isinstance(row, dict):
        return None, ["record_shape: 행이 객체가 아니다"]
    msgs = row.get("messages")
    if (not isinstance(msgs, list) or len(msgs) != 3 or not all(isinstance(m, dict) for m in msgs)
            or [m.get("role") for m in msgs] != ["system", "user", "assistant"]
            or not all(isinstance(m.get("content"), str) for m in msgs)):
        return None, ["record_shape: messages가 [system,user,assistant] 각각 문자열 content를 가진 3개가 아니다"]
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
        reasons += [f"input_schema: {m}" for m in v.check_boundary_codes(_IN_SCHEMA[role], user)[:3]]
    if out is not None:
        reasons += [f"output_schema: {m}" for m in v.check_boundary_codes(_OUT_SCHEMA[role], out)[:3]]
    sid = row.get("scenario_id")
    if not isinstance(sid, str):
        reasons.append("row_scenario_id: scenario_id가 문자열이 아니다")
    if reasons:
        return None, reasons
    rec = {"pipeline_schema_version": PIPELINE_SCHEMA_VERSION, "sample_id": f"{_ID_PREFIX[role]}-{_SPLIT_FILE[split]}-{lineno:06d}",
           "scenario_id": sid, "split": split, "origin": "SYNTHETIC", "input": user, "expected": out}
    if "human_review" in row:
        rec["human_review"] = row["human_review"]
    errs = v.check_boundary_codes(_SAMPLE_SCHEMA[role], rec)
    if errs:
        return None, [f"sample_schema: {e}" for e in errs[:3]]
    return rec, []


def _read_input(cfg: ImportConfig) -> dict:
    d = cfg.input_dir
    if not d.is_dir():
        raise InputError(f"입력 디렉터리가 없다: {d}")
    blobs, missing = {}, []
    for name, _, _ in INPUT_FILES:
        p = d / name
        if not p.is_file():
            missing.append(name)
            continue
        try:
            blobs[name] = p.read_bytes()
        except OSError as e:
            raise InputError(f"입력 파일을 읽을 수 없다: {p}: {e}") from e
    if missing:
        raise InputError(f"입력 파일이 없다: {', '.join(missing)} (필요: {', '.join(n for n, _, _ in INPUT_FILES)})")
    return blobs


def run_import(cfg: ImportConfig, *, store: DatasetStoreBase, validators: Optional[Validators] = None,
               clock: Optional[Callable[[], str]] = None) -> ImportResult:
    cfg.work_dir.mkdir(parents=True, exist_ok=True)
    report: dict = {"job_version": __version__, "mode": "import", "dataset_id": cfg.dataset_id, "notes": [],
                    "format_assumption": "행 형식은 C1 빌드 실제 파일로 확인(docs/design.md 부록 A). 다른 빌드는 이 보고서의 invalid 건수로 확인",
                    "tolerance": {"max_invalid_rows": cfg.max_invalid_rows, "max_invalid_rate": cfg.max_invalid_rate}}
    try:
        return _run_import(cfg, store, validators, clock, report)
    except BoundaryError as e:
        report["error"] = e.to_record()
        _write(cfg, report)
        raise


def _run_import(cfg, store, validators, clock, report) -> ImportResult:
    v = validators or Validators(cfg.survey_schema_dir)
    contract = v.runtime_contract_version
    blobs = _read_input(cfg)
    hashes = {n: canonical.file_hash(cfg.input_dir / n) for n in blobs}

    inputs, reasons_by_file, first_at = {}, {}, {}
    valid: dict[str, list] = {}
    total = bad = 0
    row_splits: dict = {}
    hr, pending_n, pii_rows, pii_kind_rows = Counter(), Counter(), Counter(), Counter()
    for name, role, split in INPUT_FILES:
        data = blobs[name]
        lines = data.split(b"\n")
        if lines and lines[-1] == b"":
            lines.pop()
        recs, reasons = [], Counter()
        for i, raw in enumerate(lines, 1):
            rec, why = validate_row(raw.rstrip(b"\r"), role, split, i, v)
            if rec is None:
                for w in why:
                    reasons[w] += 1
                    first_at.setdefault((name, w), i)
            else:
                recs.append(rec)
        sp = [x["split"] for x in _peek_splits(lines)]
        row_splits[name] = {"absent": sum(1 for x in sp if x is None), "distinct_values": len({str(x) for x in sp if x is not None})}
        for r in recs:
            hr[r.get("human_review", "(없음)")] += 1
            if r.get("human_review") == "pending":
                pending_n[name] += 1
            ks = pii_kinds(r)
            if ks:
                pii_rows[name] += 1
            pii_kind_rows.update(ks)
        inputs[name] = {"sha256": hashes[name],
                        "rows": len(lines), "valid": len(recs), "invalid": len(lines) - len(recs)}
        reasons_by_file[name] = dict(sorted(reasons.items()))
        valid[name] = recs
        total += len(lines)
        bad += len(lines) - len(recs)
    report["inputs"] = inputs
    report["total_rows"], report["valid_rows"], report["invalid_rows"] = total, total - bad, bad
    report["invalid_reasons_by_file"] = reasons_by_file
    # 같은 사유가 여러 파일에 있으면 합산한다(위 딕셔너리 합성은 마지막 값만 남으므로 다시 센다)
    agg = Counter()
    for rs in reasons_by_file.values():
        agg.update(rs)
    report["invalid_reasons_total"] = dict(sorted(agg.items()))
    report["first_invalid_line"] = {f"{k[0]} | {k[1]}": ln for k, ln in sorted(first_at.items())}
    report["row_split_field"] = row_splits      # 행의 split 필드는 값을 적지 않고 개수만 센다(값 형식 미확인)
    report["human_review_counts"] = dict(sorted(hr.items()))
    report["pending_policy"] = cfg.pending_policy
    report["origin_assumed"] = "SYNTHETIC"      # 모든 행에 고정. 입력에 origin 정보가 없다(가정)
    report["deid_attested"] = False             # 비식별 확인은 이 게시기가 하지 않는다. 아래 pii는 의심 패턴 경고일 뿐이다
    report["deid_note"] = "비식별 확인 주체는 데이터셋 담당이다. 게시기는 확인하지 않았고 패턴 경고만 센다"
    report["semantic_checks"] = {"performed": False, "reason": "v2 의미 검사(targets, next_item, 건너뛰기 순서, save)는 패키지에 없다(CR-006). 스키마 검증만 했다"}
    report["pii_suspect"] = {"rows_by_file": dict(sorted(pii_rows.items())), "rows_by_kind": dict(sorted(pii_kind_rows.items())),
                             "rows_total": sum(pii_rows.values()), "patterns": sorted(PII_PATTERNS)}

    rejected = []
    if total == 0:
        rejected.append("입력이 비어 있다(총 0행)")
    rate = (bad / total) if total else 1.0
    if bad > cfg.max_invalid_rows:
        rejected.append(f"검증 실패 행 {bad}건이 허용 건수 {cfg.max_invalid_rows}를 넘는다")
    if rate > cfg.max_invalid_rate:
        rejected.append(f"검증 실패율 {bad}/{total}={rate:.6f}이 허용 비율 {cfg.max_invalid_rate}를 넘는다")
    for name, recs in valid.items():
        if not recs:
            rejected.append(f"{name}: 통과한 행이 0건이다")
    npend = sum(pending_n.values())
    excluded_pending = 0
    if npend and cfg.pending_policy == "reject":
        rejected.append(f"human_review가 pending인 행이 {npend}건 있다(pending_policy=reject)")
    if cfg.max_pii_suspect_rows is not None and sum(pii_rows.values()) > cfg.max_pii_suspect_rows:
        rejected.append(f"개인정보 의심 패턴 행 {sum(pii_rows.values())}건이 허용 {cfg.max_pii_suspect_rows}를 넘는다")
    if npend and cfg.pending_policy == "exclude" and not rejected:
        for name in valid:
            valid[name] = [r for r in valid[name] if r.get("human_review") != "pending"]
        excluded_pending = npend
        for name, recs in valid.items():
            if not recs:
                rejected.append(f"{name}: pending 제외 뒤 행이 0건이다")
    report["pending_rows"] = npend
    report["pending_excluded"] = excluded_pending
    if not rejected:
        keys: dict[str, dict] = {"TRAIN": {}, "VALIDATION": {}, "EVAL": {}}
        skeys: dict[str, dict] = {"TRAIN": {}, "VALIDATION": {}, "EVAL": {}}
        for name, role, split in INPUT_FILES:
            for r in valid[name]:
                k = utterance_key(role, r["input"])
                if k:
                    keys[split].setdefault(k, 0)
                    keys[split][k] += 1
                k2 = input_key(role, r["input"])
                if k2:
                    skeys[split].setdefault(k2, 0)
        dup = {}
        for a, b in (("EVAL", "TRAIN"), ("EVAL", "VALIDATION"), ("TRAIN", "VALIDATION")):
            dup[f"{a}~{b}"] = len(set(keys[a]) & set(keys[b]))
        report["cross_split_duplicate_utterances"] = dup        # 참고(발화+맥락): 허용치 판정에 쓰지 않는다
        sdup = {f"{a}~{b}": len(set(skeys[a]) & set(skeys[b])) for a, b in (("EVAL", "TRAIN"), ("EVAL", "VALIDATION"), ("TRAIN", "VALIDATION"))}
        report["cross_split_duplicate_inputs"] = sdup           # 허용치 판정: 같은 입력
        dup = sdup
        worst = max(dup.values())
        if worst > cfg.max_cross_split_duplicates:
            rejected.append(f"분할 사이 같은 입력(정규화한 발화+입력 나머지 해시)이 허용 {cfg.max_cross_split_duplicates}건을 넘는다: {dup}")
    if not rejected:
        sc: dict[str, set] = {"TRAIN": set(), "VALIDATION": set(), "EVAL": set()}
        for name, role, split in INPUT_FILES:
            sc[split].update(r["scenario_id"] for r in valid[name])
        for a, b in (("EVAL", "TRAIN"), ("EVAL", "VALIDATION"), ("TRAIN", "VALIDATION")):
            both = sc[a] & sc[b]
            if both:
                rejected.append(f"같은 scenario_id가 {a}와 {b}에 걸친다({len(both)}건)")
    counts = {"rows_total": total, "rows_valid": total - bad, "rows_invalid": bad}
    for name, _, _ in INPUT_FILES:
        counts[f"{name}.valid"] = inputs[name]["valid"]
    if rejected:
        report["result"] = {"status": "REJECTED", "reasons": rejected}
        res = ImportResult("REJECTED", cfg.dataset_id, counts=counts, rejected_reasons=rejected)
        res.report_path = _write(cfg, report)
        return res

    created_at = cfg.created_at or (clock() if clock else datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"))
    with tempfile.TemporaryDirectory(prefix="dsimport-", dir=cfg.work_dir) as td:
        staging = Path(td) / "files"
        entries, files = [], {}
        for name, role, split in INPUT_FILES:
            rel = f"{_ROLE_DIR[role]}/{_SPLIT_FILE[split]}.jsonl"
            p = staging / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            with open(p, "w", encoding="utf-8", newline="\n") as fh:
                for r in valid[name]:
                    fh.write(dumps_line(r))
            entries.append({"path": rel, "role": role, "split": split, "sample_count": len(valid[name]),
                            "content_hash": canonical.file_hash(p)})
            files[rel] = p
        entries.sort(key=lambda e: e["path"])
        qsets = sorted(cfg.question_sets, key=lambda r: (r["id"], r["version"], r["content_hash"]))
        gv = f"{IMPORT_GENERATOR_PREFIX}:{cfg.source_label}@importer-{__version__}"
        digest = canonical.sha256_hash({
            "inputs": {k: inputs[k]["sha256"] for k in sorted(inputs)},
            "files": [[e["path"], e["content_hash"]] for e in entries], "question_sets": qsets,
            "runtime_contract_version": contract, "generator_version": gv, "turn_engine_version": cfg.turn_engine_version,
            "pending_policy": cfg.pending_policy})
        # 왜 digest 앞 32자리(128비트): 48비트(12자리)는 근거가 없어 바꿨다(docs/adr/0006 보강, 2026-10-29)
        manifest = {
            "pipeline_schema_version": PIPELINE_SCHEMA_VERSION, "dataset_id": cfg.dataset_id,
            "version": cfg.version or ("v" + digest[7:39]), "created_at": created_at, "runtime_contract_version": contract,
            "question_sets": qsets, "generator_version": gv, "seed_case_ids": [], "turn_engine_version": cfg.turn_engine_version,
            "scenario_disjoint_across_splits": True, "files": entries,
            "ext": {EXT: {"dataset_digest": digest, "import": {
                "inputs": inputs, "rows_total": total, "rows_valid": total - bad, "rows_invalid": bad,
                "invalid_reasons": report["invalid_reasons_total"],
                "human_review_counts": report["human_review_counts"], "pending_policy": cfg.pending_policy,
                "pending_excluded": excluded_pending, "origin_assumed": "SYNTHETIC",
                "deid_attested": False, "semantic_checks_performed": False,
                "pii_suspect_rows": report["pii_suspect"]["rows_total"],
                "cross_split_duplicate_utterances": report["cross_split_duplicate_utterances"],
                "cross_split_duplicate_inputs": report["cross_split_duplicate_inputs"],
                "tolerance": report["tolerance"]}}}}
        manifest["content_hash"] = canonical.content_hash(manifest)
        res = ImportResult("PUBLISHED", cfg.dataset_id, manifest["version"], None, digest, counts)
        res.status, res.content_hash = publish_idempotent(store, manifest, files, digest)   # run과 같은 판정(A10)
    report["dataset_digest"] = digest
    report["result"] = {"status": res.status, "version": res.version, "content_hash": res.content_hash}
    res.report_path = _write(cfg, report)
    return res


def _peek_splits(lines):
    for raw in lines:
        try:
            r = json.loads(raw)
            yield {"split": r.get("split")} if isinstance(r, dict) else {"split": None}
        except (ValueError, UnicodeDecodeError):
            yield {"split": None}


def _write(cfg: ImportConfig, report: dict) -> str:
    check_output("SyntheticImportReport", report)    # 왜: 계약 형식을 내보내기 전에 자기 검사한다(D107)
    p = cfg.work_dir / "import_report.json"
    p.write_text(json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    return str(p)


def import_from_config(config_path: Path, *, created_at: Optional[str] = None) -> ImportResult:
    cfg = load_import_config(config_path)
    if created_at:
        cfg.created_at = created_at
    v = Validators(cfg.survey_schema_dir)
    store = (build_http_store(cfg.store_http, ConfigError) if cfg.store_kind == "http" else
             FileDatasetStore(cfg.store_root, v) if cfg.store_kind == "file" else MemoryDatasetStore(v))
    return run_import(cfg, store=store, validators=v)
