"""잡 설정과 잡 출력을 계약 스키마(boundary-contracts D107)로 검사한다. 형식 검사는 계약이 정본이고 여기서 다시 쓰지 않는다.

왜 메시지를 직접 만드나: jsonschema의 기본 메시지는 입력 값을 그대로 싣는다(설정에 잘못 들어온 토큰 값이 오류에 새는 경로). 그래서 위치와 위반한 규칙 이름만 싣는다(표준성 점검 B3)."""
from __future__ import annotations

from functools import lru_cache
from typing import Callable

from boundary_contracts import validator


@lru_cache(maxsize=None)
def _v(name: str):
    return validator(name)


def _deepest(err):
    """oneOf/anyOf는 가장 깊이 들어간 하위 위반이 사람에게 쓸모 있는 위치를 가리킨다."""
    while err.context:
        err = max(err.context, key=lambda e: len(e.absolute_path))
    return err


def problems(name: str, doc) -> list:
    out = []
    for e in sorted(_v(name).iter_errors(doc), key=lambda e: list(map(str, e.absolute_path))):
        d = _deepest(e)
        where = ".".join(str(p) for p in d.absolute_path) or "(최상위)"
        if d.validator == "additionalProperties":
            extra = sorted(set(d.instance) - set(d.schema.get("properties", {})))
            out.append(f"{where}: 알 수 없는 키 {extra} (ADR 0014)")
        elif d.validator == "required":
            out.append(f"{where}: 필수 키 누락 ({d.validator_value})")
        else:
            out.append(f"{where}: {name} 스키마의 {d.validator} 규칙 위반")
    return out


def check_config(name: str, doc, err: Callable[[str], Exception]) -> None:
    if not isinstance(doc, dict):
        raise err("설정 파일의 최상위는 객체여야 한다")
    p = problems(name, doc)
    if p:
        raise err(f"설정이 계약 스키마 {name}에 맞지 않는다: " + "; ".join(p[:5]))


def check_output(name: str, doc: dict) -> None:
    """잡이 낸 값을 내보내기 전에 자기 검사한다. 어긋나면 코드 결함이므로 AssertionError로 크게 멈춘다."""
    p = problems(name, doc)
    if p:
        raise AssertionError(f"{name} 계약을 어긴 출력: " + "; ".join(p[:5]))
