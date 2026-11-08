"""설정 읽기(진입점 쪽, 업무 규칙 없음): 설정 파일을 JSON으로 읽고 환경 변수에서 값을 가져온다. 설정의 검사와 정규화는 components/run_plan.py, import_plan.py가 한다."""
from __future__ import annotations

from pathlib import Path

from boundary_contracts import BoundaryError, strict_json

# 왜 환경 변수가 아닌가: 이미지 안의 문진 스키마 위치는 영역 안 값이다. 환경 변수로 받으면 계약 Env 스키마에 없는 입력 이름이 생긴다(R9.1).
# 이미지는 Dockerfile이 이 경로에 스키마를 복사한다. 이 경로가 디렉터리일 때만(= 이미지 안일 때만) 설정의 survey_schema_dir보다 우선한다(CR-009의 임시 처리를 이어받음).
IMAGE_SURVEY_SCHEMA_DIR = Path("/app/survey_schema")


class ConfigError(ValueError):
    """설정 오류(경계 호출이 아니므로 BoundaryError가 아니다)."""


def read_json_file(config_path: Path) -> tuple[dict, Path]:
    p = Path(config_path).resolve()
    try:
        # 왜 strict_json: 설정 파일은 사람이 쓰는 입력이다. 계약 JSON 공통 규칙(중복 키·NaN·깊이·크기, 계약 5.0.0 CONVENTIONS)을 같은 구현으로 건다
        raw = strict_json.loads(p.read_bytes())
    except (OSError, BoundaryError) as e:
        raise ConfigError(f"설정 파일을 읽을 수 없다: {p}: {e}") from e
    if not isinstance(raw, dict):
        raise ConfigError("설정 파일의 최상위는 객체여야 한다")
    return raw, p.parent


def survey_dir_override():
    return str(IMAGE_SURVEY_SCHEMA_DIR) if IMAGE_SURVEY_SCHEMA_DIR.is_dir() else None
