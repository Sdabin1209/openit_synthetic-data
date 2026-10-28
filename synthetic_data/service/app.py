"""dataset-store 서비스(I2 서버, D100). HTTP.md `## I2`와 CONVENTIONS 9절을 따른다. 표준 라이브러리 HTTP 서버(ADR 0012).

환경 변수(진입점 `python -m synthetic_data.service`). 비밀은 boundary_contracts.read_secret(D84)으로 읽는다:
  DATASET_STORE_READ_TOKENS_FILE / DATASET_STORE_READ_TOKENS    역할=토큰,역할=토큰 (읽기 경로)
  DATASET_STORE_WRITE_TOKENS_FILE / DATASET_STORE_WRITE_TOKENS  synthetic-data=토큰   (POST. 쓰기 역할은 synthetic-data만)
  DATASET_STORE_ROOT         저장 볼륨(기본 /data)
  DATASET_STORE_SURVEY_SCHEMA_DIR  문진 스키마 디렉터리(CONTRACT_VERSION과 schemas/, 기본 /app/survey_schema)
  DATASET_STORE_PORT         기본 8080 (0이면 빈 포트)
  DATASET_STORE_MAX_BODY     게시 본문 최대 바이트(기본 1GiB)
  DATASET_STORE_SOCKET_TIMEOUT / MAX_CONNECTIONS / MAX_PUBLISHES / MAX_DOWNLOADS / MAX_ENTRIES / HEADER_DEADLINE /
  AUTH_FAIL_LIMIT / MIN_FREE_GB / MIN_TOKEN_LEN
로그는 표준 출력으로, 토큰과 본문은 남기지 않는다."""
from __future__ import annotations

import hmac
import io
import json
import os
import re
import shutil
import signal
import sys
import tempfile
import threading
import time
from contextlib import contextmanager
from collections import defaultdict, deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

from boundary_contracts import BoundaryError, SecretError, read_secret

from boundary_contracts import canonical

from ..schemas import Validators
from ..store import FileDatasetStore
from . import tarutil

STATUS = {"INVALID_RECORD": 400, "PERMISSION_DENIED": 403, "NOT_FOUND": 404, "CONFLICT": 409,
          "FAILED_PRECONDITION": 412, "UNSUPPORTED_VERSION": 422, "INTEGRITY_ERROR": 422, "UNAVAILABLE": 503}
WRITE_ROLE = "synthetic-data"      # HTTP.md I2: 쓰기 역할은 synthetic-data 하나
DRAIN_CAP = 1 << 20                # 거절 응답 전에 버리는 본문의 최대 바이트(ADR 0012, 측정 안 함)
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


