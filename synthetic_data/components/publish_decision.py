"""게시 판정 한 곳. PublishDecisionInput -> PublishOutcome. `run`과 `import`가 같은 함수를 쓴다(표준성 점검 A10).

왜 한 함수: 같은 (dataset_id, version)에 dataset_digest가 같으면 created_at이 달라도 '이미 게시됨'이다(계약 I2의 멱등 규칙, CR-005).
저장소(파일·메모리·HTTP 클라이언트)는 wiring이 주입한다: 이 컴포넌트는 get_manifest와 publish(manifest, files)만 안다."""
from __future__ import annotations

from boundary_contracts.errors import BoundaryError

from ..types.schema_registry import check

EXT = "synthetic-data"


def run(inp: dict, *, store) -> dict:
    check("PublishDecisionInput", inp)
    m = inp["manifest"]
    try:
        ex = store.get_manifest(m["dataset_id"], m["version"])
        if ex.get("ext", {}).get(EXT, {}).get("dataset_digest") == inp["digest"]:
            out = {"status": "ALREADY_PUBLISHED", "content_hash": ex["content_hash"]}
            check("PublishOutcome", out)
            return out
    except BoundaryError as e:
        if e.code != "NOT_FOUND":
            raise
    out = {"status": "PUBLISHED", "content_hash": store.publish(m, inp["files"])["content_hash"]}   # digest가 다르면 저장소가 CONFLICT를 낸다
    check("PublishOutcome", out)
    return out
