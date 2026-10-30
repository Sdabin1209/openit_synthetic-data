"""설정 읽기(진입점 쪽, 업무 규칙 없음): 설정 파일을 JSON으로 읽고 환경 변수에서 값을 가져온다. 설정의 검사와 정규화는 components/run_plan.py, import_plan.py가 한다."""
from __future__ import annotations

import json
import os
from pathlib import Path

SURVEY_DIR_ENV = "SYNTHETIC_SURVEY_SCHEMA_DIR"


class ConfigError(ValueError):
    """설정 오류(경계 호출이 아니므로 BoundaryError가 아니다)."""


def read_json_file(config_path: Path) -> tuple[dict, Path]:
    p = Path(config_path).resolve()
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        raise ConfigError(f"설정 파일을 읽을 수 없다: {p}: {e}") from e
    if not isinstance(raw, dict):
        raise ConfigError("설정 파일의 최상위는 객체여야 한다")
    return raw, p.parent


def survey_dir_override():
    return os.environ.get(SURVEY_DIR_ENV) or None
