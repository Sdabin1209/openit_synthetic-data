"""받는 쪽 통신: dataset-store 서버 면(I2, D100). HTTP.md `## I2`와 CONVENTIONS 9절을 따른다. 처리 함수는 저장소(주입)에 일을 시키고 응답을 만든다.

규약(401/403, X-Openit-User, 413, 요청·응답 계약 검증, BoundaryError 본문, /healthz, /readyz)은 openit_link.App/Route가 한다(D118). 여기는 경로 표와 처리 함수,
이 서버만의 방어(인증 실패 횟수 제한, 동시 게시·다운로드 상한, 디스크 여유, 같은 데이터셋 게시 직렬화, 종료 절차)를 맡는다. 서버 구현은 waitress(WSGI, ADR 0017, D111).

환경 변수는 읽지 않는다(wiring/service.py가 읽어 넘긴다). 로그는 표준 출력으로, 토큰과 본문은 남기지 않는다."""
from __future__ import annotations

import hmac
import re
import shutil
import tarfile
import tempfile
import threading
import time
from collections import defaultdict, deque
from contextlib import contextmanager
from pathlib import Path, PurePosixPath

from boundary_contracts import PIPELINE_SCHEMA_VERSION, BoundaryError, canonical
from openit_link import App, Request, Response, Route
from waitress import wasyncore
from waitress.server import create_server

from ..types.schema_registry import check

WRITE_ROLE = "synthetic-data"      # HTTP.md I2: 쓰기 역할은 synthetic-data 하나
MIN_TOKEN_LEN = 32                 # 128비트 이상 무작위 16진수(OWASP 세션 관리 치트시트·NIST SP 800-63B 참고, 원문은 다시 확인하지 않았다)


def parse_tokens(spec):
    """'역할=토큰,역할=토큰' -> {토큰: 역할}"""
    out = {}
    for part in (spec or "").split(","):
        part = part.strip()
        if not part:
            continue
        if "=" not in part:
            raise ValueError("토큰 설정은 역할=토큰 형식이어야 한다")
        role, tok = part.split("=", 1)
        if not role or not tok:
            raise ValueError("역할과 토큰은 비어 있을 수 없다")
        out[tok] = role
    return out


def check_token_strength(tokens, *, min_len=MIN_TOKEN_LEN):
    for tok, role in tokens.items():
        if len(tok) < min_len:
            raise ValueError(f"역할 {role}의 토큰이 {min_len}자 미만이다. `openssl rand -hex 32` 같은 무작위 값을 쓴다")
        if len(set(tok)) < 8:
            raise ValueError(f"역할 {role}의 토큰이 단조롭다. 무작위 값을 쓴다")


# ---- tar 스트림 묶기·풀기(HTTP.md 공통): 경로에 '..'·절대 경로·심볼릭 링크를 두지 않는다 ----
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


