"""계약 승격 스키마(D107)를 코드가 실제로 쓰는지 확인한다. 기대값은 계약 패키지의 예시(conformance/examples, examples_invalid)에서 온다.

왜: 손으로 키·형식을 검사하던 때는 계약 스키마와 코드가 어긋나도 아무도 몰랐다(예: 중첩 객체의 모르는 키 무시).
설정은 SyntheticJobConfigRun/Import 스키마로 검사하고, 잡 출력(stdout 결과, report.json, import_report.json, stderr 오류)은 내는 쪽이 같은 스키마로 자기 검사한다."""
from __future__ import annotations

import json
import re
from dataclasses import asdict
from pathlib import Path

import pytest

import conformance
from boundary_contracts import validator
from synthetic_data.__main__ import _result_line, main
from synthetic_data.config import ConfigError, parse_config
from synthetic_data.importer import parse_import_config
from synthetic_data.store import MemoryDatasetStore

from conftest import SURVEY_DIR, make_cfg_raw, run as run_job_helper

EX = Path(conformance.__file__).parent / "examples"
BAD = Path(conformance.__file__).parent / "examples_invalid"
ROOT = Path(__file__).resolve().parent.parent


def load(p):
    return json.loads(p.read_text(encoding="utf-8"))


def _bad(prefix):
    return sorted(p for p in BAD.glob(prefix + ".*.json"))


def _with_output(base: dict, output: dict) -> dict:
    return {**base, "output": output}


# --- 설정: 계약 예시가 기대한 대로 받아들이거나 거부한다 ---

def test_contract_example_run_config_is_accepted(tmp_path):
    parse_config(load(EX / "SyntheticJobConfigRun.json"), tmp_path)


def test_contract_example_import_config_is_accepted(tmp_path):
    parse_import_config(load(EX / "SyntheticJobConfigImport.json"), tmp_path)


@pytest.mark.parametrize("p", _bad("SyntheticJobConfigRun"), ids=lambda p: p.name)
def test_run_config_rejects_contract_invalid_examples(p, tmp_path):
    with pytest.raises(ConfigError):
        parse_config(load(p), tmp_path)


@pytest.mark.parametrize("p", _bad("SyntheticJobConfigImport"), ids=lambda p: p.name)
def test_import_config_rejects_contract_invalid_examples(p, tmp_path):
    with pytest.raises(ConfigError):
        parse_import_config(load(p), tmp_path)


def test_defs_store_and_output_examples_are_judged_by_the_contract(tmp_path):
    """SyntheticDefs의 Store/Output 예시를 설정에 끼워 넣으면 유효는 받고 무효는 거부한다(두 설정 모두)."""
    run_base, imp_base = load(EX / "SyntheticJobConfigRun.json"), load(EX / "SyntheticJobConfigImport.json")
    for p in sorted(EX.glob("SyntheticDefs.*.json")):
        d = p.name.split(".")[1]
        out = load(p) if d == "Output" else {**run_base["output"], "store": load(p)}
        parse_config(_with_output(run_base, out), tmp_path)
        parse_import_config(_with_output(imp_base, out), tmp_path)
    for p in sorted(BAD.glob("SyntheticDefs.*.json")):
        d = p.name.split(".")[1]
        out = load(p) if d == "Output" else {**run_base["output"], "store": load(p)}
        with pytest.raises(ConfigError):
            parse_config(_with_output(run_base, out), tmp_path)
        with pytest.raises(ConfigError):
            parse_import_config(_with_output(imp_base, out), tmp_path)


def test_nested_unknown_keys_are_rejected(tmp_path):
    """MANIFEST note: 중첩 객체(tolerance, split, output 등)의 모르는 키도 거부한다(ADR 0014 확장)."""
    imp = load(EX / "SyntheticJobConfigImport.json")
    imp["tolerance"]["max_invalid_rowz"] = 1
    with pytest.raises(ConfigError):
        parse_import_config(imp, tmp_path)
    run = make_cfg_raw(tmp_path)
    run["split"]["ratios"]["TEST"] = 0.1
    with pytest.raises(ConfigError):
        parse_config(run, tmp_path)


def test_config_error_message_has_no_input_values(tmp_path):
    """스키마 오류 메시지는 경로와 규칙 이름만 싣고 입력 값은 싣지 않는다(B3, 토큰 값이 설정에 잘못 들어와도 새지 않는다)."""
    run = make_cfg_raw(tmp_path)
    run["output"]["store"] = {"kind": "http", "base_url": "http://x", "token": "SECRET-VALUE-123"}
    with pytest.raises(ConfigError) as e:
        parse_config(run, tmp_path)
    assert "SECRET-VALUE-123" not in str(e.value)


