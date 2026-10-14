"""DatasetStore 파일 구현.

배치: <root>/<dataset_id>/<version>/{manifest.json, meta.json, files/<path>}
게시는 root 아래 임시 디렉터리에 다 쓴 뒤 디렉터리 이름 바꾸기(rename)로 확정한다. 중간에 죽어도 반쯤 쓴 버전이 보이지 않는다.
meta.json의 seq는 게시 순서이고 list_versions가 그 순서(오래된 것부터)로 돌려준다.
"""
from __future__ import annotations

import json
import os
import shutil
import tempfile
from pathlib import Path
from typing import BinaryIO, Optional

from boundary_contracts.errors import BoundaryError

from .base import DatasetStoreBase
from ..schemas import Validators


class FileDatasetStore(DatasetStoreBase):
    def __init__(self, root: Path, validators: Validators):
        super().__init__(validators)
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
                try:
                    os.rename(tmp, ddir / ver)
                except OSError:
                    # 동시에 같은 버전을 게시한 경우
                    again = self._load_manifest(did, ver)
                    if again is not None and again["content_hash"] == manifest["content_hash"]:
                        return
                    raise BoundaryError("CONFLICT", f"같은 (dataset_id, version)에 다른 내용이다: {did}@{ver}")
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
