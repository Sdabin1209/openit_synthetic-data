"""dataset-store 서비스(I2 서버, D100). HTTP.md `## I2`와 CONVENTIONS 9절을 따른다. 표준 라이브러리 HTTP 서버(ADR 0012).

환경 변수(진입점 `python -m synthetic_data.service`). 비밀은 boundary_contracts.read_secret(D84)으로 읽는다:
  DATASET_STORE_READ_TOKENS_FILE / DATASET_STORE_READ_TOKENS    역할=토큰,역할=토큰 (읽기 경로)
  DATASET_STORE_WRITE_TOKENS_FILE / DATASET_STORE_WRITE_TOKENS  synthetic-data=토큰   (POST. 쓰기 역할은 synthetic-data만)
  DATASET_STORE_ROOT         저장 볼륨(기본 /data)
  DATASET_STORE_SURVEY_SCHEMA_DIR  문진 스키마 디렉터리(CONTRACT_VERSION과 schemas/, 기본 /app/survey_schema)
  DATASET_STORE_PORT         기본 8080 (0이면 빈 포트)
  DATASET_STORE_MAX_BODY     게시 본문 최대 바이트(기본 1GiB)
  DATASET_STORE_SOCKET_TIMEOUT / MAX_CONNECTIONS / MAX_PUBLISHES / AUTH_FAIL_LIMIT / MIN_FREE_GB / MIN_TOKEN_LEN
로그는 표준 출력으로, 토큰과 본문은 남기지 않는다."""
from __future__ import annotations

import hmac
import json
import os
import re
import shutil
import signal
import sys
import tempfile
import threading
import time
from collections import defaultdict, deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

from boundary_contracts import BoundaryError, SecretError, read_secret

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
                 max_publishes: int = 1, auth_fail_limit: int = 10, auth_fail_window: float = 60.0,
                 min_free_gb: float = 1.0, free_bytes=None):
        for role in write_tokens.values():
            if role != WRITE_ROLE:
                raise ValueError(f"쓰기 역할은 {WRITE_ROLE}만 허용한다")
        self.root, self.read, self.write, self.max_body, self.log = Path(root), read_tokens, write_tokens, max_body, log
        self.store = FileDatasetStore(self.root / "datasets", validators)
        self.tmp = self.root / ".tmp"
        self.socket_timeout, self.max_connections = socket_timeout, max_connections
        self.auth_fail_limit, self.auth_fail_window, self.min_free_gb = auth_fail_limit, auth_fail_window, min_free_gb
        self._free_bytes = free_bytes or (lambda: shutil.disk_usage(self.root).free)
        self.publish_slots = threading.BoundedSemaphore(max(1, max_publishes))
        self._fails = defaultdict(deque)
        self._mu = threading.Lock()
        shutil.rmtree(self.tmp, ignore_errors=True)       # 재시작 정리: 이전 실행이 남긴 요청 임시 폴더
        self.tmp.mkdir(parents=True, exist_ok=True)

    def check_free_space(self, n: int) -> None:
        # 본문 tar + 풀어 둔 사본이 동시에 있는 순간의 2배 + 여유. 측정 안 함(ADR 0012)
        if self._free_bytes() < 2 * n + int(self.min_free_gb * 2**30):
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
            q = self._fails[addr]
            while q and now - q[0] > self.auth_fail_window:
                q.popleft()
            return len(q) >= self.auth_fail_limit

    def note_auth_failure(self, addr: str) -> None:
        with self._mu:
            self._fails[addr].append(time.monotonic())

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
    def list_ids(self) -> list[str]:
        try:
            return sorted(c.name for c in self.store.root.iterdir() if c.is_dir() and not c.name.startswith("."))
        except OSError as e:
            raise BoundaryError("UNAVAILABLE", "저장소를 읽을 수 없다") from e

    def dataset_tar(self, did: str, ver: str, out: Path) -> None:
        m = self.store.get_manifest(did, ver)
        with tempfile.TemporaryDirectory(dir=self.tmp) as td:
            ent = {}
            for i, f in enumerate(m["files"]):
                p = Path(td) / str(i)
                p.write_bytes(self.store.open_file(did, ver, f["path"]).read())    # 해시를 확인한 바이트만 낸다
                ent[f["path"]] = p
            tarutil.pack(ent, out)


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

        def log_message(self, fmt, *args):
            svc.log(f"{self.command} {urlparse(self.path).path} {args[1] if len(args) > 1 else ''}")

        def _send(self, code, body: bytes, ctype="application/json"):
            self.send_response(code)
            self.send_header("Content-Type", ctype + ("; charset=utf-8" if ctype == "application/json" else ""))
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _json(self, code, obj):
            self._send(code, json.dumps(obj, ensure_ascii=False).encode())

        def _file(self, path: Path, ctype: str):
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(path.stat().st_size))
            self.end_headers()
            with open(path, "rb") as f:
                shutil.copyfileobj(f, self.wfile)

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
                left = min(int(self.headers.get("Content-Length") or 0), DRAIN_CAP)
                self.connection.settimeout(0.25)
                while left > 0:
                    chunk = self.rfile.read1(min(1 << 20, left))
                    if not chunk:
                        break
                    left -= len(chunk)
            except (OSError, ValueError):
                pass

        def _dispatch(self):
            u = urlparse(self.path)
            path, q = u.path, parse_qs(u.query)
            if path == "/healthz":
                return self._json(200, {"status": "ok"})
            if path == "/readyz":
                ok = svc.ready()
                return self._json(200 if ok else 503, {"status": "ready" if ok else "not-ready"})
            addr, hdr = self.client_address[0], self.headers.get("Authorization")
            try:
                svc.authorize(self.command, hdr)
            except BoundaryError as e:
                if not svc.token_valid(hdr):      # 유효한 토큰의 403(역할 부족)은 실패 횟수에 넣지 않는다
                    throttled = svc.auth_blocked(addr)
                    svc.note_auth_failure(addr)
                    if throttled:
                        raise BoundaryError("UNAVAILABLE", "인증 시도가 너무 많다. 잠시 뒤 다시 시도한다") from None
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
                with tempfile.TemporaryDirectory(dir=svc.tmp) as td:
                    out = Path(td) / "d.tar"
                    svc.dataset_tar(unquote(m.group(1)), unquote(m.group(2)), out)
                    return self._file(out, "application/x-tar")
            m = _FILE.match(path)
            if m:
                did, ver, fp = (unquote(g) for g in m.groups())
                svc.store._check_path(fp)          # '..'·절대 경로·역슬래시는 400(HTTP.md). 그 밖에 manifest에 없는 경로는 404
                return self._send(200, svc.store.open_file(did, ver, fp).read(), "application/octet-stream")
            raise BoundaryError("NOT_FOUND", "경로가 없다")

        def _publish(self):
            n = int(self.headers.get("Content-Length") or -1)
            if n < 0:
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
                tarutil.unpack(body, td / "in", max_bytes=svc.max_body)
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
                existed = True
                try:
                    svc.store.get_manifest(did, ver)
                except BoundaryError as e:
                    if e.code == "NOT_FOUND":
                        existed = False
                    elif e.code != "INVALID_RECORD":    # 형식이 틀린 ID는 publish가 같은 오류로 거절한다
                        raise
                    else:
                        existed = False
                res = svc.store.publish(manifest, got)    # 검증·멱등(같은 hash 200)·충돌(409)은 파일 저장소가 한다
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
                      max_publishes=int(env.get("DATASET_STORE_MAX_PUBLISHES", 1)),
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
