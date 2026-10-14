"""DatasetStore 메모리 구현. 오류·멱등성·해시 검증이 파일 구현과 같다."""
from __future__ import annotations

import copy
import io
from pathlib import Path
from typing import BinaryIO, Optional

from .base import DatasetStoreBase
from ..schemas import Validators


class MemoryDatasetStore(DatasetStoreBase):
    def __init__(self, validators: Validators):
        super().__init__(validators)
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
