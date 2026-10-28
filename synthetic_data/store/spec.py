"""output.store 설정의 해석과 저장소 만들기. 잡(run)과 게시기(import)가 같은 것을 쓴다.

kind: file(root) | memory | http(base_url, token_env, timeout). file·memory는 로컬 개발용이고, 운영에서 dataset-store(I2 서버)로
게시할 때는 http다(D100, CR-D26). http의 쓰기 토큰은 token_env 이름으로 boundary_contracts.read_secret(D84)이 읽는다:
`<token_env>_FILE`이 가리키는 파일의 내용(토큰 값 하나)이 우선이고, 없으면 환경 변수 `<token_env>`(개발·시험용)."""
from __future__ import annotations

from typing import Callable, Optional

from boundary_contracts import SecretError, read_secret

DEFAULT_TOKEN_ENV = "DATASET_STORE_WRITE_TOKEN"     # 서버의 DATASET_STORE_WRITE_TOKENS(목록, 복수형)와 이름이 겹치지 않게 단수형
DEFAULT_TIMEOUT = 60.0     # 게시는 수 MB tar 한 번이다. 읽기 기본(10초)보다 넉넉하게 잡은 시작값, 측정 안 함(ADR 0013)


def parse_store(store: dict, err: Callable[[str], Exception]) -> Optional[dict]:
    """kind를 검증한다. http면 정규화한 설정 dict, 아니면 None(file·memory는 호출자가 기존 방식으로 처리)."""
    kind = store.get("kind")
    if kind not in ("file", "memory", "http"):
        raise err("output.store.kind는 file, memory, http 중 하나")
    if kind == "file" and "root" not in store:
        raise err("file 저장소에는 output.store.root가 필요하다")
    if kind == "http":
        url = store.get("base_url")
        if not isinstance(url, str) or not url.startswith(("http://", "https://")):
            raise err("http 저장소에는 output.store.base_url(http:// 또는 https://)이 필요하다")
        if "token" in store:
            raise err("토큰 값을 설정 파일에 넣지 않는다. output.store.token_env(비밀 이름)을 쓴다(D84)")
        env = store.get("token_env", DEFAULT_TOKEN_ENV)
        to = store.get("timeout", DEFAULT_TIMEOUT)
        if not isinstance(env, str) or not env or isinstance(to, bool) or not isinstance(to, (int, float)) or to <= 0:
            raise err("output.store.token_env는 비밀 이름, timeout은 양수 초")
        return {"kind": "http", "base_url": url, "token_env": env, "timeout": float(to)}
    return None


def build_http_store(spec: dict, err: Callable[[str], Exception]):
    try:
        tok = read_secret(spec["token_env"])
    except SecretError as e:
        raise err(str(e)) from None       # 메시지에는 이름·경로만 있다
    if not tok:
        raise err(f"쓰기 토큰 {spec['token_env']}이(가) 없다: {spec['token_env']}_FILE(파일 경로) 또는 {spec['token_env']}(개발용)를 설정한다")
    from boundary_contracts.clients import HttpDatasetStore
    return HttpDatasetStore(spec["base_url"], tok, spec["timeout"])
