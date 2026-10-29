#!/usr/bin/env bash
# 실제 도커로 scripts/build-image.sh를 한 번 돌려 결과 JSON과 라벨을 확인한다(U42 스모크). 끝나면 이미지를 지운다.
# 필요한 환경 변수: SMOKE_BC_SRC(boundary-contracts 해당 태그 소스 트리), SMOKE_SS_SRC(문진 스키마 디렉터리), SMOKE_BC_VERSION(vX.Y.Z), SMOKE_SS_VERSION(vX.Y.Z)
# 왜 인자로 받나: 이웃 리포 경로를 이 스크립트에 적지 않는다(구조 규칙 1). 보통 deploy가 태그에서 꺼내 준다.
set -euo pipefail
cd "$(dirname "$0")/.."
: "${SMOKE_BC_SRC:?}" "${SMOKE_SS_SRC:?}" "${SMOKE_BC_VERSION:?}" "${SMOKE_SS_VERSION:?}"
TAG="synthetic-data-dataset-store:build-image-smoke-$$"
REQ="$(mktemp)"; trap 'rm -f "$REQ"; ${DOCKER:-docker} rmi "$TAG" >/dev/null 2>&1 || true' EXIT
python3 - "$REQ" "$PWD" "$(git rev-parse --short HEAD)" "$TAG" <<'PY'
import json, os, sys
req = {"source_dir": sys.argv[2], "revision": sys.argv[3], "image_tag": sys.argv[4],
       "versions": {"boundary": os.environ["SMOKE_BC_VERSION"], "survey_schema": os.environ["SMOKE_SS_VERSION"]},
       "dependency_sources": {"boundary": os.environ["SMOKE_BC_SRC"], "survey_schema": os.environ["SMOKE_SS_SRC"]}}
open(sys.argv[1], "w").write(json.dumps(req))
PY
bash scripts/build-image.sh "$REQ" | tail -1
