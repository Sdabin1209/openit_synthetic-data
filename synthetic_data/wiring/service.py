"""dataset-store 서비스 연결(I2 서버): 환경 변수 -> 서비스 설정 -> 저장소와 서버를 만들어 잇는다. 비밀은 boundary_contracts.read_secret(D84)으로 읽는다:
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

import os
import shutil
import signal
import sys
from pathlib import Path

from boundary_contracts import BoundaryError, SecretError, read_secret

from ..components.dataset_store import FileDatasetStore
from ..components.link_dataset_store_server import (DEFAULT_CONNECTIONS, DEFAULT_DRAIN_GRACE, DEFAULT_IDLE_TIMEOUT, DEFAULT_THREADS, MIN_TOKEN_LEN,
                                                    Service, check_token_strength, make_server, parse_tokens)
from ..types.schema_registry import check
from .survey import Survey


def main(env=os.environ) -> int:
    try:
        settings = {"read_tokens": read_secret("DATASET_STORE_READ_TOKENS", environ=env) or "",
                    "write_tokens": read_secret("DATASET_STORE_WRITE_TOKENS", environ=env) or "",
                    "min_token_len": int(env.get("DATASET_STORE_MIN_TOKEN_LEN", MIN_TOKEN_LEN)), "root": env.get("DATASET_STORE_ROOT", "/data"),
                    "max_body": int(env.get("DATASET_STORE_MAX_BODY", 1 << 30)), "max_publishes": int(env.get("DATASET_STORE_MAX_PUBLISHES", 8)),
                    "max_downloads": int(env.get("DATASET_STORE_MAX_DOWNLOADS", 8)), "max_entries": int(env.get("DATASET_STORE_MAX_ENTRIES", 1000)),
                    "auth_fail_limit": int(env.get("DATASET_STORE_AUTH_FAIL_LIMIT", 10)), "min_free_gb": float(env.get("DATASET_STORE_MIN_FREE_GB", 1))}
        check("ServiceSettings", settings)      # 토큰이 하나도 없으면(읽기·쓰기 모두 빈 문자열) 여기서 거부한다
        read, write = parse_tokens(settings["read_tokens"]), parse_tokens(settings["write_tokens"])
        check_token_strength({**read, **write}, min_len=settings["min_token_len"])
        survey = Survey(Path(env.get("DATASET_STORE_SURVEY_SCHEMA_DIR", "/app/survey_schema")))
        version = survey.contract_version          # 스키마 디렉터리가 없으면 시작을 거부한다
        root = Path(settings["root"])
        svc = Service(FileDatasetStore(root / "datasets", version), root, read, write, max_body=settings["max_body"],
                      max_publishes=settings["max_publishes"], max_downloads=settings["max_downloads"], max_entries=settings["max_entries"],
                      auth_fail_limit=settings["auth_fail_limit"], min_free_gb=settings["min_free_gb"])
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
