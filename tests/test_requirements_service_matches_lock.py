"""이미지용 고정 파일(requirements-service.txt)의 판이 requirements.lock 과 같다.
둘이 어긋나 계약 3.4.19(jsonschema>=4.18)와 충돌한 jsonschema==4.10.3 이 이미지 빌드를 깨뜨렸다(2026-11-06)."""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _pins(path):
    out = {}
    for line in (ROOT / path).read_text(encoding="utf-8").splitlines():
        m = re.match(r"^([A-Za-z0-9_.\-]+)==([^\s#]+)", line.strip())
        if m:
            out[m.group(1).lower().replace("_", "-")] = m.group(2)
    return out


def test_service_pins_equal_lock_pins():
    lock, svc = _pins("requirements.lock"), _pins("requirements-service.txt")
    assert {k: (v, lock.get(k)) for k, v in svc.items() if lock.get(k) != v} == {}
