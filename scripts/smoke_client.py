"""스모크: 실행 중인 dataset-store에 계약 클라이언트로 데이터셋 하나를 게시하고 읽는다. 사용: smoke_client.py URL 쓰기토큰 읽기토큰"""
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT), str(ROOT / "tests")]
from openit_link.clients import HttpDatasetStore    # noqa: E402
from conftest import build_v2_dataset, write_files        # noqa: E402

url, wt, rt = sys.argv[1:4]
with tempfile.TemporaryDirectory() as td:
    m, blobs = build_v2_dataset(Path(td) / "b")
    files = write_files(Path(td) / "src", blobs)
    w, r = HttpDatasetStore(url, wt), HttpDatasetStore(url, rt)
    assert w.publish(m, files) == m
    assert w.publish(m, files) == m                     # 멱등
    assert r.get_manifest(m["dataset_id"], m["version"]) == m
    out = r.download(m["dataset_id"], m["version"], dest=Path(td) / "dl")
    assert sorted(p.name for p in out.rglob("*") if p.is_file()) == sorted(Path(f["path"]).name for f in m["files"])
print("smoke_client OK", m["dataset_id"], m["version"])
