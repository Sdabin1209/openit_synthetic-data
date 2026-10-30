"""시드 잡 설정 정규화. RunConfigInput -> RunPlan.

설정 파일(JSON) 하나가 잡의 모든 입력이다. 키·형식 검사는 계약 SyntheticJobConfigRun이 정본이다(D107): 모르는 키 거부(최상위·중첩), v1 생성 키 거부, 토큰 값 거부가 모두 여기서 걸린다.
계약이 못 쓰는 불변식(분할 비율의 합>0, 시드가 켜지면 failure_store 필요)은 출력 스키마 RunPlan에 있다. 평가셋 구성은 O11(사용자 결정)이라 기본값이 없다."""
from __future__ import annotations

from pathlib import Path

from ..types.schema_registry import check, check_contract, SchemaViolation

SURVEY_DIR_ENV = "SYNTHETIC_SURVEY_SCHEMA_DIR"
DEFAULT_TOKEN_ENV = "DATASET_STORE_WRITE_TOKEN"     # 서버의 DATASET_STORE_WRITE_TOKENS(목록, 복수형)와 이름이 겹치지 않게 단수형
DEFAULT_TIMEOUT = 60.0     # 게시는 수 MB tar 한 번이다. 읽기 기본(10초)보다 넉넉하게 잡은 시작값, 측정 안 함(ADR 0013)


def _resolve(base_dir: str, s: str) -> str:
    p = Path(s)
    return str(p if p.is_absolute() else (Path(base_dir) / p).resolve())


def _store_plan(store: dict, base_dir: str) -> dict:
    """계약 SyntheticDefs.Store를 계획의 저장소 항목으로. http의 기본값은 여기서 채운다."""
    kind = store["kind"]
    return {"kind": kind, "root": _resolve(base_dir, store["root"]) if kind == "file" else None,
            "http": {"base_url": store["base_url"], "token_env": store.get("token_env", DEFAULT_TOKEN_ENV),
                     "timeout": float(store.get("timeout", DEFAULT_TIMEOUT))} if kind == "http" else None}


def _survey_dir(inp: dict) -> str:
    """환경 변수가 있으면 설정 값보다 우선한다.
    왜: 이미지 안의 스키마 위치는 이미지의 내부 사항이다. 잡 선언(io.openit.jobs)으로 이미지를 돌리는 쪽(deploy)이 그 경로를 몰라도 되게,
    이미지가 ENV로 위치를 정해 두고 설정의 survey_schema_dir(계약 스키마가 필수로 요구)보다 이것을 쓴다. 설정 쪽을 생략 가능하게 하는 것은 CR-009."""
    return _resolve(inp["base_dir"], inp["survey_dir_override"] or inp["raw"]["survey_schema_dir"])


def _rules_version(raw: dict, installed: str) -> str:
    """매니페스트에 적을 LoRA-A 출력 규칙의 세대. 정본은 설치된 계약의 규칙 데이터이고 코드에 리터럴을 두지 않는다(계약 3.0.0, D109).
    설정에 값이 있으면 기대값이라 설치본과 다르면 거부한다: 다른 규칙 세대로 만든 데이터에 이 세대의 표지를 붙이면 계보가 거짓이 된다."""
    configured = raw.get("action_rules_version")
    if configured is not None and configured != installed:
        raise SchemaViolation(f"설정의 action_rules_version이 설치된 계약의 규칙 세대({installed})와 다르다")
    return installed


def run(inp: dict) -> dict:
    check("RunConfigInput", inp)
    raw = inp["raw"]
    check_contract("SyntheticJobConfigRun", raw)
    ids: dict = {}
    for q in raw["question_sets"]:
        if ids.setdefault(q["id"], q.get("usage", "TRAIN_POOL")) != q.get("usage", "TRAIN_POOL"):
            raise SchemaViolation(f"같은 문항 세트 {q['id']}를 TRAIN_POOL과 HELD_OUT_EVAL에 함께 쓸 수 없다")     # 스키마 밖 조건 표 1번
    sd = raw.get("seeds", {})
    if sd.get("question_set_id") is not None and sd["question_set_id"] not in ids and sd.get("enabled", False):
        raise SchemaViolation("seeds.question_set_id가 question_sets에 없다")                                    # 스키마 밖 조건 표 2번
    ad = raw["adapters"]
    adapter = lambda a: {"factory": a["factory"], "kwargs": dict(a.get("kwargs", {}))}
    plan = {
        "dataset_id": raw["dataset_id"], "seed": raw["seed"], "created_at": raw.get("created_at"), "version": raw.get("version"),
        "action_rules_version": _rules_version(raw, inp["installed_action_rules_version"]), "survey_schema_dir": _survey_dir(inp),
        "question_reader": adapter(ad["question_reader"]), "failure_store": adapter(ad["failure_store"]) if "failure_store" in ad else None,
        "question_sets": [{"id": q["id"], "version": q.get("version"), "usage": q.get("usage", "TRAIN_POOL")} for q in raw["question_sets"]],
        "reviewed_only": bool(raw.get("reviewed_only", True)), "seeds_enabled": bool(sd.get("enabled", False)),
        "seeds_question_set_id": sd.get("question_set_id"),
        # 왜: import의 tolerance.max_pii_suspect_rows와 같은 기본(거부)이다. 시드는 이웃이 비식별했다고 한 값이지만 의심 패턴 검사는 별개다(표준성 점검 C4)
        "seeds_max_pii_suspect": sd["max_pii_suspect_rows"] if "max_pii_suspect_rows" in sd else 0,
        "ratios": {k: float(v) for k, v in raw["split"]["ratios"].items()},
        "review_per_kind": int(raw.get("review", {}).get("per_kind", 2)), "regeneration_mode": raw.get("regeneration", {}).get("mode", "full"),
        "work_dir": _resolve(inp["base_dir"], raw["output"]["work_dir"]), "store": _store_plan(raw["output"]["store"], inp["base_dir"])}
    check("RunPlan", plan)
    return plan