class Service:
    """서버의 상태와 방어. store는 DatasetStore 구현(파일)이고 wiring이 주입한다."""

    def __init__(self, store, root: Path, read_tokens: dict, write_tokens: dict, *, max_body: int = 1 << 30,
                 log=lambda s: print(s, flush=True),
                 max_publishes: int = 8, max_downloads: int = 8, max_entries: int = 1000,
                 auth_fail_limit: int = 10, auth_fail_window: float = 60.0,
                 min_free_gb: float = 1.0, free_bytes=None):
        for role in write_tokens.values():
            if role != WRITE_ROLE:
                raise ValueError(f"쓰기 역할은 {WRITE_ROLE}만 허용한다")
        if set(read_tokens) & set(write_tokens):
            raise ValueError("같은 토큰이 읽기와 쓰기 양쪽에 설정돼 있다. 역할마다 다른 토큰을 쓴다")
        self.root, self.read, self.write, self.max_body, self.log = Path(root), read_tokens, write_tokens, max_body, log
        self.store = store
        self.tmp = self.root / ".tmp"
        self.auth_fail_limit, self.auth_fail_window, self.min_free_gb = auth_fail_limit, auth_fail_window, min_free_gb
        self._free_bytes = free_bytes or (lambda: shutil.disk_usage(self.root).free)
        self.max_entries = max_entries
        self.publish_slots = threading.BoundedSemaphore(max(1, max_publishes))
        self.download_slots = threading.BoundedSemaphore(max(1, max_downloads))
        self._locks: dict[str, list] = {}         # dataset_id -> [Lock, 참조 수]
        self._fails = defaultdict(deque)
        self._mu = threading.Lock()
        shutil.rmtree(self.tmp, ignore_errors=True)       # 재시작 정리: 이전 실행이 남긴 요청 임시 폴더
        self.tmp.mkdir(parents=True, exist_ok=True)
        for leftover in self.store.root.glob("*/.tmp-*"):  # 게시 도중 죽은 잔해(저장소가 rename 전에 쓰던 폴더)
            shutil.rmtree(leftover, ignore_errors=True)

    def check_free_space(self, n: int) -> None:
        # 본문 tar(n) + 풀어 둔 사본(n) + 저장소의 스테이징 사본(n) = 최대 약 3n이 동시에 디스크에 있다. 측정 안 함(ADR 0012)
        if self._free_bytes() < 3 * n + int(self.min_free_gb * 2**30):
            self.log("경보: 디스크 여유 부족으로 게시 거절")
            raise BoundaryError("UNAVAILABLE", "저장소 여유 공간이 부족하다")

    def tokens(self) -> dict:
        """토큰 -> 역할. openit_link.App이 인증(401/403)을 맡는다. 같은 토큰이 양쪽에 없음은 생성자가 보증한다."""
        return {**self.read, **self.write}

    def roles(self) -> frozenset:
        return frozenset(self.tokens().values())

    def auth_blocked(self, addr: str) -> bool:
        now = time.monotonic()
        with self._mu:
            q = self._fails.get(addr)
            if q is None:
                return False
            while q and now - q[0] > self.auth_fail_window:
                q.popleft()
            if not q:
                del self._fails[addr]          # 창이 지나면 주소 항목을 비운다(메모리가 주소 수만큼 늘지 않는다)
                return False
            return len(q) >= self.auth_fail_limit

    def note_auth_failure(self, addr: str) -> None:
        with self._mu:
            q = self._fails[addr]
            if len(q) < self.auth_fail_limit:   # 차단 중에는 쌓지 않는다: deque 길이는 limit이 상한
                q.append(time.monotonic())

    def ready(self) -> tuple:
        try:
            self.store.root.stat()
            p = self.tmp / ".ready"
            p.write_text("1")
            p.unlink()
            return True, {"status": "ready"}
        except Exception:
            return False, {"status": "not-ready"}

    @contextmanager
    def dataset_lock(self, dataset_id: str):
        """같은 데이터셋의 게시를 직렬화한다(다른 데이터셋은 동시에). 같은 버전 동시 게시가 503이 아니라 200/409로 끝나게 하고,
        저장소가 버전 순번(seq)을 읽고 쓰는 구간의 경합도 막는다(ADR 0012)."""
        with self._mu:
            ent = self._locks.setdefault(dataset_id, [threading.Lock(), 0])
            ent[1] += 1
        try:
            with ent[0]:
                yield
        finally:
            with self._mu:
                ent[1] -= 1
                if ent[1] == 0:
                    self._locks.pop(dataset_id, None)

    def list_ids(self) -> list[str]:
        try:
            ids = sorted(c.name for c in self.store.root.iterdir() if c.is_dir() and not c.name.startswith("."))
            return [i for i in ids if self.store._list_versions(i)]      # 버전이 하나도 없는 디렉터리는 데이터셋이 아니다
        except OSError as e:
            raise BoundaryError("UNAVAILABLE", "저장소를 읽을 수 없다") from e

    def verified_file(self, did: str, ver: str, path: str) -> tuple[Path, int]:
        """manifest에 있는 파일의 디스크 경로와 크기. 해시를 청크로 확인한 뒤에만 돌려준다(메모리에 올리지 않는다)."""
        m = self.store.get_manifest(did, ver)
        entry = next((f for f in m["files"] if f["path"] == path), None)
        if entry is None:
            raise BoundaryError("NOT_FOUND", f"데이터셋에 그 파일이 없다: {path}")
        p = self.store._vdir(did, ver) / "files" / path
        try:
            if canonical.file_hash(p) != entry["content_hash"]:
                raise BoundaryError("INTEGRITY_ERROR", f"파일 해시가 매니페스트와 다르다: {path}")
            return p, p.stat().st_size
        except FileNotFoundError:
            raise BoundaryError("INTEGRITY_ERROR", f"매니페스트에 있는 파일이 저장소에 없다: {path}") from None
        except OSError:
            raise BoundaryError("UNAVAILABLE", "파일을 읽을 수 없다") from None

    def dataset_tar(self, did: str, ver: str, out: Path) -> None:
        m = self.store.get_manifest(did, ver)
        pack({f["path"]: self.verified_file(did, ver, f["path"])[0] for f in m["files"]}, out)