class Service:
    def __init__(self, root: Path, validators: Validators, read_tokens: dict, write_tokens: dict, *, max_body: int = 1 << 30,
                 log=lambda s: print(s, flush=True), socket_timeout: float = 30.0, max_connections: int = 32,
                 max_publishes: int = 8, max_downloads: int = 8, max_entries: int = 1000, header_deadline: float = 10.0,
                 auth_fail_limit: int = 10, auth_fail_window: float = 60.0,
                 min_free_gb: float = 1.0, free_bytes=None):
        for role in write_tokens.values():
            if role != WRITE_ROLE:
                raise ValueError(f"쓰기 역할은 {WRITE_ROLE}만 허용한다")
        if set(read_tokens) & set(write_tokens):
            raise ValueError("같은 토큰이 읽기와 쓰기 양쪽에 설정돼 있다. 역할마다 다른 토큰을 쓴다")
        self.root, self.read, self.write, self.max_body, self.log = Path(root), read_tokens, write_tokens, max_body, log
        self.store = FileDatasetStore(self.root / "datasets", validators)
        self.tmp = self.root / ".tmp"
        self.socket_timeout, self.max_connections = socket_timeout, max_connections
        self.auth_fail_limit, self.auth_fail_window, self.min_free_gb = auth_fail_limit, auth_fail_window, min_free_gb
        self._free_bytes = free_bytes or (lambda: shutil.disk_usage(self.root).free)
        self.max_entries, self.header_deadline = max_entries, header_deadline
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

    @staticmethod
    def _role(tokens: dict, header):
        if not header or not header.startswith("Bearer "):
            return None
        given = header[7:].strip().encode()
        found = None
        for tok, role in tokens.items():      # 일치해도 끝까지 돌아 시간이 일정하다
            if hmac.compare_digest(tok.encode(), given):
                found = role
        return found

    def token_valid(self, header) -> bool:
        return self._role(self.read, header) is not None or self._role(self.write, header) is not None

    def authorize(self, method: str, header) -> None:
        if method == "POST":
            if self._role(self.write, header) != WRITE_ROLE:
                raise BoundaryError("PERMISSION_DENIED", "쓰기 권한이 없다")
        elif not self.token_valid(header):
            raise BoundaryError("PERMISSION_DENIED", "읽기 권한이 없다")

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

    def ready(self) -> bool:
        try:
            self.store.root.stat()
            p = self.tmp / ".ready"
            p.write_text("1")
            p.unlink()
            return True
        except Exception:
            return False

    # ---- I2 ----
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
        tarutil.pack({f["path"]: self.verified_file(did, ver, f["path"])[0] for f in m["files"]}, out)


class _DeadlineRaw(io.RawIOBase):
    """소켓 읽기에 요청 한 건의 헤더 수신 전체 마감을 건다(slowloris 완화). 소켓 timeout은 recv 한 번마다라 바이트를 천천히 흘리면 못 막는다.
    첫 바이트가 올 때까지는 소켓 timeout(유휴 연결)만 적용하고, 첫 바이트부터 disarm()까지 limit초를 준다. recv마다 남은 시간으로 확인한다."""

    def __init__(self, conn, limit: float, idle: float):
        self._conn, self._limit, self._idle = conn, limit, idle
        self._deadline = None

    def readable(self):
        return True

    def disarm(self):
        self._deadline = None
        self._conn.settimeout(self._idle)

    def readinto(self, b):
        if self._deadline is None:
            self._conn.settimeout(self._idle)
            n = self._conn.recv_into(b)
            if n:
                self._deadline = time.monotonic() + self._limit
            return n
        left = self._deadline - time.monotonic()
        if left <= 0:
            raise TimeoutError("헤더 수신 마감")
        self._conn.settimeout(min(self._idle, left))
        return self._conn.recv_into(b)


_DS = re.compile(r"^/v1/datasets/([^/]+)/versions$")
_VER = re.compile(r"^/v1/datasets/([^/]+)/versions/([^/]+)$")
_FILES = re.compile(r"^/v1/datasets/([^/]+)/versions/([^/]+)/files$")
_FILE = re.compile(r"^/v1/datasets/([^/]+)/versions/([^/]+)/files/([^/]+)$")


def _page(items: list, cursor, limit: int):
    start = 0
    if cursor is not None:
        if not cursor.isdigit():
            raise BoundaryError("INVALID_RECORD", "cursor가 올바르지 않다")
        start = int(cursor)
    chunk = items[start:start + limit]
    return {"items": chunk, "next_cursor": str(start + limit) if start + limit < len(items) else None}


def _one(q, k):
    return q[k][0] if k in q else None


def _limit(q) -> int:
    try:
        v = int(_one(q, "limit") or 100)
    except ValueError:
        raise BoundaryError("INVALID_RECORD", "limit이 올바르지 않다") from None
    if v < 1:
        raise BoundaryError("INVALID_RECORD", "limit은 1 이상이어야 한다")
    return min(v, 500)


