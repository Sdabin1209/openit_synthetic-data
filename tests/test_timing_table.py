"""시험 중 실제 시간을 기다리거나 재서 판정하는 곳이 0이다(U422, tests/TIMING.md). 컴포넌트가 시간을 직접 읽지 않는다(시계 주입, ADR 0023)."""
import re
from pathlib import Path

T = Path(__file__).resolve().parent
PKG = T.parent / "synthetic_data"


def test_tests_use_no_real_time_and_only_the_hang_guard_for_timeouts():
    bad = []
    for p in sorted(T.glob("*.py")):
        if p.name == Path(__file__).name:
            continue
        for n, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1):
            code = line.split("#", 1)[0]
            if re.search(r"time\.(sleep|monotonic|perf_counter|time)\(|\bsleep\(", code) or re.search(r"((?<!channel_)timeout=|settimeout\(|\.wait\(|\.join\()\s*\d", code):
                bad.append(f"{p.name}:{n}")
    assert not bad, bad


def test_components_do_not_read_the_clock():
    bad = [p.name for p in sorted((PKG / "components").glob("*.py")) if re.search(r"^\s*import time\b|\btime\.(monotonic|time|sleep|perf_counter)\(", p.read_text(encoding="utf-8"), re.M)]
    assert not bad, bad