def _page(items: list, cursor, limit: int):
    start = 0
    if cursor is not None:
        if not cursor.isdigit():
            raise BoundaryError("INVALID_RECORD", "cursor가 올바르지 않다")
        start = int(cursor)
    chunk = items[start:start + limit]
    return {"items": chunk, "next_cursor": str(start + limit) if start + limit < len(items) else None}


def _limit(q) -> int:
    try:
        v = int(q.get("limit") or 100)
    except ValueError:
        raise BoundaryError("INVALID_RECORD", "limit이 올바르지 않다") from None
    if v < 1:
        raise BoundaryError("INVALID_RECORD", "limit은 1 이상이어야 한다")
    return min(v, 500)


class _Stream:
    """파일을 1MiB 청크로 흘리는 WSGI 응답 본문. 응답이 끝나거나 클라이언트가 끊으면 서버가 close()를 불러 정리한다(PEP 3333).
    왜 청크: 데이터셋 파일이 클 수 있어 통째로 메모리에 올리지 않는다(ADR 0012의 스트리밍을 link 0.2.0의 반복자 본문으로 되살렸다)."""

    def __init__(self, path: Path, cleanup):
        self._f = open(path, "rb")
        self._cleanup = cleanup

    def __iter__(self):
        while True:
            chunk = self._f.read(1 << 20)
            if not chunk:
                return
            yield chunk

    def close(self):
        try:
            self._f.close()
        finally:
            self._cleanup()


