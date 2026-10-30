"""문진 스키마 디렉터리 쪽 연결: 정수 버전(CONTRACT_VERSION)과 문진 스키마 검사 함수를 컴포넌트에 넘긴다(주입)."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional

import jsonschema
from boundary_contracts.errors import BoundaryError


class Survey:
    """survey_schema_dir: 문진 스키마 디렉터리(CONTRACT_VERSION과 schemas/가 있는 곳)."""

    def __init__(self, survey_schema_dir: Optional[Path] = None):
        self.dir = Path(survey_schema_dir) if survey_schema_dir else None
        self._cache: dict[str, Any] = {}

    @property
    def contract_version(self) -> int:
        if self.dir is None:
            raise BoundaryError("FAILED_PRECONDITION", "문진 스키마 디렉터리가 설정되지 않았다")
        try:
            return int((self.dir / "CONTRACT_VERSION").read_text().strip())
        except (OSError, ValueError) as e:
            raise BoundaryError("UNSUPPORTED_VERSION", f"문진 스키마 CONTRACT_VERSION을 읽을 수 없다: {e}") from e

    def check(self, name: str, record: Any) -> list[str]:
        """위반을 '<경로>#<스키마 키워드>' 코드로(값은 담지 않는다, ADR 0003)."""
        if name not in self._cache:
            if self.dir is None:
                raise BoundaryError("FAILED_PRECONDITION", "문진 스키마 디렉터리가 설정되지 않았다")
            path = self.dir / "schemas" / f"{name}.json"
            if not path.exists():
                raise BoundaryError("UNSUPPORTED_VERSION", f"문진 스키마가 없다: {name}")
            schema = json.loads(path.read_text(encoding="utf-8"))
            schema.pop("$id", None)   # 상대 $id("standalone/...")가 '#/$defs' 참조 해석을 깨뜨린다
            self._cache[name] = jsonschema.Draft202012Validator(schema)
        return ["/".join(map(str, e.absolute_path)) + "#" + e.validator if e.absolute_path else "(루트)#" + e.validator
                for e in sorted(self._cache[name].iter_errors(record), key=lambda e: list(map(str, e.absolute_path)))]
