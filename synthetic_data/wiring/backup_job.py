"""백업·복구 잡 연결(RUNTIME R10.1): 환경(CommonEnv OPENIT_BACKUP_*, OPENIT_EGRESS_PROXY)과 비밀 파일에서 입력을 만들어 컴포넌트에 넘긴다. 판정하지 않는다.
데이터는 서비스가 쓰는 볼륨(datasets-data)과 같은 컨테이너 경로(DATASET_STORE_ROOT, 기본 /data)다. 요청 임시 폴더 .tmp 는 서비스가 시작할 때 지우는 값이라 백업하지 않는다."""
from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Mapping
from urllib.parse import urlsplit

from boundary_contracts import SecretError, read_secret, secret_format_problems

from ..components import backup_job
from ..config import ConfigError

EXCLUDE = [".tmp"]    # 근거: components/link_dataset_store_server.py 의 요청 임시 폴더(재시작 때 지운다)


def _required(env: Mapping[str, str], name: str) -> str:
    v = env.get(name)
    if not v:
        raise ConfigError(f"{name}이 필요하다(CommonEnv)")
    return v


def build_input(mode: str, env: Mapping[str, str] = os.environ) -> dict:
    url = _required(env, "OPENIT_BACKUP_URL")
    if urlsplit(url).scheme != "https":
        raise ConfigError("OPENIT_BACKUP_URL은 https여야 한다(CommonEnv)")
    try:
        cred = read_secret("OPENIT_BACKUP_CREDENTIALS", environ=env)
    except SecretError as e:
        raise ConfigError("OPENIT_BACKUP_CREDENTIALS_FILE을 읽지 못했다") from e
    # 왜 계약 함수: 자격 파일의 형식 문법은 계약이 정한다(secret_format_problems credentials_line, 계약 5.0.1, D117)
    if not cred or secret_format_problems("credentials_line", cred.strip()):
        raise ConfigError("OPENIT_BACKUP_CREDENTIALS_FILE의 내용은 한 줄 '<사용자>:<암호>'여야 한다(RFC 7617)")
    user, _, password = cred.strip().partition(":")
    return {"mode": mode, "data_dir": env.get("DATASET_STORE_ROOT", "/data"), "exclude": list(EXCLUDE),
            "repository": "rest:" + url, "password_file": _required(env, "OPENIT_BACKUP_REPO_PASSWORD_FILE"),
            "rest_user": user, "rest_password": password, "proxy": _required(env, "OPENIT_EGRESS_PROXY")}


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")     # 실제 시계는 wiring 에서만 읽는다


def run(mode: str, env: Mapping[str, str] = os.environ, clock=_utc_now) -> dict:
    return backup_job.run(build_input(mode, env), clock=clock)
