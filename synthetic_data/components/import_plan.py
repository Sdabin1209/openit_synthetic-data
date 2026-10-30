"""게시기 설정 정규화. ImportConfigInput -> ImportPlan.

키·형식·허용치 범위·origin·pending_policy 값 검사는 계약 SyntheticJobConfigImport가 정본이다(D107, ADR 0014). 스키마로 쓸 수 없는 불변식은 없다.
기본값은 가장 엄격하다: 개인정보 의심 패턴 행은 0건만 허용(경고만 하려면 null을 명시), pending은 보고만(ADR 0005)."""
from __future__ import annotations

from pathlib import Path

from ..types.schema_registry import check, check_contract, SchemaViolation

DEFAULT_TOKEN_ENV = "DATASET_STORE_WRITE_TOKEN"
DEFAULT_TIMEOUT = 60.0     # 게시는 수 MB tar 한 번이다. 읽기 기본(10초)보다 넉넉하게 잡은 시작값, 측정 안 함(ADR 0013)


def _resolve(base_dir: str, s: str) -> str:
    p = Path(s)
    return str(p if p.is_absolute() else (Path(base_dir) / p).resolve())


def _store(store: dict, base_dir: str) -> dict:
    kind = store["kind"]
    return {"kind": kind, "root": _resolve(base_dir, store["root"]) if kind == "file" else None,
            "http": {"base_url": store["base_url"], "token_env": store.get("token_env", DEFAULT_TOKEN_ENV),
                     "timeout": float(store.get("timeout", DEFAULT_TIMEOUT))} if kind == "http" else None}


def run(inp: dict) -> dict:
    check("ImportConfigInput", inp)
    raw, base = inp["raw"], inp["base_dir"]
    check_contract("SyntheticJobConfigImport", raw)
    configured, installed = raw.get("action_rules_version"), inp["installed_action_rules_version"]
    if configured is not None and configured != installed:     # 계보가 거짓이 되지 않게(D109). 설치본이 동적이라 스키마 밖 조건 표 3번
        raise SchemaViolation(f"설정의 action_rules_version이 설치된 계약의 규칙 세대({installed})와 다르다")
    tol, out = raw["tolerance"], raw["output"]
    plan = {
        "dataset_id": raw["dataset_id"], "input_dir": _resolve(base, raw["input_dir"]),
        "survey_schema_dir": _resolve(base, inp["survey_dir_override"] or raw["survey_schema_dir"]),   # 환경 변수가 설정보다 우선(run_plan과 같은 이유)
        "question_sets": raw["question_sets"], "source_label": raw["source_label"].strip(), "action_rules_version": installed,
        "tolerance": {"max_invalid_rows": tol["max_invalid_rows"], "max_invalid_rate": float(tol["max_invalid_rate"]),
                      "max_pii_suspect_rows": tol["max_pii_suspect_rows"] if "max_pii_suspect_rows" in tol else 0},
        "max_cross_split_duplicates": tol.get("max_cross_split_duplicate_inputs", 0),
        "version": raw.get("version"), "created_at": raw.get("created_at"), "work_dir": _resolve(base, out["work_dir"]),
        "pending_policy": raw.get("pending_policy", "report"), "store": _store(out["store"], base)}
    check("ImportPlan", plan)
    return plan
