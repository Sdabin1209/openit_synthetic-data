"""설정 파일 -> 실행 계획. 설정 읽기(config.py)와 정규화 컴포넌트(run_plan, import_plan)를 잇는다. 계획은 속성으로 읽는 얇은 겉옷이다."""
from __future__ import annotations

from pathlib import Path

from boundary_contracts.action_rules import load_rules
from boundary_contracts.errors import BoundaryError

from ..components import import_plan, run_plan
from ..config import ConfigError, read_json_file, survey_dir_override

_PATH_KEYS = {"work_dir", "input_dir", "survey_schema_dir"}


class Plan:
    """계획(dict)을 속성으로 읽게 한다. 경로 항목은 Path로 돌려준다."""

    def __init__(self, d: dict):
        object.__setattr__(self, "d", d)

    def __getattr__(self, k):
        try:
            v = self.d[k]
        except KeyError:
            raise AttributeError(k) from None
        return Path(v) if k in _PATH_KEYS else v

    def __setattr__(self, k, v):
        self.d[k] = v


def _inputs(raw, base_dir):
    return {"raw": raw, "base_dir": str(base_dir), "survey_dir_override": survey_dir_override(),
            "installed_action_rules_version": str(load_rules()["rules_version"])}


def _call(component, raw, base_dir) -> Plan:
    if not isinstance(raw, dict):
        raise ConfigError("설정 파일의 최상위는 객체여야 한다")
    try:
        return Plan(component.run(_inputs(raw, base_dir)))
    except BoundaryError as e:     # 설정 오류는 경계 호출이 아니라 종료 코드 2다
        raise ConfigError(e.message) from e


def parse_config(raw: dict, base_dir: Path) -> Plan:
    return _call(run_plan, raw, base_dir)


def parse_import_config(raw: dict, base_dir: Path) -> Plan:
    return _call(import_plan, raw, base_dir)


def load_config(config_path: Path) -> Plan:
    raw, base = read_json_file(config_path)
    return parse_config(raw, base)


def load_import_config(config_path: Path) -> Plan:
    raw, base = read_json_file(config_path)
    return parse_import_config(raw, base)
