"""DatasetStore 구현의 공통 부분. 게시 검증 규칙은 한 곳(여기)에만 둬서 파일 구현과 메모리 구현이 같게 동작한다.

게시(publish)가 검증하는 것(INTERFACES.md I2):
  - 매니페스트가 DatasetManifest 스키마를 통과하고 content_hash가 맞다(boundary_contracts.canonical).
  - 같은 (dataset_id, version)이 이미 있으면: 같은 content_hash면 기존 것을 돌려주고(멱등), 다르면 CONFLICT.
  - files의 키 집합 == manifest.files[].path 집합. 파일 해시, 줄 수(sample_count), 분할(split) 일치.
  - 줄마다 ActionExtractionSample(role=LORA_A)/ResponseSample(role=LORA_B) 스키마를 통과한다(input/expected는 그 스키마가 ActionExtraction*·ResponseRequest·ResponseText로 검증한다, 2.0.0).
  - 평가(EVAL) 샘플의 scenario_id가 TRAIN·VALIDATION과 겹치면 INVALID_RECORD(TRAIN과 VALIDATION끼리도 마찬가지).
"""
from __future__ import annotations

import copy
import io
import json
import re
import shutil
import tempfile
from pathlib import Path, PurePosixPath
from typing import BinaryIO, Mapping, Optional

from boundary_contracts import canonical
from boundary_contracts.errors import BoundaryError

from .. import SUPPORTED_PIPELINE_MAJOR
from ..schemas import Validators

_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]*$")
_SAMPLE_SCHEMA = {"LORA_A": "ActionExtractionSample", "LORA_B": "ResponseSample"}


def _inv(msg: str, **details) -> BoundaryError:
    return BoundaryError("INVALID_RECORD", msg, details)


def _ref_key(ref: Mapping) -> tuple:
    return (ref["id"], ref["version"], ref["content_hash"])


def _major(version: str) -> int:
    return int(str(version).split(".")[0])


