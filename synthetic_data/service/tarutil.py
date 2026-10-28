"""tar 스트림 묶기·풀기(HTTP.md 공통): 경로에 '..'·절대 경로·심볼릭 링크를 두지 않는다."""
from __future__ import annotations

import tarfile
from pathlib import Path

from boundary_contracts import BoundaryError


def pack(entries: dict[str, Path], out_path: Path) -> None:
    """entries: tar 안의 경로 -> 디스크 파일. 소유자·시각을 지워 같은 내용이면 같은 바이트가 되게 한다."""
    with tarfile.open(out_path, "w") as tf:
        for name in sorted(entries):
            info = tf.gettarinfo(str(entries[name]), arcname=name)
            info.uid = info.gid = 0
            info.uname = info.gname = ""
            info.mtime = 0
            with open(entries[name], "rb") as f:
                tf.addfile(info, f)


def _safe(name: str) -> bool:
    """정규형만 허용한다: './', '//', '..', 절대 경로, 역슬래시, 컴포넌트 255바이트 초과(파일 시스템 한계)는 거부한다.
    정규형이 아니면 'files/./x'와 'files/x'가 같은 파일로 겹쳐 쓴다."""
    if not name or name.startswith("/") or "\\" in name or "\x00" in name or name.endswith("/"):
        return False
    parts = name.split("/")
    return all(p not in ("", ".", "..") and len(p.encode("utf-8", "surrogateescape")) <= 255 for p in parts)


def unpack(tar_path: Path, dest: Path, *, max_bytes: int, max_entries: int = 1000) -> None:
    """일반 파일만 푼다(디렉터리 항목은 무시, sparse·링크·장치 거부). 합계가 max_bytes, 항목이 max_entries를 넘으면 푸는 도중에 멈춘다.
    tar는 압축하지 않으므로 선언 크기 = 실제 크기다. 항목 수 상한은 inode 고갈 방어다(ADR 0012)."""
    dest.mkdir(parents=True, exist_ok=True)
    total = n = 0
    seen: set[str] = set()
    try:
        with tarfile.open(tar_path, "r:") as tf:        # "r:"는 압축 없는 tar만(HTTP.md는 application/x-tar)
            for m in tf:
                if m.isdir():
                    continue
                if not m.isreg() or m.issparse() or not _safe(m.name):
                    raise BoundaryError("INVALID_RECORD", "tar에 허용되지 않는 항목이 있다")
                n += 1
                if n > max_entries:
                    raise BoundaryError("INVALID_RECORD", "tar의 항목이 너무 많다")
                if m.name in seen:
                    raise BoundaryError("INVALID_RECORD", "tar에 같은 경로가 두 번 있다")
                seen.add(m.name)
                total += m.size
                if total > max_bytes:
                    raise BoundaryError("INVALID_RECORD", "tar가 너무 크다")
                out = dest / m.name
                try:
                    out.parent.mkdir(parents=True, exist_ok=True)
                    with tf.extractfile(m) as src, open(out, "wb") as dst:
                        while chunk := src.read(1 << 20):
                            dst.write(chunk)
                except (FileExistsError, NotADirectoryError, IsADirectoryError):
                    raise BoundaryError("INVALID_RECORD", "tar의 경로가 서로 충돌한다") from None
                except OSError as e:
                    if e.errno == 36:      # ENAMETOOLONG
                        raise BoundaryError("INVALID_RECORD", "tar의 이름이 너무 길다") from None
                    raise BoundaryError("UNAVAILABLE", "저장 공간에 쓸 수 없다") from None
    except tarfile.TarError:
        raise BoundaryError("INVALID_RECORD", "tar를 읽을 수 없다") from None
