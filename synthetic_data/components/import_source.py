"""입력 디렉터리 읽기(바깥 자원: 디스크). ImportSourceRequest -> ImportSource.

입력 디렉터리에 lora_{a,b}_{train,val,test}.jsonl 6개가 있어야 한다. 역할과 분할은 파일 이름이 정한다(docs/adr/0002, 파일 이름은 V2_DRAFT 기록의 추정).
줄은 \\n으로 나누고 끝의 \\r을 떼며, UTF-8이 아닌 줄은 text를 null로 둔다(행 검증이 record_encoding으로 집계한다)."""
from __future__ import annotations

from pathlib import Path

from boundary_contracts import canonical

from ..types.schema_registry import check

# 왜: 매니페스트가 파일 단위로 분할을 요구하고 행의 split 값(실측: train/val/test, 파일 이름과 일치)이 파일 이름과 같은 정보라 파일 이름으로 정한다(docs/adr/0002).
SPLIT_OF_FILE = {"train": "TRAIN", "val": "VALIDATION", "test": "EVAL"}
ROLES = (("a", "LORA_A"), ("b", "LORA_B"))
INPUT_FILES = [(f"lora_{r}_{s}.jsonl", role, split) for r, role in ROLES for s, split in SPLIT_OF_FILE.items()]


class InputError(ValueError):
    """입력 디렉터리나 파일 문제(상태 조건이라 스키마로 쓸 수 없다)."""


def _text(raw: bytes):
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return None


def run(inp: dict) -> dict:
    check("ImportSourceRequest", inp)
    d = Path(inp["input_dir"])
    if not d.is_dir():
        raise InputError(f"입력 디렉터리가 없다: {d}")
    blobs, missing = {}, []
    for name, _, _ in INPUT_FILES:
        p = d / name
        if not p.is_file():
            missing.append(name)
            continue
        try:
            blobs[name] = p.read_bytes()
        except OSError as e:
            raise InputError(f"입력 파일을 읽을 수 없다: {p}: {e}") from e
    if missing:
        raise InputError(f"입력 파일이 없다: {', '.join(missing)} (필요: {', '.join(n for n, _, _ in INPUT_FILES)})")
    files = []
    for name, role, split in INPUT_FILES:
        data = blobs[name]
        lines = data.split(b"\n")
        if lines and lines[-1] == b"":
            lines.pop()
        files.append({"name": name, "role": role, "split": split, "sha256": canonical.file_hash(d / name),
                      "rows": [{"lineno": i, "text": _text(raw.rstrip(b"\r"))} for i, raw in enumerate(lines, 1)]})
    out = {"files": files}
    check("ImportSource", out)
    return out
