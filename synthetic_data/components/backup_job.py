"""dataset-store 데이터의 백업·복구 한 번. BackupJobInput -> BackupJobOutput(계약 BackupJobResult + 종료 코드).
restic(RUNTIME R10.1 의 restic REST 서버 프로토콜)을 부른다. 비밀 값은 자식 프로세스 환경에만 두고 결과·로그에 싣지 않는다(restic 의 stderr 는 주소·자격이 섞일 수 있어 버린다).
종료 코드(계약 BackupJobResult): 0 = ok, 75 = 재시도 가능(저장소에 닿지 못함·잠금), 1 = 그 밖의 실패."""
from __future__ import annotations

import json
import os
import subprocess
import tempfile
from typing import Callable
from pathlib import Path

from ..types.schema_registry import check, check_contract

# restic 종료 코드(restic 문서 "Exit codes"): 3 = 스냅숏은 만들었으나 일부 파일을 읽지 못함, 10 = 저장소 없음, 11 = 잠금 실패, 12 = 암호 틀림
_REPO_MISSING, _LOCK, _WRONG_PASSWORD, _INCOMPLETE = 10, 11, 12, 3
# 왜 저장소 확인에만 시간 상한을 두나: restic 은 저장소에 닿지 못하면 내부에서 약 15분 동안 다시 시도하고(restic 0.18 에는 이 횟수를 줄이는 옵션이 없다),
# 그동안 아무것도 내지 않아 deploy 가 시간 상한(잡 선언 timeout_seconds)으로 멈추면 재시도 가능(75)이 아니라 시간 초과 실패로 보인다. 그래서 첫 확인(`cat config`, 저장소 설정 한 개만 읽는다)에
# 상한을 두고, 넘기면 닿지 못한 것으로 보아 75 를 낸다. 30초는 측정하지 않은 시작값이다(게이트웨이 CONNECT 와 TLS 가 정상이면 수 초 안에 끝난다는 가정, 측정 안 함, ADR 0025).
PROBE_TIMEOUT_SECONDS = 30
# 왜 나머지 단계에 시간 상한이 없나: 잡 한 번의 상한은 잡 선언의 timeout_seconds 가 정본이고 deploy 가 멈춘다(R9.2). 여기서 따로 정하지 않는다.


class _Fail(Exception):
    def __init__(self, code: str, message: str, retryable: bool):
        super().__init__(message)
        self.code, self.retryable = code, retryable


def _env(inp: dict, cache_dir: str) -> dict:
    env = {k: os.environ[k] for k in ("PATH", "SSL_CERT_FILE", "TMPDIR") if k in os.environ}    # 왜 SSL_CERT_FILE: 신뢰 루트는 표준 환경 변수로 배포가 준다(RUNTIME IN-ROOT)
    env.update(RESTIC_REPOSITORY=inp["repository"], RESTIC_PASSWORD_FILE=inp["password_file"], RESTIC_CACHE_DIR=cache_dir)
    if inp.get("rest_user"):
        env["RESTIC_REST_USERNAME"], env["RESTIC_REST_PASSWORD"] = inp["rest_user"], inp.get("rest_password") or ""
    if inp.get("proxy"):
        env["HTTPS_PROXY"] = inp["proxy"]    # 왜: 영역 밖 호출은 자기 게이트웨이의 CONNECT 터널로만 나간다(R1.8). Go 표준 HTTP 전송이 읽는다
    return env


def _restic(args: list[str], env: dict, timeout: float | None = None) -> tuple[int, str]:
    try:
        p = subprocess.run(["restic", *args], env=env, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, check=False, timeout=timeout)
    except subprocess.TimeoutExpired as e:
        raise _Fail("UNAVAILABLE", "백업 저장소에 닿지 못했다(시간 안에 응답 없음)", True) from e
    except FileNotFoundError as e:
        raise _Fail("FAILED_PRECONDITION", "restic 실행 파일이 없다", False) from e
    return p.returncode, p.stdout


