"""데이터셋 저장소 컴포넌트(바깥 자원: 디스크·메모리). I2 DatasetStore의 파일 구현과 메모리 구현이 같은 게시 검증 규칙을 쓴다(한 파일에 둔 이유:
컴포넌트끼리 import하지 않으므로 공통 규칙은 한 컴포넌트 안에 있어야 한다). 표면은 입력 스키마 -> 출력 스키마인 작업 넷이다:
  publish(PublishRequest) -> DatasetManifest, get_manifest(ManifestRequest) -> DatasetManifest, list_versions(VersionsRequest) -> 버전 목록, open_file(FileRequest) -> 파일 바이트.
저장소가 이웃(HTTP)이면 같은 표면을 link_dataset_publish가 낸다. wiring이 어느 쪽을 주입할지 정한다.

DatasetStore 구현의 공통 부분. 게시 검증 규칙은 한 곳(여기)에만 둬서 파일 구현과 메모리 구현이 같게 동작한다.

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
import os
import shutil
import tempfile
from pathlib import Path, PurePosixPath
from typing import BinaryIO, Mapping, Optional

from boundary_contracts import PIPELINE_SCHEMA_VERSION, canonical
from boundary_contracts.errors import BoundaryError

from ..types.schema_registry import check, contract_codes

SUPPORTED_PIPELINE_MAJOR = int(PIPELINE_SCHEMA_VERSION.split(".")[0])
# 왜 계약에서 읽나: 숫자를 적어 두면 계약 MAJOR가 오를 때 저장소가 새 레코드를 거부한다(3.0.0 전환에서 겪음). 지원하는 MAJOR는 설치된 계약의 것이다
_SAMPLE_SCHEMA = {"LORA_A": "ActionExtractionSample", "LORA_B": "ResponseSample"}


def _inv(msg: str, **details) -> BoundaryError:
    return BoundaryError("INVALID_RECORD", msg, details)


def _contract(name: str, record, what: str) -> None:
    errs = contract_codes(name, record)
    if errs:
        raise BoundaryError("INVALID_RECORD", f"{what}이(가) {name} 스키마를 위반한다: {errs[0]}", {"errors": errs[:10]})


def _ref_key(ref: Mapping) -> tuple:
    return (ref["id"], ref["version"], ref["content_hash"])


def _major(version: str) -> int:
    return int(str(version).split(".")[0])


class DatasetStoreBase:
    """하위 클래스는 저장 방식(_load_manifest, _commit, _list_versions, _open)만 구현한다."""

    def __init__(self, survey_contract_version: int):
        self.survey_contract_version = survey_contract_version     # 문진 스키마 정수 버전(D14). 파일 위치는 wiring이 읽어 넘긴다

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
        check("ManifestRequest", {"dataset_id": dataset_id, "version": version})
        m = self._load_manifest(dataset_id, version)
        if m is None:
            raise BoundaryError("NOT_FOUND", f"데이터셋이 없다: {dataset_id}@{version}")
        if canonical.content_hash(m) != m.get("content_hash"):
            raise BoundaryError("INTEGRITY_ERROR", f"저장된 매니페스트의 해시가 맞지 않는다: {dataset_id}@{version}")
        return copy.deepcopy(m)

    def list_versions(self, dataset_id: str) -> list[str]:
        check("VersionsRequest", {"dataset_id": dataset_id})
        return list(self._list_versions(dataset_id))

    def open_file(self, dataset_id: str, version: str, path: str) -> BinaryIO:
        check("FileRequest", {"dataset_id": dataset_id, "version": version, "path": path})
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
        check("PublishRequest", {"manifest": manifest, "files": {p: str(f) for p, f in files.items()}})     # ID·경로 형식은 스키마가 거부한다(INVALID_RECORD)
        _contract("DatasetManifest", manifest, "매니페스트")
        if _major(manifest["pipeline_schema_version"]) != SUPPORTED_PIPELINE_MAJOR:
            raise BoundaryError("UNSUPPORTED_VERSION", f"지원하지 않는 pipeline_schema_version: {manifest['pipeline_schema_version']}")
        did, ver = manifest["dataset_id"], manifest["version"]
        if canonical.content_hash(manifest) != manifest["content_hash"]:
            raise BoundaryError("INTEGRITY_ERROR", "매니페스트의 content_hash가 내용과 맞지 않는다")
        existing = self._load_manifest(did, ver)
        if existing is not None:
            if existing["content_hash"] == manifest["content_hash"]:
                return copy.deepcopy(existing)
            raise BoundaryError("CONFLICT", f"같은 (dataset_id, version)에 다른 내용이다: {did}@{ver}")

        if manifest["runtime_contract_version"] != self.survey_contract_version:
            raise BoundaryError("UNSUPPORTED_VERSION",
                                f"문진 스키마 버전 불일치: 매니페스트 {manifest['runtime_contract_version']}, 지원 {self.survey_contract_version}")
        entries = manifest["files"]
        paths = [f["path"] for f in entries]
        if len(set(paths)) != len(paths):
            raise _inv("files[].path가 중복된다")
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
        role, split, p = f["role"], f["split"], f["path"]
        n = 0
        with open(path, "rb") as fh:
            for lineno, raw in enumerate(fh, 1):
                line = raw.rstrip(b"\n")
                if not line.strip():
                    raise _inv(f"{p}:{lineno}: 빈 줄")
                try:
                    rec = json.loads(line.decode("utf-8"))
                except UnicodeDecodeError:
                    raise _inv(f"{p}:{lineno}: UTF-8이 아니다") from None      # 왜: 예외 문구에는 문제의 바이트 값이 들어간다. 값은 오류에 싣지 않는다(ADR 0003)
                except json.JSONDecodeError as e:
                    raise _inv(f"{p}:{lineno}: JSON이 아니다({e.msg})") from None
                where = f"{p}:{lineno}"
                _contract(_SAMPLE_SCHEMA[role], rec, where)
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


def _fsync(path: Path) -> None:
    # 왜: 데이터가 저장 장치에 닿기 전에 rename만 내구해지면 정전 뒤 '게시됨'인데 내용이 빈 버전이 남을 수 있다. 임시 파일 쓰기 -> 파일 fsync ->
    #     rename -> 디렉터리 fsync가 POSIX의 원자적 교체 관행이다(fsync(2), ADR 0008 보강). 디렉터리는 O_RDONLY로 열어 fsync한다.
    fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _fsync_tree(top: Path) -> None:
    for dirpath, _dirs, names in os.walk(top, topdown=False):
        for n in names:
            _fsync(Path(dirpath) / n)
        _fsync(Path(dirpath))


class FileDatasetStore(DatasetStoreBase):
    def __init__(self, root: Path, survey_contract_version: int):
        super().__init__(survey_contract_version)
        self.root = Path(root)
        try:
            self.root.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            raise BoundaryError("UNAVAILABLE", f"저장소 디렉터리를 만들 수 없다: {e}") from e

    def _vdir(self, did: str, ver: str) -> Path:
        return self.root / did / ver

    def _load_manifest(self, dataset_id, version) -> Optional[dict]:
        p = self._vdir(dataset_id, version) / "manifest.json"
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return None
        except (OSError, json.JSONDecodeError) as e:
            raise BoundaryError("INTEGRITY_ERROR", f"매니페스트를 읽을 수 없다: {p}: {e}") from e

    def _commit(self, manifest: dict, staged_dir: Path) -> None:
        did, ver = manifest["dataset_id"], manifest["version"]
        ddir = self.root / did
        try:
            ddir.mkdir(parents=True, exist_ok=True)
            seqs = [self._seq(c) for c in ddir.iterdir() if c.is_dir() and not c.name.startswith(".tmp-")]
            tmp = Path(tempfile.mkdtemp(prefix=".tmp-", dir=ddir))
            try:
                shutil.copytree(staged_dir, tmp / "files")
                (tmp / "manifest.json").write_text(
                    json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
                (tmp / "meta.json").write_text(json.dumps({"seq": max(seqs, default=0) + 1}), encoding="utf-8")
                _fsync_tree(tmp)
                try:
                    os.rename(tmp, ddir / ver)
                except OSError:
                    # 동시에 같은 버전을 게시한 경우
                    again = self._load_manifest(did, ver)
                    if again is not None and again["content_hash"] == manifest["content_hash"]:
                        return
                    raise BoundaryError("CONFLICT", f"같은 (dataset_id, version)에 다른 내용이다: {did}@{ver}")
                # rename 뒤 fsync 실패를 동시 게시 충돌로 오인하지 않도록 위 try 밖에 둔다
                _fsync(ddir)
                _fsync(self.root)     # 새 데이터셋 디렉터리의 항목도 내구하게 한다
            finally:
                shutil.rmtree(tmp, ignore_errors=True)
        except OSError as e:
            raise BoundaryError("UNAVAILABLE", f"저장 실패: {e}") from e

    @staticmethod
    def _seq(vdir: Path) -> int:
        try:
            return int(json.loads((vdir / "meta.json").read_text())["seq"])
        except (OSError, ValueError, KeyError):
            return 0

    def _list_versions(self, dataset_id) -> list[str]:
        ddir = self.root / dataset_id
        if not ddir.is_dir():
            return []
        dirs = [c for c in ddir.iterdir() if c.is_dir() and not c.name.startswith(".tmp-") and (c / "manifest.json").exists()]
        return [c.name for c in sorted(dirs, key=lambda c: (self._seq(c), c.name))]

    def _open(self, dataset_id, version, path) -> BinaryIO:
        try:
            return open(self._vdir(dataset_id, version) / "files" / path, "rb")
        except FileNotFoundError as e:
            raise BoundaryError("INTEGRITY_ERROR", f"매니페스트에 있는 파일이 저장소에 없다: {path}") from e
        except OSError as e:
            raise BoundaryError("UNAVAILABLE", str(e)) from e


class MemoryDatasetStore(DatasetStoreBase):
    def __init__(self, survey_contract_version: int):
        super().__init__(survey_contract_version)
        self._manifests: dict[tuple[str, str], dict] = {}
        self._blobs: dict[tuple[str, str, str], bytes] = {}
        self._order: dict[str, list[str]] = {}

    def _load_manifest(self, dataset_id, version) -> Optional[dict]:
        return self._manifests.get((dataset_id, version))

    def _commit(self, manifest: dict, staged_dir: Path) -> None:
        did, ver = manifest["dataset_id"], manifest["version"]
        for f in manifest["files"]:
            self._blobs[(did, ver, f["path"])] = (staged_dir / f["path"]).read_bytes()
        self._manifests[(did, ver)] = copy.deepcopy(manifest)
        self._order.setdefault(did, []).append(ver)

    def _list_versions(self, dataset_id) -> list[str]:
        return self._order.get(dataset_id, [])

    def _open(self, dataset_id, version, path) -> BinaryIO:
        return io.BytesIO(self._blobs[(dataset_id, version, path)])

    # 시험용: 저장된 바이트를 훼손해 무결성 검사를 확인한다.
    def _corrupt_for_test(self, dataset_id: str, version: str, path: str) -> None:
        k = (dataset_id, version, path)
        self._blobs[k] = self._blobs[k] + b"x"
