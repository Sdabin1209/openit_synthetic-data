"""I1·I7을 실제 HTTP 클라이언트(boundary_contracts.clients)와 참조 서버로 읽는 통합 시험."""
from __future__ import annotations

import json

import pytest

import doubles
from conftest import SURVEY_DIR, make_cfg_raw
from ref_server import ReferenceServer, ref_of
from synthetic_data.__main__ import main

TOK = "tok-reader"


def review(ref):
    return {"pipeline_schema_version": "1.0", "review_id": "rv-" + ref["id"], "question_set": ref,
            "reviewer_role": "clinical-reviewer", "decision": "APPROVED", "clinical_basis_approved": True,
            "reviewed_at": "2026-10-15T00:00:00Z"}


def make_server(case_mutations=()):
    srv = ReferenceServer({TOK: "reader"})
    banks = {"qs-main": doubles.make_bank("main"), "qs-unseen": doubles.make_bank("unseen")}
    refs = {}
    for qid, bank in banks.items():
        ref = ref_of(qid, str(bank["version"]), bank)
        srv.add_question_set(qid, bank, reviews=[review(ref)])
        refs[qid] = ref
    fs = doubles.make_failure_store(banks["qs-main"])
    p, tr = fs.get_case("fc-p"), fs.get_trace("tr-p")
    c = doubles.failure_case("fc-new", "tr-new", p["expected"], question_set=refs["qs-main"], expected_kind="PARSER")
    for m in case_mutations:
        m(c)
    srv.cases += [c, fs.get_case("fc-pending")]
    srv.deid_traces["tr-new"] = dict(tr, session_id="sess-new")
    srv.deid_traces["tr-x"] = fs.get_trace("tr-x")
    return srv


def http_cfg(tmp_path, url, **over):
    ad = lambda f: {"factory": f"synthetic_data.adapters:{f}", "kwargs": {"base_url": url, "token_env": "SYN_TEST_TOKEN"}}
    raw = make_cfg_raw(tmp_path, adapters={"question_reader": ad("http_question_reader"), "failure_store": ad("http_failure_store")},
                       output={"work_dir": str(tmp_path / "w"), "store": {"kind": "file", "root": str(tmp_path / "st")}},
                       seeds={"enabled": True}, **over)
    p = tmp_path / "job.json"
    p.write_text(json.dumps(raw))
    return p


def test_job_over_http(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("SYN_TEST_TOKEN", TOK)
    unknown = lambda c: c.update(future_field={"a": 1}, expected_kind="FUTURE_KIND")
    with make_server([unknown]) as srv:
        assert main(["run", "--config", str(http_cfg(tmp_path, srv.url))]) == 0
        out = json.loads(capsys.readouterr().out)
        paths = [r[1] for r in srv.requests]
    assert out["status"] == "PUBLISHED"
    assert any(p.startswith("/v1/question-sets/qs-main/latest") for p in paths) and any("/v1/cases" in p for p in paths)
    assert all(r[0] == "GET" for r in srv.requests)                       # 읽기만 한다
    rep = json.loads((tmp_path / "w" / "report.json").read_text())
    assert "error" not in rep
    assert any("fc-new" in n and "future_field" in n for n in rep["notes"])      # 모르는 필드는 받아들이고 남긴다
    assert any("FUTURE_KIND" in n for n in rep["notes"])                          # 모르는 열거값도
    m = json.loads(next((tmp_path / "st" / "ds-test").glob("*/manifest.json")).read_text())
    assert m["seed_case_ids"] == ["fc-new"]


def test_major_mismatch_is_unsupported_version_in_report(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("SYN_TEST_TOKEN", TOK)
    with make_server([lambda c: c.update(pipeline_schema_version="2.0")]) as srv:
        assert main(["run", "--config", str(http_cfg(tmp_path, srv.url))]) == 3
    err = json.loads((tmp_path / "w" / "report.json").read_text())["error"]
    assert err["code"] == "UNSUPPORTED_VERSION" and err["retryable"] is False
    assert not list((tmp_path / "st").glob("ds-test/*"))                   # 아무것도 게시하지 않았다


def test_server_down_is_retryable(tmp_path, monkeypatch):
    monkeypatch.setenv("SYN_TEST_TOKEN", TOK)
    with make_server() as srv:
        url = srv.url
    assert main(["run", "--config", str(http_cfg(tmp_path, url))]) == 75
    assert json.loads((tmp_path / "w" / "report.json").read_text())["error"]["code"] == "UNAVAILABLE"


def test_missing_token_env_is_config_error(tmp_path, monkeypatch):
    monkeypatch.delenv("SYN_TEST_TOKEN", raising=False)
    with make_server() as srv:
        assert main(["run", "--config", str(http_cfg(tmp_path, srv.url))]) == 2


def test_wrong_token_is_permission_denied(tmp_path, monkeypatch):
    monkeypatch.setenv("SYN_TEST_TOKEN", "wrong")
    with make_server() as srv:
        assert main(["run", "--config", str(http_cfg(tmp_path, srv.url))]) == 3
    assert json.loads((tmp_path / "w" / "report.json").read_text())["error"]["code"] == "PERMISSION_DENIED"
