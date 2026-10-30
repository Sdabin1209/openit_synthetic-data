"""패키징 결과(파일 본문)를 임시 폴더에 쓰고 멱등 게시 판정 컴포넌트에 넘긴다. run과 import가 같은 길을 쓴다."""
from __future__ import annotations

import tempfile
from pathlib import Path

from ..components import publish_decision


def publish(packaged: dict, store, work_dir: Path, prefix: str) -> dict:
    with tempfile.TemporaryDirectory(prefix=prefix, dir=work_dir) as td:
        staging = Path(td) / "files"
        paths = {}
        for f in packaged["files"]:
            p = staging / f["path"]
            p.parent.mkdir(parents=True, exist_ok=True)
            with open(p, "w", encoding="utf-8", newline="\n") as fh:
                fh.write(f["text"])
            paths[f["path"]] = str(p)
        return publish_decision.run({"manifest": packaged["manifest"], "digest": packaged["digest"], "files": paths}, store=store)
