"""스키마 검증. 경계 계약 레코드는 boundary_contracts.validator(패키지에 든 스키마)로, 샘플의 input/expected는 문진 스키마로 따로 검증한다.
검증 실패는 BoundaryError(INVALID_RECORD)다."""
from __future__ import annotations

import json
import warnings
from pathlib import Path
from typing import Any, Optional

import boundary_contracts
import jsonschema
from boundary_contracts.errors import BoundaryError

warnings.filterwarnings("ignore", category=DeprecationWarning, module="jsonschema")


def _errors(validator, record) -> list[str]:
    out = []
    for e in sorted(validator.iter_errors(record), key=lambda e: list(map(str, e.absolute_path))):
        loc = "/".join(map(str, e.absolute_path)) or "(루트)"
        out.append(f"{loc}: {e.message[:200]}")
    return out


class Validators:
    """survey_schema_dir: 문진 스키마 디렉터리(CONTRACT_VERSION과 schemas/가 있는 곳)."""

    def __init__(self, survey_schema_dir: Optional[Path] = None):
        self.survey_dir = Path(survey_schema_dir) if survey_schema_dir else None
        self._cache: dict[tuple[str, str], Any] = {}

    @property
    def runtime_contract_version(self) -> int:
        if self.survey_dir is None:
            raise BoundaryError("FAILED_PRECONDITION", "문진 스키마 디렉터리가 설정되지 않았다")
        try:
            return int((self.survey_dir / "CONTRACT_VERSION").read_text().strip())
        except (OSError, ValueError) as e:
            raise BoundaryError("UNSUPPORTED_VERSION", f"문진 스키마 CONTRACT_VERSION을 읽을 수 없다: {e}") from e

    def _boundary(self, name: str):
        key = ("b", name)
        if key not in self._cache:
            try:
                self._cache[key] = boundary_contracts.validator(name)
            except KeyError as e:
                raise BoundaryError("UNSUPPORTED_VERSION", f"경계 계약 스키마가 없다: {name}") from e
        return self._cache[key]

    def _survey(self, name: str):
        key = ("s", name)
        if key not in self._cache:
            if self.survey_dir is None:
                raise BoundaryError("FAILED_PRECONDITION", "문진 스키마 디렉터리가 설정되지 않았다")
            path = self.survey_dir / "schemas" / f"{name}.json"
            if not path.exists():
                raise BoundaryError("UNSUPPORTED_VERSION", f"문진 스키마가 없다: {name}")
            schema = json.loads(path.read_text(encoding="utf-8"))
            schema.pop("$id", None)   # 상대 $id("standalone/...")가 '#/$defs' 참조 해석을 깨뜨린다
            self._cache[key] = jsonschema.Draft202012Validator(schema)
        return self._cache[key]

    def check_boundary(self, name: str, record: Any) -> list[str]:
        return _errors(self._boundary(name), record)

    def check_boundary_codes(self, name: str, record: Any) -> list[str]:
        """위반을 '<경로>#<스키마 키워드>' 코드로만 돌려준다. 메시지(입력 값이 섞임)와 값은 담지 않는다. 배열 번호는 *로 바꾼다."""
        import re
        out = set()
        for e in self._boundary(name).iter_errors(record):
            path = re.sub(r"/\d+", "/*", "/".join(map(str, e.absolute_path))) or "(루트)"
            out.add(f"{path}#{e.validator}")
        return sorted(out)

    def check_survey(self, name: str, record: Any) -> list[str]:
        return _errors(self._survey(name), record)

    def boundary(self, name: str, record: Any, *, what: str = "") -> None:
        errs = self.check_boundary(name, record)
        if errs:
            raise BoundaryError("INVALID_RECORD", f"{what or name}이(가) {name} 스키마를 위반한다: {errs[0]}", {"errors": errs[:10]})

    def survey(self, name: str, record: Any, *, what: str = "") -> None:
        errs = self.check_survey(name, record)
        if errs:
            raise BoundaryError("INVALID_RECORD", f"{what or name}이(가) 문진 스키마 {name}을 위반한다: {errs[0]}", {"errors": errs[:10]})