class DatasetStoreBase:
    """하위 클래스는 저장 방식(_load, _put, _versions, _read)만 구현한다."""

    def __init__(self, validators: Validators):
        self.validators = validators

    # ---- 저장 방식 (하위 클래스) ----
    def _load_manifest(self, dataset_id: str, version: str) -> Optional[dict]:
        raise NotImplementedError

    def _commit(self, manifest: dict, staged_dir: Path) -> None:
        """staged_dir/<경로>의 파일들과 manifest를 원자적으로 저장한다."""
        raise NotImplementedError

    def _list_versions(self, dataset_id: str) -> list[str]:
        raise NotImplementedError

    def _open(self, dataset_id: str, version: str, path: str) -> BinaryIO:
        raise NotImplementedError

    # ---- I2 ----
    def get_manifest(self, dataset_id: str, version: str) -> dict:
        self._check_id(dataset_id, "dataset_id")
        self._check_id(version, "version")
        m = self._load_manifest(dataset_id, version)
        if m is None:
            raise BoundaryError("NOT_FOUND", f"데이터셋이 없다: {dataset_id}@{version}")
        if canonical.content_hash(m) != m.get("content_hash"):
            raise BoundaryError("INTEGRITY_ERROR", f"저장된 매니페스트의 해시가 맞지 않는다: {dataset_id}@{version}")
        return copy.deepcopy(m)

    def list_versions(self, dataset_id: str) -> list[str]:
        self._check_id(dataset_id, "dataset_id")
        return list(self._list_versions(dataset_id))

    def open_file(self, dataset_id: str, version: str, path: str) -> BinaryIO:
        m = self.get_manifest(dataset_id, version)
        entry = next((f for f in m["files"] if f["path"] == path), None)
        if entry is None:
            raise BoundaryError("NOT_FOUND", f"데이터셋에 그 파일이 없다: {path}")
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td) / "f"
            with self._open(dataset_id, version, path) as src, open(tmp, "wb") as dst:
                shutil.copyfileobj(src, dst)
            if canonical.file_hash(tmp) != entry["content_hash"]:
                raise BoundaryError("INTEGRITY_ERROR", f"파일 해시가 매니페스트와 다르다: {path}")
            return io.BytesIO(tmp.read_bytes())

    def publish(self, manifest: dict, files: Mapping[str, Path]) -> dict:
        v = self.validators
        v.boundary("DatasetManifest", manifest, what="매니페스트")
        if _major(manifest["pipeline_schema_version"]) != SUPPORTED_PIPELINE_MAJOR:
            raise BoundaryError("UNSUPPORTED_VERSION", f"지원하지 않는 pipeline_schema_version: {manifest['pipeline_schema_version']}")
        did, ver = manifest["dataset_id"], manifest["version"]
        self._check_id(ver, "version")
        if canonical.content_hash(manifest) != manifest["content_hash"]:
            raise BoundaryError("INTEGRITY_ERROR", "매니페스트의 content_hash가 내용과 맞지 않는다")
        existing = self._load_manifest(did, ver)
        if existing is not None:
            if existing["content_hash"] == manifest["content_hash"]:
                return copy.deepcopy(existing)
            raise BoundaryError("CONFLICT", f"같은 (dataset_id, version)에 다른 내용이다: {did}@{ver}")

        if manifest["runtime_contract_version"] != v.runtime_contract_version:
            raise BoundaryError("UNSUPPORTED_VERSION",
                                f"문진 스키마 버전 불일치: 매니페스트 {manifest['runtime_contract_version']}, 지원 {v.runtime_contract_version}")
        entries = manifest["files"]
        paths = [f["path"] for f in entries]
        if len(set(paths)) != len(paths):
            raise _inv("files[].path가 중복된다")
        for p in paths:
            self._check_path(p)
        if set(files) != set(paths):
            raise _inv("files의 키와 manifest.files[].path가 다르다",
                       missing=sorted(set(paths) - set(files)), extra=sorted(set(files) - set(paths)))
        manifest_qs = {_ref_key(r) for r in manifest["question_sets"]}
        seed_ids = set(manifest["seed_case_ids"])

        with tempfile.TemporaryDirectory(prefix="dsstage-") as td:
            staged = Path(td) / "files"
            staged.mkdir()
            for p in paths:   # 검증 대상과 저장 대상이 같은 바이트이도록 먼저 복사한다
                src = Path(files[p])
                if not src.is_file():
                    raise _inv(f"파일이 없다: {p}")
                dst = staged / PurePosixPath(p)
                dst.parent.mkdir(parents=True, exist_ok=True)
                try:
                    shutil.copyfile(src, dst)
                except OSError as e:
                    raise BoundaryError("UNAVAILABLE", f"파일을 읽을 수 없다: {p}: {e}") from e

            scenarios: dict[str, set[str]] = {"TRAIN": set(), "VALIDATION": set(), "EVAL": set()}
            sample_ids: set[str] = set()
            for f in entries:
                p = f["path"]
                path = staged / PurePosixPath(p)
                if canonical.file_hash(path) != f["content_hash"]:
                    raise BoundaryError("INTEGRITY_ERROR", f"파일 해시가 맞지 않는다: {p}")
                allowed = {_ref_key(r) for r in f.get("question_sets", manifest["question_sets"])}
                if not allowed <= manifest_qs:
                    raise _inv(f"{p}: files[].question_sets가 manifest.question_sets에 없는 문항 세트를 가리킨다")
                count = self._check_lines(f, path, manifest, allowed, seed_ids, sample_ids, scenarios)
                if count != f["sample_count"]:
                    raise _inv(f"{p}: sample_count {f['sample_count']} != 실제 줄 수 {count}")
            for a, b in (("EVAL", "TRAIN"), ("EVAL", "VALIDATION"), ("TRAIN", "VALIDATION")):
                both = scenarios[a] & scenarios[b]
                if both:
                    raise _inv(f"같은 scenario_id가 {a}와 {b}에 걸친다", scenario_ids=sorted(both)[:10])
            stored = copy.deepcopy(manifest)
            self._commit(stored, staged)
        return copy.deepcopy(stored)

    # ---- 내부 ----
    def _check_lines(self, f: dict, path: Path, manifest: dict, allowed: set, seed_ids: set,
                     sample_ids: set, scenarios: dict) -> int:
        v = self.validators
        role, split, p = f["role"], f["split"], f["path"]
        n = 0
        with open(path, "rb") as fh:
            for lineno, raw in enumerate(fh, 1):
                line = raw.rstrip(b"\n")
                if not line.strip():
                    raise _inv(f"{p}:{lineno}: 빈 줄")
                try:
                    rec = json.loads(line.decode("utf-8"))
                except (UnicodeDecodeError, json.JSONDecodeError) as e:
                    raise _inv(f"{p}:{lineno}: JSON이 아니다: {e}") from e
                where = f"{p}:{lineno}"
                v.boundary(_SAMPLE_SCHEMA[role], rec, what=where)
                if _major(rec["pipeline_schema_version"]) != SUPPORTED_PIPELINE_MAJOR:
                    raise BoundaryError("UNSUPPORTED_VERSION", f"{where}: 지원하지 않는 pipeline_schema_version")
                if rec["split"] != split:
                    raise _inv(f"{where}: 샘플 split {rec['split']} != 파일 split {split}")
                if "question_set" in rec and _ref_key(rec["question_set"]) not in allowed:
                    raise _inv(f"{where}: question_set이 이 파일의 문항 세트에 없다")
                if "seed_case_id" in rec and rec["seed_case_id"] not in seed_ids:
                    raise _inv(f"{where}: seed_case_id가 manifest.seed_case_ids에 없다")
                if rec["sample_id"] in sample_ids:
                    raise _inv(f"{where}: sample_id 중복: {rec['sample_id']}")
                sample_ids.add(rec["sample_id"])
                scenarios[split].add(rec["scenario_id"])
                n += 1
        return n

    @staticmethod
    def _check_id(value: str, what: str) -> None:
        if not isinstance(value, str) or not _ID_RE.match(value) or len(value) > 128:
            raise _inv(f"{what} 형식이 맞지 않는다: {value!r}")

    @staticmethod
    def _check_path(p: str) -> None:
        pp = PurePosixPath(p)
        if pp.is_absolute() or ".." in pp.parts or "\\" in p or str(pp) != p or p in ("", "."):
            raise _inv(f"안전하지 않은 파일 경로: {p!r}")
