"""잡(import·run)이 output.store.kind=http로 이 영역의 실제 I2 서버(포트 0)에 게시한다(CR-D26). 가짜 서버가 아니다."""
from __future__ import annotations

import json

import pytest

from conftest import RULES_VERSION, SURVEY_DIR, make_cfg_raw
from synthetic_data.__main__ import main
from synthetic_data.config import ConfigError, parse_config
from test_import import QS, write_input
from test_service import RT, WT, Srv


@pytest.fixture
def srv(tmp_path):
    s = Srv(tmp_path / "srv")
    yield s
    s.close()


def import_cfg(tmp, url, **store):
    raw = {"dataset_id": "ds-http", "input_dir": str(tmp / "in"), "survey_schema_dir": str(SURVEY_DIR), "question_sets": QS,
           "source_label": "fake-test", "action_rules_version": RULES_VERSION, "created_at": "2026-10-27T00:00:00Z",
           "tolerance": {"max_invalid_rows": 0, "max_invalid_rate": 0.0},
           "output": {"work_dir": str(tmp / "work"), "store": {"kind": "http", "base_url": url, "token_env": "SD_TEST_WRITE_TOKEN", **store}}}
    p = tmp / "imp.json"
    p.write_text(json.dumps(raw))
    return p


def test_import_publishes_over_http_and_rerun_is_idempotent(tmp_path, srv, monkeypatch, capsys):
    tokfile = tmp_path / "tok"
    tokfile.write_text(WT + "\n")
    monkeypatch.setenv("SD_TEST_WRITE_TOKEN_FILE", str(tokfile))          # D84: 파일 경로로 받는다
    write_input(tmp_path / "in")
    cfg = import_cfg(tmp_path, srv.url)
    assert main(["import", "--config", str(cfg)]) == 0
    first = json.loads(capsys.readouterr().out)
    assert first["status"] == "PUBLISHED"
    ids = json.loads(srv.call("GET", "/v1/datasets")[1])["items"]
    assert ids == ["ds-http"]
    ver = json.loads(srv.call("GET", "/v1/datasets/ds-http/versions")[1])["items"]
    assert len(ver) == 1
    assert main(["import", "--config", str(cfg)]) == 0                    # 같은 입력 재실행: 새 버전을 만들지 않는다
    second = json.loads(capsys.readouterr().out)
    assert second["status"] == "ALREADY_PUBLISHED" and second.get("dataset_digest") == first.get("dataset_digest")
    assert json.loads(srv.call("GET", "/v1/datasets/ds-http/versions")[1])["items"] == ver


def test_read_token_cannot_publish_from_job(tmp_path, srv, monkeypatch, capsys):
    monkeypatch.setenv("SD_TEST_WRITE_TOKEN", RT)                         # 개발용 환경 변수 호환
    write_input(tmp_path / "in")
    assert main(["import", "--config", str(import_cfg(tmp_path, srv.url))]) == 3     # 경계 오류(PERMISSION_DENIED), 재시도 불가
    assert "PERMISSION_DENIED" in capsys.readouterr().err
    assert json.loads(srv.call("GET", "/v1/datasets")[1])["items"] == []


def test_missing_token_is_config_error_without_value(tmp_path, srv, monkeypatch, capsys):
    monkeypatch.delenv("SD_TEST_WRITE_TOKEN", raising=False)
    monkeypatch.delenv("SD_TEST_WRITE_TOKEN_FILE", raising=False)
    write_input(tmp_path / "in")
    assert main(["import", "--config", str(import_cfg(tmp_path, srv.url))]) == 2
    assert "SD_TEST_WRITE_TOKEN" in capsys.readouterr().err


def test_run_job_publishes_over_http(tmp_path, srv, monkeypatch, capsys):
    monkeypatch.setenv("SD_TEST_WRITE_TOKEN", WT)
    raw = make_cfg_raw(tmp_path, output={"work_dir": str(tmp_path / "w"), "store": {
        "kind": "http", "base_url": srv.url, "token_env": "SD_TEST_WRITE_TOKEN"}})
    p = tmp_path / "job.json"
    p.write_text(json.dumps(raw))
    assert main(["run", "--config", str(p)]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "PUBLISHED"
    assert main(["run", "--config", str(p)]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "ALREADY_PUBLISHED"
    assert json.loads(srv.call("GET", "/v1/datasets/ds-test/versions")[1])["items"].__len__() == 1


@pytest.mark.parametrize("store", [{"kind": "http"}, {"kind": "http", "base_url": "ftp://x"},
                                   {"kind": "http", "base_url": "http://x", "token": "inline-secret"},
                                   {"kind": "http", "base_url": "http://x", "timeout": 0}, {"kind": "nope"}])
def test_http_store_config_errors(tmp_path, store):
    raw = make_cfg_raw(tmp_path, output={"work_dir": str(tmp_path / "w"), "store": store})
    with pytest.raises(ConfigError) as e:
        parse_config(raw, tmp_path)
    assert "inline-secret" not in str(e.value)
