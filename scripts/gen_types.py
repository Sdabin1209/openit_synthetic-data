#!/usr/bin/env python3
"""schemas/*.schema.json -> synthetic_data/types/ 생성 (DESIGN.md 3절, D117). 손으로 고치지 않는 파일만 만든다.

만드는 것:
  types/<타입>_schema.py     datamodel-code-generator(TypedDict)가 만든 코드 타입
  types/schema_registry.py   스키마 사본(이미지에는 리포 루트 schemas/가 없다)과 검증 함수
사용: python scripts/gen_types.py [--out <디렉터리>]   (기본: synthetic_data/types. tests/test_structure.py가 임시 디렉터리에 다시 만들어 비교한다)"""
from __future__ import annotations

import argparse
import json
import pprint
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCHEMAS = ROOT / "schemas"

REGISTRY_HEAD = '''"""schemas/에서 생성한 스키마 사본과 검증 함수. 손으로 고치지 않는다(scripts/gen_types.py).

왜 사본을 코드에 넣나: 이미지에는 리포 루트의 schemas/가 없다. 정본은 schemas/*.schema.json이고 tests/test_structure.py가 이 파일이 정본과 같은지 본다.
오류 메시지에는 위반한 값을 싣지 않는다(위치와 규칙 이름만, ADR 0003): 환자 발화일 수 있는 값이 로그·응답으로 새지 않게 한다."""
from __future__ import annotations

import re
from functools import lru_cache
from typing import Any

import jsonschema
from boundary_contracts import BoundaryError
from boundary_contracts import validator as _contract_validator

'''

REGISTRY_TAIL = '''

class SchemaViolation(BoundaryError):
    """입력·출력이 스키마를 어겼다. 경계 오류 INVALID_RECORD와 같다."""

    def __init__(self, message: str, details=None):
        super().__init__("INVALID_RECORD", message, details or {})


_STORE = {s["$id"]: s for s in SCHEMAS.values()}


@lru_cache(maxsize=None)
def _validator(name: str):
    schema = SCHEMAS[name]
    resolver = jsonschema.RefResolver.from_schema(schema, store=_STORE)
    return jsonschema.Draft202012Validator(schema, resolver=resolver)


def _code(e) -> str:
    return (re.sub(r"/\\d+", "/*", "/".join(map(str, e.absolute_path))) or "(루트)") + "#" + e.validator


def codes(name: str, doc: Any) -> list[str]:
    """영역 스키마 위반을 '<경로>#<스키마 키워드>' 코드로(배열 번호는 *). 위반이 없으면 빈 목록."""
    return sorted({_code(e) for e in _validator(name).iter_errors(doc)})


def check(name: str, doc: Any) -> None:
    found = codes(name, doc)
    if found:
        raise SchemaViolation(f"{name} 스키마 위반: {', '.join(found[:5])}", {"errors": found[:10]})


@lru_cache(maxsize=None)
def _contract(name: str):
    return _contract_validator(name)


def contract_codes(name: str, doc: Any) -> list[str]:
    """경계 계약(boundary-contracts) 스키마 위반 코드. 영역 스키마의 codes와 같은 형식."""
    return sorted({_code(e) for e in _contract(name).iter_errors(doc)})


def _deepest(err):
    # oneOf/anyOf는 가장 깊이 들어간 하위 위반이 사람에게 쓸모 있는 위치를 가리킨다
    while err.context:
        err = max(err.context, key=lambda e: len(e.absolute_path))
    return err


def contract_problems(name: str, doc: Any) -> list[str]:
    """계약 스키마 위반을 사람이 읽는 문장으로. 값은 싣지 않는다(설정에 잘못 들어온 토큰 값이 오류로 새는 경로 차단, 표준성 점검 B3)."""
    out = []
    for e in sorted(_contract(name).iter_errors(doc), key=lambda e: list(map(str, e.absolute_path))):
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


def check_contract(name: str, doc: Any) -> None:
    """계약 스키마 검사. 어기면 SchemaViolation(INVALID_RECORD)."""
    p = contract_problems(name, doc)
    if p:
        raise SchemaViolation(f"{name} 계약 스키마 위반: " + "; ".join(p[:5]), {"errors": p[:10]})
'''


def generate(out: Path) -> None:
    out.mkdir(parents=True, exist_ok=True)
    files = sorted(SCHEMAS.glob("*.schema.json"))
    schemas = {p.name[: -len(".schema.json")]: json.loads(p.read_text(encoding="utf-8")) for p in files}
    with tempfile.TemporaryDirectory() as td:
        src = Path(td) / "schemas"
        src.mkdir()
        for p in files:
            shutil.copyfile(p, src / p.name)
        gen = Path(td) / "gen"
        subprocess.run([sys.executable, "-m", "datamodel_code_generator", "--input", str(src), "--input-file-type", "jsonschema", "--output", str(gen),
                        "--output-model-type", "typing.TypedDict", "--target-python-version", "3.10", "--disable-timestamp",
                        "--formatters", "black", "isort", "--no-use-closed-typed-dict"], check=True, capture_output=True)
        for p in sorted(gen.glob("*.py")):
            if p.name == "__init__.py":
                continue
            (out / p.name).write_text(p.read_text(encoding="utf-8"), encoding="utf-8")
    body = "SCHEMAS: dict[str, dict] = " + pprint.pformat(schemas, width=120, sort_dicts=True) + "\n"
    (out / "schema_registry.py").write_text(REGISTRY_HEAD + body + REGISTRY_TAIL, encoding="utf-8")
    (out / "__init__.py").write_text('"""schemas/에서 생성한 코드 타입. 손으로 고치지 않는다(scripts/gen_types.py)."""\n', encoding="utf-8")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, default=ROOT / "synthetic_data" / "types")
    a = ap.parse_args()
    if a.out.exists():
        for p in a.out.glob("*.py"):
            p.unlink()
    generate(a.out)
    print(f"생성: {a.out}")
