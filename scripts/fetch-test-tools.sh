#!/usr/bin/env bash
# 백업·복구 시험이 쓰는 restic과 restic-rest-server를 Debian 공식 패키지(이미지 python:3.12-slim 의 apt)에서 받아 build/tools/ 에 푼다.
# 왜: 이 머신에 root 가 없고 두 도구는 파이썬 패키지가 아니다. 이미지의 restic 과 같은 출처(Debian apt)라 시험이 쓰는 restic 이 배포되는 restic 이다.
# 사용: scripts/fetch-test-tools.sh   그다음 PATH="$PWD/build/tools/usr/bin:$PATH" .venv/bin/python -m pytest
set -euo pipefail
cd "$(dirname "$0")/.."
OUT="$PWD/build/tools"; mkdir -p "$OUT/debs"
docker run --rm -v "$OUT/debs":/debs -w /debs python:3.12-slim bash -c 'apt-get update -qq >/dev/null && apt-get download -qq restic restic-rest-server; chown -R '"$(id -u)"':'"$(id -g)"' /debs'
for d in "$OUT"/debs/*.deb; do dpkg -x "$d" "$OUT"; done
"$OUT/usr/bin/restic" version >&2
[ -x "$OUT/usr/bin/restic-rest-server" ] && echo "restic-rest-server: ok" >&2 || { echo "restic-rest-server 없음" >&2; ls "$OUT/usr/bin" >&2; exit 1; }
