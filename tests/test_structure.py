"""구조 검사(DESIGN.md 6절, D117). 헤드의 head/scripts/structure-check.py와 같은 기준을 시험으로 강제한다."""
from __future__ import annotations

import ast
import json
import subprocess
import sys
import tempfile
from pathlib import Path

import jsonschema
import pytest

ROOT = Path(__file__).resolve().parent.parent
PKG = ROOT / "synthetic_data"
SCHEMAS = ROOT / "schemas"
HTTP_MODULES = ("boundary_contracts.clients", "openit_link", "urllib.request", "http.client", "http.server", "requests", "waitress", "wsgiref")
ENTRY = {"__init__.py", "__main__.py", "config.py"}      # 진입점·설정(업무 규칙을 두지 않는다)


def code_files():
    return sorted(p for p in PKG.rglob("*.py") if "__pycache__" not in p.parts)


def imports(path: Path):
    """(모듈 이름, 상대 단계, 가져온 이름들)"""
    for n in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(n, ast.Import):
            for a in n.names:
                yield a.name, 0, []
        elif isinstance(n, ast.ImportFrom):
            yield n.module or "", n.level, [a.name for a in n.names]


def test_1_standard_directories_exist():
    assert any(SCHEMAS.glob("*.schema.json"))
    for d in ("types", "components", "wiring"):
        assert any((PKG / d).glob("*.py")), d


def test_2_components_do_not_import_each_other():
    comp = {p.stem for p in (PKG / "components").glob("*.py")}
    bad = []
    for p in (PKG / "components").glob("*.py"):
        for mod, level, names in imports(p):
            parts = mod.split(".") if mod else []
            hit = (level == 1 and parts and parts[0] in comp) or (level == 1 and not parts and set(names) & comp) \
                or (level >= 2 and parts[:1] == ["components"] and len(parts) > 1 and parts[1] in comp) or (mod.startswith("synthetic_data.components"))
            if hit:
                bad.append(f"{p.name}: {mod or names}")
            if level >= 2 and parts[:1] == ["wiring"]:
                bad.append(f"{p.name}: 컴포넌트가 wiring을 안다 ({mod})")
    assert not bad, bad


def test_3_http_only_in_link_components():
    bad = []
    for p in code_files():
        if p.parent.name == "components" and p.name.startswith("link_"):
            continue
        for mod, level, names in imports(p):
            if level == 0 and any(mod == h or mod.startswith(h + ".") for h in HTTP_MODULES):
                bad.append(f"{p.relative_to(ROOT)}: {mod}")
    assert not bad, bad


def _resolver_store():
    docs = {p.name: json.loads(p.read_text(encoding="utf-8")) for p in SCHEMAS.glob("*.schema.json")}
    return docs, {d["$id"]: d for d in docs.values()}


def test_4_every_schema_has_valid_and_invalid_examples_with_right_results():
    docs, store = _resolver_store()
    bad = []
    for fname, schema in docs.items():
        stem = fname[: -len(".schema.json")]
        jsonschema.Draft202012Validator.check_schema(schema)
        v = jsonschema.Draft202012Validator(schema, resolver=jsonschema.RefResolver.from_schema(schema, store=store))
        ok = sorted((SCHEMAS / "examples").glob(f"{stem}.valid*.json"))
        no = sorted((SCHEMAS / "examples").glob(f"{stem}.invalid*.json"))
        if not ok or not no:
            bad.append(f"{stem}: 통과·거부 예시가 모두 있지 않음")
        bad += [f"{p.name}: 통과해야 하는데 거부됨" for p in ok if not v.is_valid(json.loads(p.read_text(encoding="utf-8")))]
        bad += [f"{p.name}: 거부돼야 하는데 통과함" for p in no if v.is_valid(json.loads(p.read_text(encoding="utf-8")))]
    assert not bad, bad


def test_5_types_equal_regenerated_output():
    pytest.importorskip("datamodel_code_generator")
    with tempfile.TemporaryDirectory() as td:
        subprocess.run([sys.executable, str(ROOT / "scripts" / "gen_types.py"), "--out", td], check=True, capture_output=True)
        fresh = {p.name: p.read_text(encoding="utf-8") for p in Path(td).glob("*.py")}
    have = {p.name: p.read_text(encoding="utf-8") for p in (PKG / "types").glob("*.py")}
    assert set(fresh) == set(have), sorted(set(fresh) ^ set(have))
    assert [n for n in fresh if fresh[n] != have[n]] == []


def test_6_every_code_file_belongs_somewhere():
    bad = []
    for p in code_files():
        rel = p.relative_to(PKG)
        top = rel.parts[0]
        if top in ("components", "wiring", "types"):
            continue
        if p.name in ENTRY or (top == "adapters" and p.name == "__init__.py"):
            continue
        bad.append(str(rel))
    assert not bad, bad


def test_components_check_their_input_with_a_schema():
    """컴포넌트는 입력 검사를 스키마 검증 하나로 한다(DESIGN.md 5절): 파일마다 schema_registry의 check를 부른다."""
    missing = [p.name for p in (PKG / "components").glob("*.py") if "check(" not in p.read_text(encoding="utf-8")]
    assert not missing, missing