# --- 잡 출력: 계약 스키마로 자기 검사 ---

def test_run_result_and_report_match_contract(tmp_path, validators):
    cfg, res = run_job_helper(make_cfg_raw(tmp_path), MemoryDatasetStore(validators), validators)
    validator("SyntheticJobResult").validate(asdict(res))
    validator("SyntheticRunReport").validate(json.loads((tmp_path / "work" / "report.json").read_text(encoding="utf-8")))


def test_import_result_and_report_match_contract(tmp_path, validators):
    from test_import import cfg_for, write_input
    from synthetic_data.importer import run_import
    write_input(tmp_path / "in")
    res = run_import(cfg_for(tmp_path), store=MemoryDatasetStore(validators), validators=validators)
    validator("SyntheticJobResult").validate(asdict(res))
    validator("SyntheticImportReport").validate(json.loads((tmp_path / "work" / "import_report.json").read_text(encoding="utf-8")))


def test_cli_config_error_line_matches_job_error_contract(tmp_path, capsys):
    p = tmp_path / "bad.json"
    p.write_text(json.dumps({"dataset_id": "x", "nope": 1}), encoding="utf-8")
    assert main(["run", "--config", str(p)]) == 2
    validator("SyntheticJobError").validate(json.loads(capsys.readouterr().err.strip().splitlines()[-1]))


def test_cli_missing_config_file_is_job_error(tmp_path, capsys):
    assert main(["import", "--config", str(tmp_path / "none.json")]) == 2
    validator("SyntheticJobError").validate(json.loads(capsys.readouterr().err.strip().splitlines()[-1]))


# --- 이미지 라벨: Dockerfile이 계약 ImageLabels를 만족한다 ---

def _dockerfile_labels(revision: str, bc: str, survey: str) -> dict:
    text = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    args = dict(re.findall(r"^ARG (\w+)=(\S+)$", text, re.M))
    args.update({"REVISION": revision, "BC_VERSION": bc, "SURVEY_SCHEMA_VERSION": survey})
    block = text[text.index("LABEL "):].split("\nCMD")[0]
    labels = dict(re.findall(r'(io\.openit\.[\w.-]+)="([^"]*)"', block))
    return {k: re.sub(r"\$\{(\w+)\}", lambda m: args[m.group(1)], v) for k, v in labels.items()}


def test_dockerfile_labels_satisfy_image_labels_contract():
    labels = _dockerfile_labels("96d56ba", "v2.5.0", "1")
    validator("ImageLabels").validate(labels)
    assert labels["io.openit.service"] == "dataset-store"


def test_dockerfile_arg_defaults_use_na_not_unknown():
    """ARG 기본값은 n/a다(none/unknown/unset 불가). 기본값 그대로 빌드되면 revision 검사가 빌드를 멈춘다."""
    text = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    for name, val in re.findall(r"^ARG (\w+)=(\S+)$", text, re.M):
        assert val.lower() not in ("none", "unknown", "unset"), name
    assert "n/a" in text
    assert re.search(r"\[0-9a-f\]\{7,40\}", text), "REVISION이 hex가 아니면 빌드가 실패해야 한다"


def test_smoke_script_does_not_fall_back_to_unknown_revision():
    assert "echo unknown" not in (ROOT / "scripts" / "smoke_service.sh").read_text(encoding="utf-8")


def test_cli_result_line_drops_empty_rejected_reasons_unless_rejected():
    from synthetic_data.importer import ImportResult
    ok = json.loads(_result_line(ImportResult("ALREADY_PUBLISHED", "ds", "v1", "sha256:" + "a" * 64, "sha256:" + "b" * 64)))
    assert "rejected_reasons" not in ok


def test_turn_engine_version_comes_from_config_even_if_turn_engine_is_installed(tmp_path, validators, monkeypatch):
    """D109: turn_engine_version은 설치본이 아니라 설정의 고정 표지다. 설치돼 있어도 설정값이 매니페스트에 들어간다."""
    import sys
    import types
    fake = types.ModuleType("turn_engine")
    fake.ENGINE_VERSION = "v9.9.9-installed"
    monkeypatch.setitem(sys.modules, "turn_engine", fake)
    st = MemoryDatasetStore(validators)
    _, res = run_job_helper(make_cfg_raw(tmp_path, turn_engine_version="0.4.3"), st, validators)
    assert st.get_manifest(res.dataset_id, res.version)["turn_engine_version"] == "0.4.3"