def make_handler(svc: Service):
    class H(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"
        server_version = "dataset-store"
        timeout = svc.socket_timeout        # 느린 클라이언트가 스레드를 잡지 못하게 한다

        def setup(self):
            super().setup()
            self._dl = _DeadlineRaw(self.connection, svc.header_deadline, svc.socket_timeout)
            self.rfile = io.BufferedReader(self._dl, self.rbufsize if self.rbufsize > 0 else io.DEFAULT_BUFFER_SIZE)

        def log_message(self, fmt, *args):
            # 요청 줄이 잘못됐거나 URI가 너무 길면(414) self.path·command가 아직 없다
            svc.log(f"{getattr(self, 'command', None) or '-'} {urlparse(getattr(self, 'path', '-')).path} {args[1] if len(args) > 1 else ''}")

        def _send(self, code, body: bytes, ctype="application/json"):
            self.send_response(code)
            self.send_header("Content-Type", ctype + ("; charset=utf-8" if ctype == "application/json" else ""))
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _json(self, code, obj):
            self._send(code, json.dumps(obj, ensure_ascii=False).encode())

        def _file(self, path: Path, ctype: str, size: int = None):
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(path.stat().st_size if size is None else size))
            self.end_headers()
            with open(path, "rb") as f:
                shutil.copyfileobj(f, self.wfile, 1 << 20)       # 청크로 흘린다

        def _length(self):
            """Content-Length를 엄격히 읽는다: 숫자만, 한 번만. 아니면 400(요청 밀반입·비정상 값 방어)."""
            vals = self.headers.get_all("Content-Length") or []
            if len(vals) > 1 or (vals and not vals[0].isascii()) or (vals and not vals[0].isdigit()):
                raise BoundaryError("INVALID_RECORD", "Content-Length가 올바르지 않다")
            return int(vals[0]) if vals else None

        def _fail(self, e: BoundaryError):
            if self.command == "POST":
                self.close_connection = True
                self._drain()
            self._json(STATUS[e.code], e.to_record())

        _consumed = False

        def _drain(self):
            # 읽지 않고 답하면 아직 보내는 클라이언트가 연결 초기화를 받아 403/400을 못 본다. 작은 본문만 버리고 연결을 닫는다.
            if self._consumed:
                return
            self._consumed = True
            try:
                left = min(self._length() or 0, DRAIN_CAP)
                self._dl._idle = 0.25          # 읽기 대기는 0.25초까지(느린 송신자가 스레드를 잡지 못하게). 연결은 곧 닫는다
                while left > 0:
                    chunk = self.rfile.read1(min(1 << 20, left))
                    if not chunk:
                        break
                    left -= len(chunk)
            except (OSError, ValueError, BoundaryError):
                pass

        def _dispatch(self):
            self._dl.disarm()                  # 헤더를 다 받았다. 본문은 소켓 timeout만 적용
            self._length()                     # 어떤 메서드든 잘못된 Content-Length는 인증 전에 400
            u = urlparse(self.path)
            path, q = u.path, parse_qs(u.query)
            if path == "/healthz":
                return self._json(200, {"status": "ok"})
            if path == "/readyz":
                ok = svc.ready()
                return self._json(200 if ok else 503, {"status": "ready" if ok else "not-ready"})
            addr, hdr = self.client_address[0], self.headers.get("Authorization")
            # 차단 확인이 먼저다: 차단 중인 주소는 올바른 토큰도 거부한다(그렇지 않으면 차단 중에도 추측이 맞는지 알 수 있다, ADR 0012)
            if svc.auth_blocked(addr):
                raise BoundaryError("UNAVAILABLE", "인증 시도가 너무 많다. 잠시 뒤 다시 시도한다")
            try:
                svc.authorize(self.command, hdr)
            except BoundaryError:
                if not svc.token_valid(hdr):      # 유효한 토큰의 403(역할 부족)은 실패 횟수에 넣지 않는다
                    svc.note_auth_failure(addr)
                raise
            if self.command == "POST":
                if path != "/v1/datasets":
                    raise BoundaryError("NOT_FOUND", "경로가 없다")
                return self._publish()
            if self.command != "GET":
                raise BoundaryError("NOT_FOUND", "경로가 없다")
            if path == "/v1/datasets":
                return self._json(200, _page(svc.list_ids(), _one(q, "cursor"), _limit(q)))
            m = _DS.match(path)
            if m:
                return self._json(200, _page(svc.store.list_versions(unquote(m.group(1))), _one(q, "cursor"), _limit(q)))
            m = _VER.match(path)
            if m:
                return self._json(200, svc.store.get_manifest(unquote(m.group(1)), unquote(m.group(2))))
            m = _FILES.match(path)
            if m:
                with self._download():
                    with tempfile.TemporaryDirectory(dir=svc.tmp) as td:
                        out = Path(td) / "d.tar"
                        svc.dataset_tar(unquote(m.group(1)), unquote(m.group(2)), out)
                        return self._file(out, "application/x-tar")
            m = _FILE.match(path)
            if m:
                did, ver, fp = (unquote(g) for g in m.groups())
                svc.store._check_path(fp)          # '..'·절대 경로·역슬래시는 400(HTTP.md). 그 밖에 manifest에 없는 경로는 404
                with self._download():
                    p, size = svc.verified_file(did, ver, fp)
                    return self._file(p, "application/octet-stream", size)
            raise BoundaryError("NOT_FOUND", "경로가 없다")

        @contextmanager
        def _download(self):
            if not svc.download_slots.acquire(blocking=False):      # 동시 다운로드 상한: 디스크 읽기와 임시 tar를 지킨다
                raise BoundaryError("UNAVAILABLE", "다운로드가 많다. 잠시 뒤 다시 시도한다")
            try:
                yield
            finally:
                svc.download_slots.release()

        def _publish(self):
            n = self._length()
            if n is None:
                raise BoundaryError("INVALID_RECORD", "Content-Length가 필요하다")
            if n > svc.max_body:
                raise BoundaryError("INVALID_RECORD", "본문이 너무 크다")
            if not svc.publish_slots.acquire(blocking=False):
                raise BoundaryError("UNAVAILABLE", "다른 게시가 진행 중이다. 잠시 뒤 다시 시도한다")
            try:
                self._publish_locked(n)
            finally:
                svc.publish_slots.release()

        def _publish_locked(self, n: int):
            svc.check_free_space(n)
            self._consumed = True
            with tempfile.TemporaryDirectory(dir=svc.tmp) as td:
                td = Path(td)
                body = td / "body.tar"
                left = n
                with open(body, "wb") as f:
                    while left:
                        chunk = self.rfile.read(min(1 << 20, left))
                        if not chunk:
                            raise BoundaryError("INVALID_RECORD", "본문이 중간에 끊겼다")
                        f.write(chunk)
                        left -= len(chunk)
                tarutil.unpack(body, td / "in", max_bytes=svc.max_body, max_entries=svc.max_entries)
                body.unlink()
                mp = td / "in" / "manifest.json"
                if not mp.is_file():
                    raise BoundaryError("INVALID_RECORD", "tar에 manifest.json이 있어야 한다")
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
            self._json(200 if existed else 201, res)

        def _handle(self):
            self._consumed = False
            try:
                self._dispatch()
            except BoundaryError as e:
                self._fail(e)
            except Exception as e:
                svc.log(f"내부 오류 {type(e).__name__}")
                self._fail(BoundaryError("UNAVAILABLE", "서비스 내부 오류"))

        do_GET = do_POST = do_PUT = do_DELETE = do_PATCH = _handle

        def _no_body_405(self):
            # 왜: HEAD·OPTIONS를 정의하지 않으면 표준 라이브러리가 HTML 본문의 501을 낸다. 아는 메서드는 JSON 계약대로 405로 답한다(퍼징 시험이 발견).
            self.send_response(405)
            self.send_header("Allow", "GET, POST")
            self.send_header("Content-Length", "0")
            self.end_headers()

        do_HEAD = do_OPTIONS = _no_body_405

    return H


