"""게시 판정 한 곳. `run`과 `import`가 같은 함수를 쓴다(표준성 점검 A10).

왜 한 함수: 같은 (dataset_id, version)에 dataset_digest가 같으면 created_at이 달라도 '이미 게시됨'이다(계약 I2의 멱등 규칙, CR-005).
예전에는 import만 version을 지정했을 때도 이 판정을 했고 run은 version을 비웠을 때만 해서, 같은 입력 재실행의 결과가 두 경로에서 달랐다."""
from __future__ import annotations

from boundary_contracts.errors import BoundaryError

from .package import EXT


def publish_idempotent(store, manifest: dict, files: dict, digest: str) -> tuple[str, str]:
    """(status, content_hash). status는 PUBLISHED 또는 ALREADY_PUBLISHED. digest가 다르면 저장소가 CONFLICT를 낸다."""
    try:
        ex = store.get_manifest(manifest["dataset_id"], manifest["version"])
        if ex.get("ext", {}).get(EXT, {}).get("dataset_digest") == digest:
            return "ALREADY_PUBLISHED", ex["content_hash"]
    except BoundaryError as e:
        if e.code != "NOT_FOUND":
            raise
    return "PUBLISHED", store.publish(manifest, files)["content_hash"]