def make_routes(svc: Service) -> list[Route]:
    """경로 표. 경로 조각의 퍼센트 인코딩(%2F 포함)은 openit_link(0.2.0)가 조각마다 풀어 params로 준다."""

    def take_download_slot():
        if not svc.download_slots.acquire(blocking=False):      # 동시 다운로드 상한: 디스크 읽기와 임시 tar를 지킨다
            raise BoundaryError("UNAVAILABLE", "다운로드가 많다. 잠시 뒤 다시 시도한다")

    def list_datasets(r: Request):
        return Response(200, _page(svc.list_ids(), r.query.get("cursor"), _limit(r.query)))

    def list_versions(r: Request):
        return Response(200, _page(svc.store.list_versions(r.params["d"]), r.query.get("cursor"), _limit(r.query)))

    def get_manifest(r: Request):
        return Response(200, svc.store.get_manifest(r.params["d"], r.params["v"]))

    def get_tar(r: Request):
        take_download_slot()
        td = Path(tempfile.mkdtemp(dir=svc.tmp))
        try:
            svc.dataset_tar(r.params["d"], r.params["v"], td / "d.tar")
            return Response(200, _Stream(td / "d.tar", lambda: (shutil.rmtree(td, ignore_errors=True), svc.download_slots.release())),
                            headers={"Content-Length": str((td / "d.tar").stat().st_size)}, content_type="application/x-tar")
        except BaseException:
            shutil.rmtree(td, ignore_errors=True)
            svc.download_slots.release()
            raise

    def get_file(r: Request):
        did, ver, fp = r.params["d"], r.params["v"], r.params["p"]
        check("FileRequest", {"dataset_id": did, "version": ver, "path": fp})      # '..'·절대 경로·역슬래시는 400(HTTP.md). 그 밖에 manifest에 없는 경로는 404
        take_download_slot()
        try:
            p, size = svc.verified_file(did, ver, fp)
            return Response(200, _Stream(p, svc.download_slots.release), headers={"Content-Length": str(size)}, content_type="application/octet-stream")
        except BaseException:
            svc.download_slots.release()
            raise

    def publish(r: Request):
        if not svc.publish_slots.acquire(blocking=False):
            raise BoundaryError("UNAVAILABLE", "다른 게시가 진행 중이다. 잠시 뒤 다시 시도한다")
        try:
            return _publish_locked(r.raw)
        finally:
            svc.publish_slots.release()

    def _publish_locked(raw: bytes):
        svc.check_free_space(len(raw))
        with tempfile.TemporaryDirectory(dir=svc.tmp) as td:
            td = Path(td)
            body = td / "body.tar"
            body.write_bytes(raw)
            unpack(body, td / "in", max_bytes=svc.max_body, max_entries=svc.max_entries)
            body.unlink()
            mp = td / "in" / "manifest.json"
            if not mp.is_file():
                raise BoundaryError("INVALID_RECORD", "tar에 manifest.json이 있어야 한다")
            import json
            try:
                manifest = json.loads(mp.read_text(encoding="utf-8"))
            except ValueError:
                raise BoundaryError("INVALID_RECORD", "manifest.json이 JSON이 아니다") from None
            if not isinstance(manifest, dict):
                raise BoundaryError("INVALID_RECORD", "manifest.json이 객체가 아니다")
            fdir = td / "in" / "files"
            got = {p.relative_to(fdir).as_posix(): p for p in fdir.rglob("*") if p.is_file()} if fdir.is_dir() else {}
            stray = [p.relative_to(td / "in").as_posix() for p in (td / "in").rglob("*")
                     if p.is_file() and p != mp and fdir not in p.parents]
            if stray:
                raise BoundaryError("INVALID_RECORD", "tar에 manifest.json과 files/ 밖의 항목이 있다")
            did, ver = str(manifest.get("dataset_id")), str(manifest.get("version"))
            with svc.dataset_lock(did):
                # 잠금 안에서 판정하므로 existed와 저장소의 멱등·충돌 판정이 같은 시점을 본다: 같은 hash면 200, 다르면 저장소가 409
                try:
                    svc.store.get_manifest(did, ver)
                    existed = True
                except BoundaryError as e:
                    if e.code not in ("NOT_FOUND", "INVALID_RECORD"):    # 형식이 틀린 ID는 publish가 같은 오류로 거절한다
                        raise
                    existed = False
                res = svc.store.publish(manifest, got)
        return Response(200 if existed else 201, res)

    readers = svc.roles()
    base = "/v1/datasets"
    return [
        Route("POST", base, publish, roles=frozenset({WRITE_ROLE}), raw_body=True, max_body=svc.max_body, response_schema="DatasetManifest"),
        Route("GET", base, list_datasets, roles=readers),
        Route("GET", base + "/{d}/versions", list_versions, roles=readers),
        Route("GET", base + "/{d}/versions/{v}", get_manifest, roles=readers, response_schema="DatasetManifest"),
        Route("GET", base + "/{d}/versions/{v}/files", get_tar, roles=readers),
        Route("GET", base + "/{d}/versions/{v}/files/{p}", get_file, roles=readers),
    ]


def make_app(svc: Service):
    """WSGI 앱. 규약(인증, 413, 계약 검증, 오류 본문, 경로 인코딩, 405 Allow)은 openit_link.App(0.2.0)이 맡는다. 이 겉옷은 라이브러리에 없는 이 서버만의 방어 둘이다:
    (1) 인증 실패 횟수 제한: 같은 주소에서 401이 limit번 쌓이면 올바른 토큰도 잠시 거부해 토큰 추측이 맞는지 알 수 없게 한다(ADR 0012, 규약이 아니라 서버 방어라 라이브러리 몫이 아니다),
    (2) 처리하지 못한 예외를 비밀 없는 503으로(라이브러리는 예외를 잡지 않아 서버가 HTML 500을 낸다; 내부 오류 형식 이름만 로그)."""
    inner = App(make_routes(svc), svc.tokens(), ready=svc.ready)

    def respond_unavailable(start_response, message: str):
        import json
        body = json.dumps(BoundaryError("UNAVAILABLE", message).to_record(PIPELINE_SCHEMA_VERSION), ensure_ascii=False).encode()
        start_response("503 Service Unavailable", [("Content-Type", "application/json"), ("Content-Length", str(len(body)))])
        return [body]

    def app(environ, start_response):
        path = environ.get("PATH_INFO", "/")
        addr = environ.get("REMOTE_ADDR", "-")
        status = []
        if path not in ("/healthz", "/readyz") and svc.auth_blocked(addr):
            out = respond_unavailable(start_response, "인증 시도가 너무 많다. 잠시 뒤 다시 시도한다")
            status.append("503")
        else:
            def sr(st, headers, exc_info=None):
                status.append(st.split(" ", 1)[0])
                return start_response(st, headers, exc_info)
            try:
                out = inner(environ, sr)
            except Exception as e:
                svc.log(f"내부 오류 {type(e).__name__}")
                out = respond_unavailable(start_response, "서비스 내부 오류")
                status.append("503")
            if status and status[0] == "401":
                svc.note_auth_failure(addr)      # 유효한 토큰의 403(역할 부족)은 실패 횟수에 넣지 않는다
        svc.log(f"{environ['REQUEST_METHOD']} {path} {status[0] if status else '-'}")
        return out

    return app


