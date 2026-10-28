"""스모크의 비밀 누출 검사가 실제로 실패하는지 확인한다(검사가 늘 통과하는 형태였던 결함의 재발 방지)."""
import subprocess
from pathlib import Path

S = str(Path(__file__).resolve().parent.parent / "scripts" / "assert_no_secret.sh")


def run(text, *secrets):
    return subprocess.run(["sh", S, *secrets], input=text.encode(), capture_output=True)


def test_leak_fails():
    r = run("2026 INFO token=abc123secret ok\n", "abc123secret", "other")
    assert r.returncode == 1 and b"abc123secret" not in r.stderr + r.stdout


def test_clean_passes():
    assert run("INFO started\n", "abc123secret", "other").returncode == 0


def test_empty_secret_arg_is_error():
    assert run("x", "").returncode == 2
