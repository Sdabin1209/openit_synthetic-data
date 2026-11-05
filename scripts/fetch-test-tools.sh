#!/usr/bin/env bash
# 백업·복구 시험이 쓰는 restic과 restic-rest-server를 Debian 공식 패키지(이미지와 같은 python 기반 이미지의 apt)에서 받아 build/tools/ 에 푼다.
# scripts/setup-env.sh 가 부른다(표준 설치가 시험 의존까지 받는다). 시험은 PATH 에 build/tools/usr/bin 을 스스로 더해 찾는다(tests/conftest.py).
# 왜: 이 머신에 root 가 없고 두 도구는 파이썬 패키지가 아니다. 이미지의 restic 과 같은 출처(Debian apt)·같은 버전이라 시험이 쓰는 restic 이 배포되는 restic 이다.
# 버전 고정: restic 은 Dockerfile 의 RESTIC_DEB_VERSION(이미지와 같은 값, 한 곳), restic-rest-server 는 아래 상수(시험 전용이라 이미지에 없다).
# 기반 이미지도 Dockerfile 의 PYTHON_IMAGE(digest 고정)를 그대로 쓴다. 멱등: 같은 버전이 이미 풀려 있으면 아무것도 받지 않는다.
set -euo pipefail
cd "$(dirname "$0")/.."
. scripts/docker-env.sh; docker_env_setup      # 전역 ~/.docker 의 자격 도우미에 기대지 않는다
REST_SERVER_DEB_VERSION=0.13.0-2
RESTIC_DEB_VERSION="$(sed -n 's/^ARG RESTIC_DEB_VERSION=//p' Dockerfile)"
PYTHON_IMAGE="$(sed -n 's/^ARG PYTHON_IMAGE=//p' Dockerfile)"
[ -n "$RESTIC_DEB_VERSION" ] && [ -n "$PYTHON_IMAGE" ] || { echo "fetch-test-tools: Dockerfile에서 RESTIC_DEB_VERSION·PYTHON_IMAGE를 읽지 못했다" >&2; exit 1; }
command -v docker >/dev/null 2>&1 || { echo "fetch-test-tools: docker가 필요하다(Debian 공식 패키지를 받는 표준 경로)" >&2; exit 1; }
OUT="$PWD/build/tools"; WANT="restic=$RESTIC_DEB_VERSION restic-rest-server=$REST_SERVER_DEB_VERSION"
if [ -x "$OUT/usr/bin/restic" ] && [ -x "$OUT/usr/bin/restic-rest-server" ] && [ "$(cat "$OUT/.versions" 2>/dev/null)" = "$WANT" ]; then
  echo "fetch-test-tools: 이미 있다($WANT)" >&2; exit 0
fi
rm -rf "$OUT"; mkdir -p "$OUT/debs"
docker run --rm -v "$OUT/debs":/debs -w /debs "$PYTHON_IMAGE" bash -c "apt-get update -qq >/dev/null && apt-get download -qq restic=$RESTIC_DEB_VERSION restic-rest-server=$REST_SERVER_DEB_VERSION; chown -R '$(id -u)':'$(id -g)' /debs" >&2
for d in "$OUT"/debs/*.deb; do dpkg -x "$d" "$OUT"; done
"$OUT/usr/bin/restic" version >&2
[ -x "$OUT/usr/bin/restic-rest-server" ] || { echo "fetch-test-tools: restic-rest-server 없음" >&2; ls "$OUT/usr/bin" >&2; exit 1; }
printf '%s' "$WANT" >"$OUT/.versions"
echo "fetch-test-tools: 완료($WANT)" >&2
