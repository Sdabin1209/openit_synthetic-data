"""scripts/docker-env.sh(docker_env_setup)의 시험: (1) 호출자가 준 DOCKER_CONFIG 는 그대로, (2) 안 주면 리포 안 빈 설정, (3) 망가진 사용자 전역 설정을 거치지 않는다 + 변이.
실제 docker 를 부른다. 사용자 ~/.docker 는 건드리지 않고 HOME 을 임시 폴더로 바꿔 망가진 전역 설정을 흉내 낸다."""
from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

from conftest import HANG_GUARD_SECONDS

ROOT = Path(__file__).resolve().parent.parent
BROKEN = json.dumps({"credsStore": "nonexistent-helper-xyz"})      # 없는 자격 도우미: 부르는 순간 "error getting credentials"


def _env(tmp: Path, **extra) -> dict:
    home = tmp / "home"; (home / ".docker").mkdir(parents=True, exist_ok=True)
    (home / ".docker" / "config.json").write_text(BROKEN)
    e = {k: v for k, v in os.environ.items() if k not in ("DOCKER_CONFIG", "DOCKER_HOST")}
    e["HOME"] = str(home)
    e.update(extra)
    return e


def _sh(script: str, env: dict) -> subprocess.CompletedProcess:
    return subprocess.run(["sh", "-c", f'cd "{ROOT}" && . scripts/docker-env.sh && docker_env_setup && {script}'], env=env, capture_output=True, text=True, timeout=HANG_GUARD_SECONDS)


def _ctx(tmp: Path) -> Path:
    c = tmp / "ctx"; c.mkdir(exist_ok=True)
    (c / "Dockerfile").write_text("# syntax=docker/dockerfile:1\nFROM scratch\nLABEL io.openit.test=docker-env\n")      # syntax 줄: 프런트엔드 이미지를 레지스트리에서 풀어 자격 도우미를 부르는 경로
    return c


def test_given_docker_config_is_kept(tmp_path):
    r = _sh('printf %s "$DOCKER_CONFIG"', _env(tmp_path, DOCKER_CONFIG=str(tmp_path / "given")))
    assert r.returncode == 0 and r.stdout == str(tmp_path / "given")


def test_without_it_the_repo_empty_config_is_used_not_user_home(tmp_path):
    r = _sh('printf %s "$DOCKER_CONFIG"', _env(tmp_path))
    assert r.returncode == 0 and r.stdout == str(ROOT / "build" / "docker-config")
    assert json.loads((ROOT / "build" / "docker-config" / "config.json").read_text()) == {}
    assert str(tmp_path / "home") not in r.stdout


def test_broken_user_global_config_is_not_used_so_docker_build_succeeds(tmp_path):
    tag = f"sd-docker-env-test-{os.getpid()}"
    try:
        r = _sh(f'docker build -q --no-cache -t {tag} "{_ctx(tmp_path)}"', _env(tmp_path))
        assert r.returncode == 0, r.stderr[-300:]
    finally:
        subprocess.run(["sh", "-c", f'cd "{ROOT}" && . scripts/docker-env.sh && docker_env_setup && docker rmi -f {tag}'], env=_env(tmp_path), capture_output=True, timeout=HANG_GUARD_SECONDS)


def test_mutation_without_the_setup_the_same_build_fails_on_credentials(tmp_path):
    r = subprocess.run(["docker", "build", "-q", "--no-cache", "-t", f"sd-docker-env-mut-{os.getpid()}", str(_ctx(tmp_path))], env=_env(tmp_path), capture_output=True, text=True, timeout=HANG_GUARD_SECONDS)
    assert r.returncode != 0 and "credentials" in r.stderr
