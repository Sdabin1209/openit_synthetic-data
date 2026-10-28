#!/bin/sh
# 이미지를 빌드해 띄우고 /healthz, /readyz, 권한, 게시(POST)와 조회를 확인한다. 고정 포트를 쓰지 않는다(Docker가 배정, D22).
# 환경 변수: SMOKE_WHEELS(boundary-contracts wheel 폴더, 기본 ../model-lab/vendor/wheels), SMOKE_BC_VERSION(기본 requirements.lock의 boundary-contracts 태그),
#            SURVEY_SCHEMA(기본 ../survey-service/schema; 읽기만 한다)
set -eu
cd "$(dirname "$0")/.."
BC_VER=${SMOKE_BC_VERSION:-$(grep ^boundary-contracts requirements.lock | sed "s/.*@v//")}
WHEELS=${SMOKE_WHEELS:-../model-lab/vendor/wheels}
SCHEMA=${SURVEY_SCHEMA:-../survey-service/schema}
WHL=$(ls "$WHEELS"/boundary_contracts-"$BC_VER"-*.whl | head -1)
TAG="synthetic-data-dataset-store:smoke-$$"
NAME="synthetic-data-dataset-store-smoke-$$"
SECRETS=$(mktemp -d)
trap 'rm -rf "$SECRETS"; docker rm -f "$NAME" >/dev/null 2>&1 || true; docker volume rm "$NAME-data" >/dev/null 2>&1 || true; docker rmi "$TAG" >/dev/null 2>&1 || true' EXIT
# wheel 폴더 전체가 아니라 고른 wheel 하나만 컨텍스트로 준다
WCTX=$(mktemp -d); cp "$WHL" "$WCTX"/; trap 'rm -rf "$WCTX"; rm -rf "$SECRETS"; docker rm -f "$NAME" >/dev/null 2>&1 || true; docker volume rm "$NAME-data" >/dev/null 2>&1 || true; docker rmi "$TAG" >/dev/null 2>&1 || true' EXIT
docker build -q --build-context wheels="$WCTX" --build-context survey_schema="$SCHEMA" \
  --build-arg "BC_SPEC=/wheels/$(basename "$WHL")" --build-arg "BC_VERSION=v$BC_VER" --build-arg "SURVEY_SCHEMA_VERSION=$(tr -d ' \n' < "$SCHEMA/CONTRACT_VERSION")" \
  --build-arg "REVISION=$(git rev-parse --short HEAD 2>/dev/null || echo unknown)" -t "$TAG" .
docker volume create "$NAME-data" >/dev/null
# 토큰은 환경 변수가 아니라 파일로 준다(D84). 시험 전용 무작위 값이고 끝나면 버려진다.
RT=$(od -An -N24 -tx1 /dev/urandom | tr -d ' \n'); WT=$(od -An -N24 -tx1 /dev/urandom | tr -d ' \n')
printf 'model-lab=%s\n' "$RT" > "$SECRETS/read"; printf 'synthetic-data=%s\n' "$WT" > "$SECRETS/write"
chmod 755 "$SECRETS"; chmod 644 "$SECRETS"/*
docker run -d --name "$NAME" -p 127.0.0.1::8080 -v "$NAME-data":/data -v "$SECRETS":/run/secrets:ro \
  -e DATASET_STORE_READ_TOKENS_FILE=/run/secrets/read -e DATASET_STORE_WRITE_TOKENS_FILE=/run/secrets/write "$TAG" >/dev/null
PORT=$(docker port "$NAME" 8080/tcp | head -1 | sed 's/.*://')
URL="http://127.0.0.1:$PORT"
for i in $(seq 1 30); do curl -fsS "$URL/healthz" >/dev/null 2>&1 && break; sleep 1; done
echo "healthz: $(curl -fsS "$URL/healthz")"
echo "readyz: $(curl -fsS "$URL/readyz")"
echo "user: $(docker exec "$NAME" id -u)"
echo "labels: $(docker inspect -f '{{json .Config.Labels}}' "$TAG")"
[ "$(curl -s -o /dev/null -w '%{http_code}' "$URL/v1/datasets")" = 403 ]
[ "$(curl -s -o /dev/null -w '%{http_code}' -H "Authorization: Bearer $RT" "$URL/v1/datasets")" = 200 ]
[ "$(curl -s -o /dev/null -w '%{http_code}' -X POST -H "Authorization: Bearer $RT" --data-binary x "$URL/v1/datasets")" = 403 ]
# 게시와 조회(계약 클라이언트로). 개발 환경(.venv)의 boundary_contracts를 쓴다.
.venv/bin/python scripts/smoke_client.py "$URL" "$WT" "$RT"
docker logs "$NAME" 2>&1 | sh scripts/assert_no_secret.sh "$RT" "$WT"
echo SMOKE_OK
