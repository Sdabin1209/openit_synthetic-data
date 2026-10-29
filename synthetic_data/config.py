"""시드 잡(`run`) 설정. 설정 파일(JSON) 하나가 잡의 모든 입력이다. 상대 경로는 설정 파일이 있는 디렉터리 기준이다.

평가셋 구성·지표·임계치는 사용자 결정(O11)이라 코드에 기본값을 두지 않는다. split.ratios는 반드시 설정에 적어야 하고,
저장소의 예시 설정에 있는 값은 동작 확인용 자리 표시이지 결정이 아니다."""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from .contract_check import check_config
from .store.spec import parse_store



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
    seeds_max_pii_suspect: Optional[int]   # None = 경고만, 기본 0 = 하나라도 있으면 거부
    ratios: dict
    review_per_kind: int
    regeneration_mode: str
    work_dir: Path
    store_kind: str
    store_root: Optional[Path]
    raw: dict = field(default_factory=dict)
    store_http: Optional[dict] = None     # kind=http일 때의 정규화된 설정(store/spec.py)


def _adapter(d: dict) -> AdapterSpec:
    return AdapterSpec(d["factory"], dict(d.get("kwargs", {})))


SURVEY_DIR_ENV = "SYNTHETIC_SURVEY_SCHEMA_DIR"


def survey_dir(configured: str, base_dir: Path) -> Path:
    """문진 스키마 디렉터리. 환경 변수가 있으면 설정 값보다 우선한다.
    왜: 이미지 안의 스키마 위치는 이미지의 내부 사항이다. 잡 선언(io.openit.jobs)으로 이미지를 돌리는 쪽(deploy)이 그 경로를 몰라도 되게,
    이미지가 ENV로 위치를 정해 두고 설정의 survey_schema_dir(계약 스키마가 필수로 요구)보다 이것을 쓴다. 설정 쪽을 생략 가능하게 하는 것은 CR-009."""
    import os
    v = os.environ.get(SURVEY_DIR_ENV)
    p = Path(v or configured)
    return p if p.is_absolute() else (base_dir / p).resolve()


def parse_config(raw: dict, base_dir: Path) -> JobConfig:
    # 왜: 키·형식 검사는 계약 스키마가 정본이다(D107). 모르는 키 거부(최상위·중첩), v1 생성 키 거부, 토큰 값 거부가 모두 여기서 걸린다.
    #     아래는 스키마로 쓸 수 없는 불변식만 검사한다(R7: 스키마가 보증한 것은 다시 검사하지 않는다).
    check_config("SyntheticJobConfigRun", raw, ConfigError)
    def path(s):
        p = Path(s)
        return p if p.is_absolute() else (base_dir / p).resolve()

    ratios = raw["split"]["ratios"]
    if sum(ratios.values()) <= 0:
        raise ConfigError("split.ratios의 합이 0보다 커야 한다 (평가셋 구성은 O11, 사용자 결정)")
    qsets = [QuestionSetSpec(q["id"], q.get("version"), q.get("usage", "TRAIN_POOL")) for q in raw["question_sets"]]
    ids = {}
    for q in qsets:
        if ids.setdefault(q.id, q.usage) != q.usage:
            raise ConfigError(f"같은 문항 세트 {q.id}를 TRAIN_POOL과 HELD_OUT_EVAL에 함께 쓸 수 없다")
    ad = raw["adapters"]
    sd = raw.get("seeds", {})
    out = raw["output"]
    store = out["store"]
    http = parse_store(store)
    seeds_on = bool(sd.get("enabled", False))
    # 왜: import의 tolerance.max_pii_suspect_rows와 같은 기본(거부)이다. 시드는 이웃이 비식별했다고 한 값이지만 의심 패턴 검사는 별개다(표준성 점검 C4)
    mpii = sd["max_pii_suspect_rows"] if "max_pii_suspect_rows" in sd else 0
    if seeds_on:
        if "failure_store" not in ad:
            raise ConfigError("seeds.enabled인데 adapters.failure_store가 없다")
        if sd.get("question_set_id") is not None and sd["question_set_id"] not in ids:
            raise ConfigError("seeds.question_set_id가 question_sets에 없다")
    return JobConfig(
        dataset_id=raw["dataset_id"], seed=raw["seed"], created_at=raw.get("created_at"), version=raw.get("version"),
        turn_engine_version=raw.get("turn_engine_version"),
        survey_schema_dir=survey_dir(raw["survey_schema_dir"], base_dir),
        question_reader=_adapter(ad["question_reader"]),
        failure_store=_adapter(ad["failure_store"]) if "failure_store" in ad else None,
        question_sets=qsets, reviewed_only=bool(raw.get("reviewed_only", True)),
        seeds_enabled=seeds_on, seeds_question_set_id=sd.get("question_set_id"), seeds_max_pii_suspect=mpii,
        ratios={k: float(v) for k, v in ratios.items()},
        review_per_kind=int(raw.get("review", {}).get("per_kind", 2)), regeneration_mode=raw.get("regeneration", {}).get("mode", "full"),
        work_dir=path(out["work_dir"]), store_kind=store["kind"],
        store_root=path(store["root"]) if "root" in store else None, raw=raw, store_http=http)


def load_config(config_path: Path) -> JobConfig:
    p = Path(config_path).resolve()
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        raise ConfigError(f"설정 파일을 읽을 수 없다: {p}: {e}") from e
    return parse_config(raw, p.parent)