class _Server(ThreadingHTTPServer):
    daemon_threads = False        # 진행 중 요청을 끊지 않고 server_close가 기다린다
    block_on_close = True

    def __init__(self, addr, handler, max_connections: int):
        super().__init__(addr, handler)
        self._slots = threading.BoundedSemaphore(max(1, max_connections))

    def process_request(self, request, client_address):
        if not self._slots.acquire(blocking=False):
            try:
                request.settimeout(2)
                body = json.dumps(BoundaryError("UNAVAILABLE", "연결이 너무 많다").to_record(), ensure_ascii=False).encode()
                request.sendall(b"HTTP/1.1 503 Service Unavailable\r\nContent-Type: application/json\r\nContent-Length: "
                                + str(len(body)).encode() + b"\r\nConnection: close\r\n\r\n" + body)
            except OSError:
                pass
            self.shutdown_request(request)
            return
        super().process_request(request, client_address)

    def process_request_thread(self, request, client_address):
        try:
            super().process_request_thread(request, client_address)
        finally:
            self._slots.release()


def make_server(svc: Service, host="127.0.0.1", port=0) -> ThreadingHTTPServer:
    return _Server((host, port), make_handler(svc), svc.max_connections)


# 기본값은 모두 측정하지 않은 보수적 시작값이다(ADR 0012). 환경 변수로 조정한다.
def main(env=os.environ) -> int:
    try:
        read = parse_tokens(read_secret("DATASET_STORE_READ_TOKENS", environ=env))
        write = parse_tokens(read_secret("DATASET_STORE_WRITE_TOKENS", environ=env))
        if not read and not write:
            raise ValueError("DATASET_STORE_READ_TOKENS 또는 DATASET_STORE_WRITE_TOKENS가 필요하다")
        check_token_strength({**read, **write}, min_len=int(env.get("DATASET_STORE_MIN_TOKEN_LEN", MIN_TOKEN_LEN)))
        validators = Validators(survey_schema_dir=Path(env.get("DATASET_STORE_SURVEY_SCHEMA_DIR", "/app/survey_schema")))
        validators.runtime_contract_version          # 스키마 디렉터리가 없으면 시작을 거부한다
        svc = Service(Path(env.get("DATASET_STORE_ROOT", "/data")), validators, read, write,
                      max_body=int(env.get("DATASET_STORE_MAX_BODY", 1 << 30)),
                      socket_timeout=float(env.get("DATASET_STORE_SOCKET_TIMEOUT", 30)),
                      max_connections=int(env.get("DATASET_STORE_MAX_CONNECTIONS", 32)),
                      max_publishes=int(env.get("DATASET_STORE_MAX_PUBLISHES", 8)),
                      max_downloads=int(env.get("DATASET_STORE_MAX_DOWNLOADS", 8)),
                      max_entries=int(env.get("DATASET_STORE_MAX_ENTRIES", 1000)),
                      header_deadline=float(env.get("DATASET_STORE_HEADER_DEADLINE", 10)),
                      auth_fail_limit=int(env.get("DATASET_STORE_AUTH_FAIL_LIMIT", 10)),
                      min_free_gb=float(env.get("DATASET_STORE_MIN_FREE_GB", 1)))
    except (ValueError, OSError, SecretError, BoundaryError) as e:
        print(f"시작 실패: {type(e).__name__}: {e}", file=sys.stderr, flush=True)
        return 2
    srv = make_server(svc, env.get("DATASET_STORE_HOST", "0.0.0.0"), int(env.get("DATASET_STORE_PORT", 8080)))

    def _stop(signum, frame):
        threading.Thread(target=srv.shutdown, daemon=True).start()
    try:
        signal.signal(signal.SIGTERM, _stop)
    except ValueError:
        pass
    print(f"dataset-store 시작 포트 {srv.server_address[1]}", flush=True)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        srv.server_close()
        shutil.rmtree(svc.tmp, ignore_errors=True)
    return 0
