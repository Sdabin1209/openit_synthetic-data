"""시드 잡(`run`) 설정. 설정 파일(JSON) 하나가 잡의 모든 입력이다. 상대 경로는 설정 파일이 있는 디렉터리 기준이다.

평가셋 구성·지표·임계치는 사용자 결정(O11)이라 코드에 기본값을 두지 않는다. split.ratios는 반드시 설정에 적어야 하고,
저장소의 예시 설정에 있는 값은 동작 확인용 자리 표시이지 결정이 아니다."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from .store.spec import parse_store

_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]*$")
USAGES = ("TRAIN_POOL", "HELD_OUT_EVAL")
SPLITS = ("TRAIN", "VALIDATION", "EVAL")


class ConfigError(ValueError):
    """설정 오류(경계 호출이 아니므로 BoundaryError가 아니다)."""


@dataclass
class AdapterSpec:
    factory: str                    # "module:function"
    kwargs: dict = field(default_factory=dict)


@dataclass
class QuestionSetSpec:
    id: str
    version: Optional[str]
    usage: str


@dataclass
class JobConfig:
    # v1 생성 설정 키(scenarios, generators, style_guide_version)는 받되 무시한다(ADR 0010). 배포 E2E의 기존 설정 파일이 아직 싣고 있다.
    dataset_id: str
    seed: int
    created_at: Optional[str]
    version: Optional[str]
    turn_engine_version: Optional[str]
    survey_schema_dir: Path
    question_reader: AdapterSpec
    failure_store: Optional[AdapterSpec]
    question_sets: list
    reviewed_only: bool
    seeds_enabled: bool
    seeds_question_set_id: Optional[str]
    ratios: dict
    review_per_kind: int
    regeneration_mode: str
    work_dir: Path
    store_kind: str
    store_root: Optional[Path]
    raw: dict = field(default_factory=dict)
    store_http: Optional[dict] = None     # kind=http일 때의 정규화된 설정(store/spec.py)


def _req(d: dict, key: str, where: str):
    if key not in d:
        raise ConfigError(f"설정에 {where}{key}이(가) 필요하다")
    return d[key]


def _adapter(d: dict, where: str) -> AdapterSpec:
    f = _req(d, "factory", where + ".")
    if ":" not in f:
        raise ConfigError(f"{where}.factory는 'module:function' 형식이어야 한다")
    return AdapterSpec(f, dict(d.get("kwargs", {})))


def parse_config(raw: dict, base_dir: Path) -> JobConfig:
    def path(s):
        p = Path(s)
        return p if p.is_absolute() else (base_dir / p).resolve()

    did = _req(raw, "dataset_id", "")
    if not _ID_RE.match(did) or len(did) > 128:
        raise ConfigError("dataset_id 형식이 맞지 않는다")
    seed = _req(raw, "seed", "")
    if not isinstance(seed, int) or isinstance(seed, bool):
        raise ConfigError("seed는 정수여야 한다")
    ratios = _req(_req(raw, "split", ""), "ratios", "split.")
    if set(ratios) != set(SPLITS) or any(not isinstance(x, (int, float)) or x < 0 for x in ratios.values()) or sum(ratios.values()) <= 0:
        raise ConfigError("split.ratios는 TRAIN·VALIDATION·EVAL 세 키에 0 이상의 수를 적어야 하고 합이 0보다 커야 한다 (평가셋 구성은 O11, 사용자 결정)")
    qsets = []
    for q in _req(raw, "question_sets", ""):
        usage = q.get("usage", "TRAIN_POOL")
        if usage not in USAGES:
            raise ConfigError(f"question_sets[].usage는 {USAGES} 중 하나여야 한다")
        qsets.append(QuestionSetSpec(_req(q, "id", "question_sets[]."), q.get("version"), usage))
    if not qsets:
        raise ConfigError("question_sets가 비어 있다")
    ids = {}
    for q in qsets:
        if ids.setdefault(q.id, q.usage) != q.usage:
            raise ConfigError(f"같은 문항 세트 {q.id}를 TRAIN_POOL과 HELD_OUT_EVAL에 함께 쓸 수 없다")
    ad = _req(raw, "adapters", "")
    sd = raw.get("seeds", {})
    out = _req(raw, "output", "")
    store = _req(out, "store", "output.")
    kind = _req(store, "kind", "output.store.")
    http = parse_store(store, ConfigError)
    reg = raw.get("regeneration", {}).get("mode", "full")
    if reg not in ("full", "affected_only"):
        raise ConfigError("regeneration.mode는 full 또는 affected_only")
    seeds_on = bool(sd.get("enabled", False))
    if seeds_on:
        if "failure_store" not in ad:
            raise ConfigError("seeds.enabled인데 adapters.failure_store가 없다")
        if sd.get("question_set_id") is not None and sd["question_set_id"] not in ids:
            raise ConfigError("seeds.question_set_id가 question_sets에 없다")
    return JobConfig(
        dataset_id=did, seed=seed, created_at=raw.get("created_at"), version=raw.get("version"),
        turn_engine_version=raw.get("turn_engine_version"),
        survey_schema_dir=path(_req(raw, "survey_schema_dir", "")),
        question_reader=_adapter(_req(ad, "question_reader", "adapters."), "adapters.question_reader"),
        failure_store=_adapter(ad["failure_store"], "adapters.failure_store") if "failure_store" in ad else None,
        question_sets=qsets, reviewed_only=bool(raw.get("reviewed_only", True)),
        seeds_enabled=seeds_on, seeds_question_set_id=sd.get("question_set_id"),
        ratios={k: float(v) for k, v in ratios.items()},
        review_per_kind=int(raw.get("review", {}).get("per_kind", 2)), regeneration_mode=reg,
        work_dir=path(_req(out, "work_dir", "output.")), store_kind=kind,
        store_root=path(store["root"]) if "root" in store else None, raw=raw, store_http=http)


def load_config(config_path: Path) -> JobConfig:
    p = Path(config_path).resolve()
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        raise ConfigError(f"설정 파일을 읽을 수 없다: {p}: {e}") from e
    return parse_config(raw, p.parent)
