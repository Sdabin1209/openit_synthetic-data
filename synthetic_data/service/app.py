"""dataset-store 서비스(I2 서버, D100). HTTP.md `## I2`와 CONVENTIONS 9절을 따른다. WSGI(PEP 3333) 앱 + waitress(ADR 0017, D111).

환경 변수(진입점 `python -m synthetic_data.service`). 비밀은 boundary_contracts.read_secret(D84)으로 읽는다:
  DATASET_STORE_READ_TOKENS_FILE / DATASET_STORE_READ_TOKENS    역할=토큰,역할=토큰 (읽기 경로)
  DATASET_STORE_WRITE_TOKENS_FILE / DATASET_STORE_WRITE_TOKENS  synthetic-data=토큰   (POST. 쓰기 역할은 synthetic-data만)
  DATASET_STORE_ROOT         저장 볼륨(기본 /data)
  DATASET_STORE_SURVEY_SCHEMA_DIR  문진 스키마 디렉터리(CONTRACT_VERSION과 schemas/, 기본 /app/survey_schema)
  DATASET_STORE_PORT         기본 8080 (0이면 빈 포트)
  DATASET_STORE_MAX_BODY     게시 본문 최대 바이트(기본 1GiB). waitress max_request_body_size
  DATASET_STORE_SOCKET_TIMEOUT  유휴 연결 timeout 초(waitress channel_timeout)
  DATASET_STORE_MAX_CONNECTIONS  동시 연결 상한(waitress connection_limit). DATASET_STORE_THREADS  작업 스레드 수
  DATASET_STORE_DRAIN_GRACE  종료 신호 뒤 진행 중 요청을 기다리는 최대 초
  DATASET_STORE_MAX_PUBLISHES / MAX_DOWNLOADS / MAX_ENTRIES / AUTH_FAIL_LIMIT / MIN_FREE_GB / MIN_TOKEN_LEN
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
from contextlib import contextmanager
from http import HTTPStatus
from collections import defaultdict, deque
from pathlib import Path
from urllib.parse import parse_qs, unquote

from boundary_contracts import BoundaryError, SecretError, read_secret
from waitress import wasyncore
from waitress.server import create_server

from boundary_contracts import canonical

from ..schemas import Validators
from ..store import FileDatasetStore
from . import tarutil

STATUS = {"INVALID_RECORD": 400, "PERMISSION_DENIED": 403, "NOT_FOUND": 404, "CONFLICT": 409,
          "FAILED_PRECONDITION": 412, "UNSUPPORTED_VERSION": 422, "INTEGRITY_ERROR": 422, "UNAVAILABLE": 503}
WRITE_ROLE = "synthetic-data"      # HTTP.md I2: 쓰기 역할은 synthetic-data 하나
MIN_TOKEN_LEN = 32                 # 128비트 이상 무작위 16진수(OWASP 세션 관리 치트시트·NIST SP 800-63B 참고, 원문은 다시 확인하지 않았다)


class Unauthenticated(BoundaryError):
    """토큰이 없거나 틀림. 상태 401 + `WWW-Authenticate: Bearer`, 본문 code는 PERMISSION_DENIED(CONVENTIONS 9절 '401과 403', D106).
    왜: RFC 9110 15.5.2는 인증 자격이 없거나 틀린 요청에 401과 WWW-Authenticate를 요구하고, RFC 6750 3절은 Bearer 스킴의 이 헤더를 정한다.
    토큰은 맞지만 권한이 없을 때(읽기 토큰으로 게시)만 403이다(RFC 9110 15.5.4)."""

    def __init__(self, message: str):
        super().__init__("PERMISSION_DENIED", message)


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
        self.store = FileDatasetStore(self.root / "datasets", validators)
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
                if self.token_valid(header):
                    raise BoundaryError("PERMISSION_DENIED", "쓰기 권한이 없다")      # 토큰은 맞지만 읽기 토큰: 403
                raise Unauthenticated("토큰이 없거나 틀리다")
        elif not self.token_valid(header):
            raise Unauthenticated("토큰이 없거나 틀리다")

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


class _Stream:
    """파일을 청크로 흘리는 WSGI 응답 본문. 응답이 끝나거나 클라이언트가 끊으면 서버가 close()를 불러 정리한다(PEP 3333)."""

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


def make_app(svc: Service):
    """WSGI 앱. 연결·timeout·스레드·본문 상한은 서버(waitress)의 몫이고 여기는 인증, 경로, 계약 오류만 다룬다."""

    def respond(start_response, code, body: bytes, ctype="application/json", headers=()):
        ct = ctype + ("; charset=utf-8" if ctype == "application/json" else "")
        start_response(f"{code} {HTTPStatus(code).phrase}", [("Content-Type", ct), ("Content-Length", str(len(body))), *headers])
        return [body]

    def json_response(start_response, code, obj, headers=()):
        return respond(start_response, code, json.dumps(obj, ensure_ascii=False).encode(), headers=headers)

    def stream(start_response, path: Path, ctype: str, size: int, cleanup):
        start_response("200 OK", [("Content-Type", ctype), ("Content-Length", str(size))])
        return _Stream(path, cleanup)

    def fail(start_response, e: BoundaryError):
        if isinstance(e, Unauthenticated):
            return json_response(start_response, 401, e.to_record(), headers=(("WWW-Authenticate", "Bearer"),))
        return json_response(start_response, STATUS[e.code], e.to_record())

    @contextmanager
    def download_slot():
        if not svc.download_slots.acquire(blocking=False):      # 동시 다운로드 상한: 디스크 읽기와 임시 tar를 지킨다
            raise BoundaryError("UNAVAILABLE", "다운로드가 많다. 잠시 뒤 다시 시도한다")
        try:
            yield
        finally:
            svc.download_slots.release()

    def publish(environ):
        n = int(environ.get("CONTENT_LENGTH") or 0)
        if not svc.publish_slots.acquire(blocking=False):
            raise BoundaryError("UNAVAILABLE", "다른 게시가 진행 중이다. 잠시 뒤 다시 시도한다")
        try:
            return publish_locked(environ["wsgi.input"], n)
        finally:
            svc.publish_slots.release()

    def publish_locked(src, n: int):
        svc.check_free_space(n)
        with tempfile.TemporaryDirectory(dir=svc.tmp) as td:
            td = Path(td)
            body = td / "body.tar"
            with open(body, "wb") as f:
                shutil.copyfileobj(src, f, 1 << 20)       # waitress가 이미 받아 둔 본문(큰 것은 임시 파일)을 옮긴다
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
        return (200 if existed else 201), res

    def dispatch(environ, start_response):
        # 왜 REQUEST_URI인가: WSGI의 PATH_INFO는 퍼센트 디코딩돼 있어 파일 경로의 %2F(HTTP.md I2 open_file)가 '/'로 바뀐다. 원래 경로를 쓴다.
        method, path = environ["REQUEST_METHOD"], (environ.get("REQUEST_URI") or environ["PATH_INFO"]).split("?", 1)[0]
        q = parse_qs(environ.get("QUERY_STRING", ""))
        if method in ("HEAD", "OPTIONS"):
            # 왜: 아는 메서드는 JSON 계약대로 405로 답한다(퍼징 시험이 발견한 결함, 표준 라이브러리 서버는 HTML 501을 냈다)
            start_response("405 Method Not Allowed", [("Allow", "GET, POST"), ("Content-Length", "0")])
            return [b""]
        if path == "/healthz":
            return json_response(start_response, 200, {"status": "ok"})
        if path == "/readyz":
            ok = svc.ready()
            return json_response(start_response, 200 if ok else 503, {"status": "ready" if ok else "not-ready"})
        addr, hdr = environ.get("REMOTE_ADDR", "-"), environ.get("HTTP_AUTHORIZATION")
        # 차단 확인이 먼저다: 차단 중인 주소는 올바른 토큰도 거부한다(그렇지 않으면 차단 중에도 추측이 맞는지 알 수 있다, ADR 0012)
        if svc.auth_blocked(addr):
            raise BoundaryError("UNAVAILABLE", "인증 시도가 너무 많다. 잠시 뒤 다시 시도한다")
        try:
            svc.authorize(method, hdr)
        except BoundaryError:
            if not svc.token_valid(hdr):      # 유효한 토큰의 403(역할 부족)은 실패 횟수에 넣지 않는다
                svc.note_auth_failure(addr)
            raise
        if method == "POST":
            if path != "/v1/datasets":
                raise BoundaryError("NOT_FOUND", "경로가 없다")
            code, res = publish(environ)
            return json_response(start_response, code, res)
        if method != "GET":
            raise BoundaryError("NOT_FOUND", "경로가 없다")
        if path == "/v1/datasets":
            return json_response(start_response, 200, _page(svc.list_ids(), _one(q, "cursor"), _limit(q)))
        m = _DS.match(path)
        if m:
            return json_response(start_response, 200, _page(svc.store.list_versions(unquote(m.group(1))), _one(q, "cursor"), _limit(q)))
        m = _VER.match(path)
        if m:
            return json_response(start_response, 200, svc.store.get_manifest(unquote(m.group(1)), unquote(m.group(2))))
        m = _FILES.match(path)
        if m:
            with download_slot():
                td = Path(tempfile.mkdtemp(dir=svc.tmp))
                try:
                    svc.dataset_tar(unquote(m.group(1)), unquote(m.group(2)), td / "d.tar")
                    return stream(start_response, td / "d.tar", "application/x-tar", (td / "d.tar").stat().st_size,
                                  lambda: shutil.rmtree(td, ignore_errors=True))
                except BaseException:
                    shutil.rmtree(td, ignore_errors=True)
                    raise
        m = _FILE.match(path)
        if m:
            did, ver, fp = (unquote(g) for g in m.groups())
            svc.store._check_path(fp)          # '..'·절대 경로·역슬래시는 400(HTTP.md). 그 밖에 manifest에 없는 경로는 404
            with download_slot():
                p, size = svc.verified_file(did, ver, fp)
                return stream(start_response, p, "application/octet-stream", size, lambda: None)
        raise BoundaryError("NOT_FOUND", "경로가 없다")

    def app(environ, start_response):
        status = []

        def sr(st, headers, exc_info=None):
            status.append(st.split(" ", 1)[0])
            return start_response(st, headers, exc_info)
        try:
            out = dispatch(environ, sr)
        except BoundaryError as e:
            out = fail(sr, e)
        except Exception as e:
            svc.log(f"내부 오류 {type(e).__name__}")
            out = fail(sr, BoundaryError("UNAVAILABLE", "서비스 내부 오류"))
        svc.log(f"{environ['REQUEST_METHOD']} {environ['PATH_INFO']} {status[0] if status else '-'}")
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
                      max_publishes=int(env.get("DATASET_STORE_MAX_PUBLISHES", 8)),
                      max_downloads=int(env.get("DATASET_STORE_MAX_DOWNLOADS", 8)),
                      max_entries=int(env.get("DATASET_STORE_MAX_ENTRIES", 1000)),
                      auth_fail_limit=int(env.get("DATASET_STORE_AUTH_FAIL_LIMIT", 10)),
                      min_free_gb=float(env.get("DATASET_STORE_MIN_FREE_GB", 1)))
        srv = make_server(svc, env.get("DATASET_STORE_HOST", "0.0.0.0"), int(env.get("DATASET_STORE_PORT", 8080)),
                          threads=int(env.get("DATASET_STORE_THREADS", DEFAULT_THREADS)),
                          connection_limit=int(env.get("DATASET_STORE_MAX_CONNECTIONS", DEFAULT_CONNECTIONS)),
                          channel_timeout=float(env.get("DATASET_STORE_SOCKET_TIMEOUT", DEFAULT_IDLE_TIMEOUT)),
                          drain_grace=float(env.get("DATASET_STORE_DRAIN_GRACE", DEFAULT_DRAIN_GRACE)))
    except (ValueError, OSError, SecretError, BoundaryError) as e:
        print(f"시작 실패: {type(e).__name__}: {e}", file=sys.stderr, flush=True)
        return 2

    def _stop(signum, frame):
        srv._stop.set()                  # 루프가 알아채고 진행 중 요청을 마친 뒤 돌아온다
    try:
        signal.signal(signal.SIGTERM, _stop)
        signal.signal(signal.SIGINT, _stop)
    except ValueError:
        pass
    print(f"dataset-store 시작 포트 {srv.server_address[1]}", flush=True)
    try:
        srv.serve_forever()
    finally:
        srv.server_close()
        shutil.rmtree(svc.tmp, ignore_errors=True)
    return 0