# 기본값은 모두 측정하지 않은 시작값이다(ADR 0012, 0017). 환경 변수로 조정한다.
DEFAULT_THREADS = 16        # 동시 게시 8 + 동시 다운로드 8(슬롯 상한의 합). 읽기 목록 요청은 짧다. 측정 안 함(ADR 0017)
DEFAULT_CONNECTIONS = 32    # 이전 구현의 시작값을 그대로 옮긴다. 측정 안 함
DEFAULT_IDLE_TIMEOUT = 30   # 이전 구현의 소켓 timeout을 그대로 옮긴다. 측정 안 함
DEFAULT_DRAIN_GRACE = 8     # Docker stop 기본 대기 10초(SIGKILL 전)에서 여유 2초를 뺀 값(제약). 큰 게시는 이보다 길 수 있다


class DatasetServer:
    """waitress 서버 하나와 종료 절차. serve_forever()는 shutdown()이 불릴 때까지 돌고, 그때 새 연결을 받지 않고 진행 중인 요청을
    drain_grace초까지 마저 처리한 뒤 돌아온다. 왜 직접 루프를 도나: waitress의 run()은 종료 신호에 작업 스레드를 5초만 기다리고 응답을
    소켓에 쓰는 주 루프를 먼저 끝내 진행 중 응답이 나가지 못한다(waitress 3.0.2 server.py run())."""

    def __init__(self, svc: Service, host="127.0.0.1", port=0, *, threads=DEFAULT_THREADS, connection_limit=DEFAULT_CONNECTIONS,
                 channel_timeout=DEFAULT_IDLE_TIMEOUT, drain_grace=DEFAULT_DRAIN_GRACE):
        self._map: dict = {}
        self._srv = create_server(make_app(svc), map=self._map, host=host, port=port, threads=threads, connection_limit=connection_limit,
                                  channel_timeout=int(channel_timeout),
                                  cleanup_interval=min(5, max(1, int(channel_timeout))), max_request_body_size=svc.max_body, ident="dataset-store",
                                  clear_untrusted_proxy_headers=True)
        self._stop, self._done, self._grace = threading.Event(), threading.Event(), drain_grace
        self._done.set()

    @property
    def server_address(self):
        return (self._srv.effective_host, self._srv.effective_port)

    def serve_forever(self):
        self._done.clear()
        try:
            while not self._stop.is_set():
                wasyncore.loop(timeout=0.1, map=self._map, count=1)
            wasyncore.dispatcher.close(self._srv)           # 새 연결을 받지 않는다(trigger는 작업 스레드가 쓰므로 닫지 않는다)
            deadline = time.monotonic() + self._grace
            while time.monotonic() < deadline and any(self._busy(c) for c in list(self._srv.active_channels.values())):
                wasyncore.loop(timeout=0.1, map=self._map, count=1)
        finally:
            self._done.set()

    @staticmethod
    def _busy(ch) -> bool:
        return bool(ch.requests or ch.total_outbufs_len or ch.request is not None)

    def shutdown(self):
        self._stop.set()
        self._done.wait()

    def server_close(self):
        wasyncore.close_all(self._map)
        self._srv.task_dispatcher.shutdown()


def make_server(svc: Service, host="127.0.0.1", port=0, **kw) -> DatasetServer:
    return DatasetServer(svc, host, port, **kw)
