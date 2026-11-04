"""dataset-store 백업·복구 잡(RUNTIME R10.1): 잡 선언·노출 선언의 계약 검증, 연결(환경 -> 입력), 백업->복구 왕복과 변이.
왕복은 Debian 공식 패키지의 restic 과 restic-rest-server(scripts/fetch-test-tools.sh)로 실제 REST 프로토콜을 쓴다. 두 도구가 PATH 에 없으면 왕복을 건너뛰고 pytest 는 종료 코드 77(SKIP, 통과 아님)로 끝난다(tests/conftest.py).
시험 서버는 시험이 띄운 자식 프로세스이고 끝나면 그 PID 만 종료한다."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from conftest import HANG_GUARD_SECONDS, TOOLS_MISSING_MARK

from boundary_contracts import validator
from synthetic_data import __main__ as entry
from synthetic_data.components import backup_job
from synthetic_data.config import ConfigError
from synthetic_data.wiring import backup_job as wiring

ROOT = Path(__file__).resolve().parent.parent
JOBS = {j["name"]: j for j in json.loads((ROOT / "jobs.json").read_text(encoding="utf-8"))["jobs"]}
HAVE_TOOLS = bool(shutil.which("restic") and shutil.which("restic-rest-server"))
needs_tools = pytest.mark.skipif(not HAVE_TOOLS, reason=TOOLS_MISSING_MARK + " restic·restic-rest-server가 PATH에 없다(scripts/fetch-test-tools.sh 후 PATH=build/tools/usr/bin:$PATH)")


# --- 계약 ---------------------------------------------------------------------------------------------------------------------

def test_jobs_declaration_is_valid_and_declares_backup_and_restore():
    validator("JobsDeclaration").validate({"jobs": list(JOBS.values())})
    for name, sub in (("dataset-backup", "backup"), ("dataset-restore", "restore")):
        j = JOBS[name]
        assert j["argv"] == ["python", "-m", "synthetic_data", sub] and j["idempotent"] is True
        assert j["needs"] == ["datasets-data"]
        assert sorted(j["secret_files"]) == ["OPENIT_BACKUP_CREDENTIALS_FILE", "OPENIT_BACKUP_REPO_PASSWORD_FILE"]
        assert sorted(j["env"]) == ["OPENIT_BACKUP_URL", "OPENIT_EGRESS_PROXY"]
        assert j["timeout_seconds"] == 1800        # 측정하지 않은 시작값(ADR 0025). 기본 상한 3600초(R9.3)보다 짧아야 하는 주기 조건만 본다
        assert "config" not in j                   # 설정은 환경과 비밀 파일뿐이다(CommonEnv)


def test_exposure_declares_external_backup_egress_and_is_valid():
    exp = json.loads((ROOT / "deploy-exposure.json").read_text(encoding="utf-8"))
    validator("Exposure").validate(exp)
    assert "external:backup" in exp["egress"]


def test_result_validates_against_contract_for_ok_and_failed():
    now = "2026-11-05T00:00:00Z"
    validator("BackupJobResult").validate({"status": "ok", "snapshot_id": "a" * 8, "bytes": 3, "started_at": now, "finished_at": now})
    validator("BackupJobResult").validate({"status": "failed", "snapshot_id": None, "bytes": 0, "started_at": now, "finished_at": now,
                                           "error": {"code": "UNAVAILABLE", "message": "x", "retryable": True}})


# --- 연결 ---------------------------------------------------------------------------------------------------------------------

def _env(tmp: Path, **over) -> dict:
    (tmp / "cred").write_text("synthetic-data:s3cret-pass\n")
    (tmp / "pw").write_text("repo-pass\n")
    env = {"OPENIT_BACKUP_URL": "https://backup-store/synthetic-data", "OPENIT_BACKUP_CREDENTIALS_FILE": str(tmp / "cred"),
           "OPENIT_BACKUP_REPO_PASSWORD_FILE": str(tmp / "pw"), "OPENIT_EGRESS_PROXY": "http://127.0.0.1:3128", "DATASET_STORE_ROOT": "/data"}
    env.update(over)
    return {k: v for k, v in env.items() if v is not None}


def test_build_input_maps_env_and_secret_files(tmp_path):
    inp = wiring.build_input("backup", _env(tmp_path))
    assert inp["repository"] == "rest:https://backup-store/synthetic-data" and inp["data_dir"] == "/data" and inp["exclude"] == [".tmp"]
    assert (inp["rest_user"], inp["rest_password"]) == ("synthetic-data", "s3cret-pass") and inp["proxy"] == "http://127.0.0.1:3128"
    assert inp["password_file"] == str(tmp_path / "pw")        # 암호는 값이 아니라 파일 경로로만 다룬다(restic 이 직접 읽는다)


@pytest.mark.parametrize("over", [{"OPENIT_BACKUP_URL": None}, {"OPENIT_BACKUP_URL": "http://backup-store/x"}, {"OPENIT_EGRESS_PROXY": None},
                                  {"OPENIT_BACKUP_REPO_PASSWORD_FILE": None}, {"OPENIT_BACKUP_CREDENTIALS_FILE": None}])
def test_build_input_rejects_missing_or_insecure_config(tmp_path, over):
    with pytest.raises(ConfigError):
        wiring.build_input("restore", _env(tmp_path, **over))


def test_credentials_without_colon_are_rejected_without_echoing_value(tmp_path):
    env = _env(tmp_path)
    Path(env["OPENIT_BACKUP_CREDENTIALS_FILE"]).write_text("nocolonsecretvalue\n")
    with pytest.raises(ConfigError) as e:
        wiring.build_input("backup", env)
    assert "nocolonsecretvalue" not in str(e.value)


def test_entry_returns_2_and_prints_no_secret_on_config_error(tmp_path, monkeypatch, capsys):
    for k in ("OPENIT_BACKUP_URL", "OPENIT_BACKUP_CREDENTIALS_FILE", "OPENIT_BACKUP_REPO_PASSWORD_FILE", "OPENIT_EGRESS_PROXY"):
        monkeypatch.delenv(k, raising=False)
    assert entry.main(["backup"]) == 2
    assert capsys.readouterr().out == ""


# --- 왕복(실제 restic REST) ---------------------------------------------------------------------------------------------------

CLOCK = lambda: "2026-11-05T00:00:00Z"     # 주입 시계(ADR 0023): 시험이 실제 시간을 읽지 않는다


@pytest.fixture
def rest_server(tmp_path):
    # --listen 포트 0: 서버가 빈 포트를 고르고 "start server on <주소>" 한 줄을 낸다. 그 줄을 읽을 때까지 막혀 기다릴 뿐 시간을 재지 않는다
    # --no-auth: 인증 경로는 잡이 아니라 서버의 몫이라 여기서 시험하지 않는다(자격은 환경 변수로 restic 에 전달만 한다). 시험 전용 loopback 서버다
    p = subprocess.Popen(["restic-rest-server", "--path", str(tmp_path / "repos"), "--listen", "127.0.0.1:0", "--no-auth"], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    try:
        port = None
        for line in p.stdout:
            if line.startswith("start server on "):
                port = int(line.rsplit(":", 1)[1]); break
        assert port, "시험 REST 서버가 뜨지 않았다"
        yield port
    finally:
        p.terminate(); p.wait(timeout=HANG_GUARD_SECONDS); p.stdout.close()


def _inp(tmp: Path, port: int, mode: str, *, data: Path, pw: str = "repo-pass", repo: str = "area") -> dict:
    (tmp / "pw").write_text(pw)
    return {"mode": mode, "data_dir": str(data), "exclude": [".tmp"], "repository": f"rest:http://127.0.0.1:{port}/{repo}", "password_file": str(tmp / "pw"),
            "rest_user": None, "rest_password": None, "proxy": None}


def _tree(root: Path) -> dict:
    return {str(p.relative_to(root)): p.read_bytes() for p in sorted(root.rglob("*")) if p.is_file()}


def _populate(data: Path) -> dict:
    (data / "ds-a" / "v1").mkdir(parents=True)
    (data / "ds-a" / "v1" / "manifest.json").write_text('{"v": 1}')
    (data / "ds-a" / "v1" / "train.jsonl").write_bytes(b"line1\nline2\n" * 1000)
    (data / "ds-b").mkdir()
    (data / "ds-b" / "x.bin").write_bytes(bytes(range(256)) * 40)
    (data / ".tmp").mkdir()
    (data / ".tmp" / "partial").write_text("요청 임시 파일")
    return {k: v for k, v in _tree(data).items() if not k.startswith(".tmp")}


@needs_tools
def test_backup_then_restore_round_trip_with_mutations(tmp_path, rest_server):
    data = tmp_path / "data"; data.mkdir()
    original = _populate(data)
    b = backup_job.run(clock=CLOCK, inp=_inp(tmp_path, rest_server, "backup", data=data))
    assert b["exit_code"] == 0 and b["result"]["status"] == "ok" and b["result"]["snapshot_id"] and b["result"]["bytes"] >= sum(map(len, original.values()))
    validator("BackupJobResult").validate(b["result"])
    # 변이: 파일 변경, 파일 삭제, 폴더 통째 삭제, 백업 뒤에 생긴 파일(복구는 지우지 않는다)
    (data / "ds-a" / "v1" / "train.jsonl").write_bytes(b"corrupted")
    (data / "ds-a" / "v1" / "manifest.json").unlink()
    shutil.rmtree(data / "ds-b")
    (data / "late.txt").write_text("백업 뒤에 생김")
    r = backup_job.run(clock=CLOCK, inp=_inp(tmp_path, rest_server, "restore", data=data))
    assert r["exit_code"] == 0 and r["result"]["status"] == "ok" and r["result"]["snapshot_id"] == b["result"]["snapshot_id"]
    validator("BackupJobResult").validate(r["result"])
    now = _tree(data)
    for k, v in original.items():
        assert now[k] == v, k
    assert now["late.txt"] == "백업 뒤에 생김".encode()
    assert ".tmp/partial" in now          # 복구가 .tmp 를 건드리지 않는다


@needs_tools
def test_tmp_dir_is_not_in_snapshot(tmp_path, rest_server):
    data = tmp_path / "data"; data.mkdir(); _populate(data)
    backup_job.run(clock=CLOCK, inp=_inp(tmp_path, rest_server, "backup", data=data))
    shutil.rmtree(data / ".tmp"); shutil.rmtree(data / "ds-a")
    assert backup_job.run(clock=CLOCK, inp=_inp(tmp_path, rest_server, "restore", data=data))["exit_code"] == 0
    assert not (data / ".tmp").exists() and (data / "ds-a" / "v1" / "manifest.json").exists()


@needs_tools
def test_backup_is_idempotent_and_restore_uses_latest(tmp_path, rest_server):
    data = tmp_path / "data"; data.mkdir(); _populate(data)
    first = backup_job.run(clock=CLOCK, inp=_inp(tmp_path, rest_server, "backup", data=data))
    (data / "ds-b" / "x.bin").write_bytes(b"newer")
    second = backup_job.run(clock=CLOCK, inp=_inp(tmp_path, rest_server, "backup", data=data))
    assert first["exit_code"] == second["exit_code"] == 0 and first["result"]["snapshot_id"] != second["result"]["snapshot_id"]
    (data / "ds-b" / "x.bin").write_bytes(b"x")
    assert backup_job.run(clock=CLOCK, inp=_inp(tmp_path, rest_server, "restore", data=data))["result"]["snapshot_id"] == second["result"]["snapshot_id"]
    assert (data / "ds-b" / "x.bin").read_bytes() == b"newer"


@needs_tools
def test_restore_without_any_backup_fails_not_found_not_retryable(tmp_path, rest_server):
    data = tmp_path / "data"; data.mkdir()
    out = backup_job.run(clock=CLOCK, inp=_inp(tmp_path, rest_server, "restore", data=data, repo="empty"))
    assert out["exit_code"] == 1 and out["result"]["status"] == "failed" and out["result"]["error"]["code"] == "NOT_FOUND" and out["result"]["error"]["retryable"] is False
    assert out["result"]["snapshot_id"] is None
    validator("BackupJobResult").validate(out["result"])


@needs_tools
def test_wrong_repo_password_fails_permission_denied_without_leaking_it(tmp_path, rest_server):
    data = tmp_path / "data"; data.mkdir(); _populate(data)
    assert backup_job.run(clock=CLOCK, inp=_inp(tmp_path, rest_server, "backup", data=data))["exit_code"] == 0
    bad = backup_job.run(clock=CLOCK, inp=_inp(tmp_path, rest_server, "restore", data=data, pw="wrong-password-xyz"))
    assert bad["exit_code"] == 1 and bad["result"]["error"]["code"] == "PERMISSION_DENIED"
    assert "wrong-password-xyz" not in json.dumps(bad)


@pytest.mark.parametrize("mode", ["backup", "restore"])
def test_no_answer_from_store_is_retryable_75(tmp_path, monkeypatch, mode):
    """restic 이 저장소에 닿지 못해 첫 확인이 시간 안에 끝나지 않으면 75(UNAVAILABLE, 재시도 가능). 실제로 기다리지 않고 시간 초과 예외로 대신한다(우리 코드의 대응만 본다)."""
    def never_answers(cmd, **kw):
        assert kw["timeout"] == backup_job.PROBE_TIMEOUT_SECONDS            # 첫 확인에 상한이 걸려 있다
        raise subprocess.TimeoutExpired(cmd, kw["timeout"])
    monkeypatch.setattr(backup_job.subprocess, "run", never_answers)
    data = tmp_path / "data"; data.mkdir()
    out = backup_job.run(clock=CLOCK, inp=_inp(tmp_path, 1, mode, data=data))
    assert out["exit_code"] == 75 and out["result"]["error"]["code"] == "UNAVAILABLE" and out["result"]["error"]["retryable"] is True
    validator("BackupJobResult").validate(out["result"])


def test_missing_restic_binary_is_a_non_retryable_failure(tmp_path, monkeypatch):
    monkeypatch.setenv("PATH", str(tmp_path))
    out = backup_job.run(clock=CLOCK, inp=_inp(tmp_path, 1, "backup", data=tmp_path))
    assert out["exit_code"] == 1 and out["result"]["error"]["retryable"] is False


def test_input_schema_rejects_bad_input():
    with pytest.raises(Exception):
        backup_job.run(clock=CLOCK, inp={"mode": "sync", "data_dir": "data", "exclude": [], "repository": "", "password_file": "pw"})


def test_missing_tools_make_pytest_exit_77_not_0(tmp_path):
    """도구가 없을 때 건너뜀이 통과(0)로 보이지 않는다. PATH 에서 restic 을 뺀 하위 pytest 가 왕복 시험만 골라 돌리면 종료 코드 77 이다."""
    import os, sys
    env = {k: v for k, v in os.environ.items() if k != "PATH"}
    env["PATH"] = str(tmp_path)                                     # 빈 폴더: restic·restic-rest-server 가 없다
    r = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", str(Path(__file__)), "-k", "round_trip_with_mutations"],
                       env=env, cwd=str(ROOT), capture_output=True, text=True, timeout=HANG_GUARD_SECONDS)
    assert r.returncode == 77, r.stdout[-400:]
    assert "SKIP(77)" in r.stdout


@needs_tools
def test_forget_keeps_policy_and_restore_still_works(tmp_path, rest_server):
    """보존·정리(ADR 0025): 같은 날 여러 번 백업하면 중간 스냅숏이 지워지고 최신은 남으며, 정리 뒤에도 복구된다."""
    data = tmp_path / "data"; data.mkdir(); _populate(data)
    ids = []
    for i in range(3):
        (data / "ds-b" / "x.bin").write_bytes(b"gen%d" % i)
        out = backup_job.run(clock=CLOCK, inp=_inp(tmp_path, rest_server, "backup", data=data))
        assert out["exit_code"] == 0
        ids.append(out["result"]["snapshot_id"])
    env = {"PATH": os.environ["PATH"], "RESTIC_REPOSITORY": f"rest:http://127.0.0.1:{rest_server}/area", "RESTIC_PASSWORD_FILE": str(tmp_path / "pw")}
    listed = json.loads(subprocess.run(["restic", "snapshots", "--json", "--no-cache"], env=env, capture_output=True, text=True, check=True, timeout=HANG_GUARD_SECONDS).stdout)
    left = [s["id"] for s in listed]
    # 같은 날 안의 중간 스냅숏은 지워지고(restic 이 기간마다 하나씩만 남기는 규칙), 최신은 남는다. 정확히 몇 개가 남는지는 restic 의 규칙이라 단정하지 않는다
    assert any(i.startswith(ids[-1][:8]) for i in left) and not any(i.startswith(ids[1][:8]) for i in left) and len(left) < len(ids)
    (data / "ds-b" / "x.bin").write_bytes(b"broken")
    assert backup_job.run(clock=CLOCK, inp=_inp(tmp_path, rest_server, "restore", data=data))["exit_code"] == 0
    assert (data / "ds-b" / "x.bin").read_bytes() == b"gen2"


def test_backup_runs_forget_with_the_documented_policy(tmp_path, monkeypatch):
    """도구 없이도 본다: 백업이 성공하면 forget 을 정해 둔 값으로 부르고, forget 이 실패하면 잡이 실패다(75)."""
    calls = []
    def fake(args, env, timeout=None):
        calls.append(args)
        if args[0] == "backup":
            return 0, '{"message_type":"summary","snapshot_id":"abc12345","total_bytes_processed":7}\n'
        return (1 if args[0] == "forget" and fail else 0), ""
    monkeypatch.setattr(backup_job, "_restic", fake)
    for fail, code in ((False, 0), (True, 75)):
        calls.clear()
        out = backup_job.run(clock=CLOCK, inp=_inp(tmp_path, 1, "backup", data=tmp_path))
        assert out["exit_code"] == code
        f = [c for c in calls if c[0] == "forget"][0]
        assert f[f.index("--keep-daily") + 1] == "7" and f[f.index("--keep-weekly") + 1] == "4" and f[f.index("--keep-monthly") + 1] == "6" and "--prune" in f