def _failure_for(rc: int, what: str) -> _Fail:
    if rc == _WRONG_PASSWORD:
        return _Fail("PERMISSION_DENIED", f"{what}: 저장소 암호가 맞지 않는다", False)
    # 그 밖(연결 실패·잠금·일부 파일 읽기 실패)은 다시 하면 풀릴 수 있다. 같은 잡은 멱등이라 다음 주기에 다시 한다(R10.12)
    return _Fail("UNAVAILABLE", f"{what}: 백업 저장소 또는 데이터 읽기가 실패했다(restic 종료 {rc})", True)


def _summary(out: str) -> dict:
    for line in reversed(out.splitlines()):
        try:
            d = json.loads(line)
        except ValueError:
            continue
        if isinstance(d, dict) and d.get("message_type") == "summary":
            return d
    raise _Fail("INTEGRITY_ERROR", "restic 결과에서 요약을 읽지 못했다", False)


def _backup(inp: dict, env: dict) -> tuple[str, int]:
    rc, _ = _restic(["cat", "config"], env, PROBE_TIMEOUT_SECONDS)
    if rc == _REPO_MISSING:
        rc, _ = _restic(["init"], env)              # 왜 여기서 만드나: 첫 백업이 저장소를 만든다. 이 잡이 멱등이라 이미 있으면 건너뛴다
        if rc != 0:
            raise _failure_for(rc, "저장소 만들기")
    elif rc != 0:
        raise _failure_for(rc, "저장소 확인")
    d = inp["data_dir"].rstrip("/")
    args = ["backup", "--json", "--no-cache", "--tag", "dataset-store", *sum((["--exclude", f"{d}/{n}"] for n in inp["exclude"]), []), d]
    rc, out = _restic(args, env)
    if rc != 0:
        raise _failure_for(rc, "백업")
    s = _summary(out)
    return s["snapshot_id"], int(s.get("total_bytes_processed", 0))


def _restore(inp: dict, env: dict) -> tuple[str, int]:
    d = inp["data_dir"].rstrip("/")
    rc, out = _restic(["snapshots", "--json", "--no-cache", "--latest", "1", "--path", d], env, PROBE_TIMEOUT_SECONDS)
    if rc == _REPO_MISSING:
        raise _Fail("NOT_FOUND", "복구할 백업 저장소가 없다", False)
    if rc != 0:
        raise _failure_for(rc, "스냅숏 조회")
    snaps = json.loads(out or "[]")
    if not snaps:
        raise _Fail("NOT_FOUND", "복구할 스냅숏이 없다", False)
    sid = snaps[-1]["id"]
    # 왜 --target /: 스냅숏은 절대 경로(/data/…)로 담겨 있어 루트에 풀면 원래 자리로 돌아간다. 백업에 없던 파일은 지우지 않는다(복구가 데이터를 더 잃지 않게)
    rc, out = _restic(["restore", sid, "--json", "--no-cache", "--target", "/"], env)
    if rc != 0:
        raise _failure_for(rc, "복구")
    return sid, int(_summary(out).get("total_bytes", 0))


def run(inp: dict, *, clock: Callable[[], str]) -> dict:
    """clock: 지금 시각(UTC, Z 로 끝나는 문자열)을 돌려주는 주입된 시계(ADR 0023: 컴포넌트가 시간을 직접 읽지 않는다)."""
    check("BackupJobInput", inp)
    started = clock()
    try:
        with tempfile.TemporaryDirectory() as cache:
            sid, nbytes = (_backup if inp["mode"] == "backup" else _restore)(inp, _env(inp, cache))
        res = {"status": "ok", "snapshot_id": sid, "bytes": nbytes, "started_at": started, "finished_at": clock()}
        code = 0
    except _Fail as f:
        res = {"status": "failed", "snapshot_id": None, "bytes": 0, "started_at": started, "finished_at": clock(),
               "error": {"code": f.code, "message": str(f), "retryable": f.retryable}}
        code = 75 if f.retryable else 1
    check_contract("BackupJobResult", res)                      # 왜: deploy 가 읽는 형식이라 내보내기 전에 계약으로 자기 검사한다(D107)
    out = {"result": res, "exit_code": code}
    check("BackupJobOutput", out)
    return out
