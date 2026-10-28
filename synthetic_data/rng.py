"""재현 가능한 난수. 전역 random과 시각을 쓰지 않고 (시드, 용도 문자열)에서 파생한다."""
from __future__ import annotations

from boundary_contracts import canonical


def derive_int(*parts) -> int:
    return int(canonical.sha256_hash(list(parts))[7:23], 16)


def short_hash(*parts, n: int = 16) -> str:
    return canonical.sha256_hash(list(parts))[7:7 + n]
