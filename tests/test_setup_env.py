"""scripts/setup-env.sh 출력 규약(계약 SetupEnvReport, U43): 표준 출력 마지막 줄이 보고 JSON이고, test_command가 영역 시험을 돌린다."""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

from boundary_contracts import validator

ROOT = Path(__file__).resolve().parent.parent


def last_line(out: str) -> dict:
    return json.loads(out.strip().splitlines()[-1])


def test_success_last_line_is_setup_env_report_and_test_command_works():
    r = subprocess.run(["bash", str(ROOT / "scripts" / "setup-env.sh")], capture_output=True, text=True, timeout=500)
    assert r.returncode == 0, r.stderr[-500:]
    rep = last_line(r.stdout)
    validator("SetupEnvReport").validate(rep)
    assert rep["area"] == "synthetic-data" and rep["status"] == "ok" and rep["exit_code"] == 0
    env = rep["environment"]
    assert env["kind"] == "python-venv" and (ROOT / env["path"]).is_dir()
    # 전체 시험을 다시 돌리면 이 시험이 재귀하므로 같은 명령에 수집만 시킨다(전체 실행은 영역 시험 전체 실행 자체가 한다)
    t = subprocess.run(env["test_command"] + ["--collect-only", "-q", "tests/test_units.py"], cwd=ROOT, capture_output=True, text=True, timeout=120)
    assert t.returncode == 0, t.stdout[-300:]


def test_progress_goes_to_stderr_not_stdout():
    r = subprocess.run(["bash", str(ROOT / "scripts" / "setup-env.sh")], capture_output=True, text=True, timeout=500)
    assert r.stdout.strip().count("\n") == 0 and "setup-env:" in r.stderr


def test_failure_still_ends_with_a_fail_report(tmp_path):
    (tmp_path / "scripts").mkdir()
    shutil.copy(ROOT / "scripts" / "setup-env.sh", tmp_path / "scripts" / "setup-env.sh")     # requirements.lock이 없는 리포
    r = subprocess.run(["bash", str(tmp_path / "scripts" / "setup-env.sh")], capture_output=True, text=True, timeout=60)
    assert r.returncode == 1
    rep = last_line(r.stdout)
    validator("SetupEnvReport").validate(rep)
    assert rep["status"] == "fail" and rep["exit_code"] == 1
