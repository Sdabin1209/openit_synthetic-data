#!/bin/sh
# deploy 와 같은 실행 조건으로 띄운다(읽기 전용 루트, /tmp tmpfs, cap_drop ALL, no-new-privileges, 쓸 수 있는 경로는 deploy compose 와 같게): 2026-11-06 E2E 기동에서야 드러난 쓰기 경로 결함을 스모크에서 잡는다
# 이미지를 빌드해 띄우고 /healthz, /readyz, 권한, 게시(POST)와 조회를 확인한다. 고정 포트를 쓰지 않는다(Docker가 배정, D22).
# boundary-contracts wheel은 이웃 폴더가 아니라 requirements.lock이 고정한 태그에서 `pip wheel`로 만든다(git SSH 접근 필요).
# 환경 변수: SMOKE_WHEELS(미리 만든 wheel 폴더. 없으면 태그에서 만든다), SMOKE_BC_VERSION(기본 requirements.lock의 boundary-contracts 태그),
#            SURVEY_SCHEMA(기본: 설치된 survey_schema 패키지의 v1; 읽기만 한다)
set -eu
# 실패하면 컨테이너를 지우기 전에 상태와 로그를 남긴다(정리 순서 결함 수정 2026-11-03: 지우고 나면 실패 원인을 볼 수 없다).
# inspect 는 State 만 낸다(전체 inspect 는 환경 변수가 섞인다).
smoke_diag() {
  local rc=$1; shift
  [ "$rc" -eq 0 ] && return 0
  for c in "$@"; do
    [ -n "$c" ] || continue
    docker inspect "$c" >/dev/null 2>&1 || continue
    echo "=== 실패(종료 코드 $rc): 컨테이너 $c 진단 ===" >&2
    docker inspect -f 'status={{.State.Status}} exit={{.State.ExitCode}} oom={{.State.OOMKilled}} error={{.State.Error}} started={{.State.StartedAt}} finished={{.State.FinishedAt}}' "$c" >&2 || true
    docker logs --tail 100 "$c" >&2 2>&1 || true
  done
}
cd "$(dirname "$0")/.."
. scripts/docker-env.sh; docker_env_setup      # 전역 ~/.docker 의 자격 도우미에 기대지 않는다(scripts/docker-env.sh)
BC_VER=${SMOKE_BC_VERSION:-$(grep ^boundary-contracts requirements.lock | sed "s/.*@v//")}
# 문진 스키마는 설치된 survey_schema 패키지(판은 requirements.lock 의 태그)에서 꺼낸다. 이웃 리포 작업 폴더를 읽지 않는다(헤드 점검 2026-11-05)
SCHEMA=${SURVEY_SCHEMA:-$(.venv/bin/python -c 'import survey_schema,pathlib;print(pathlib.Path(survey_schema.__file__).resolve().parent/"v1")')}
[ -d "$SCHEMA/schemas" ] || { echo "smoke: 문진 스키마를 찾지 못했다($SCHEMA). bash scripts/setup-env.sh 로 survey_schema 를 설치한다" >&2; exit 2; }
if [ -n "${SMOKE_WHEELS:-}" ]; then
  WHL=$(ls "$SMOKE_WHEELS"/boundary_contracts-"$BC_VER"-*.whl | head -1)
else
  # 왜: 태그에서 wheel을 만드는 것이 pip의 표준 경로이고(`pip wheel`), 이웃 영역이 보관하는 폴더 배치에 기대지 않으며 lock의 태그와 이미지가 어긋나지 않는다.
  BUILT=$(mktemp -d); trap 'rm -rf "$BUILT"' EXIT
  .venv/bin/python -m pip wheel -q --no-deps --disable-pip-version-check -w "$BUILT" "$(grep ^boundary-contracts requirements.lock)"
  WHL=$(ls "$BUILT"/boundary_contracts-*.whl | head -1)
fi
# 통신 기반 openit-link(D118)도 잠금 파일의 태그에서 wheel로 만든다(--no-deps: 계약은 위 wheel을 쓴다)
LBUILT=$(mktemp -d)
.venv/bin/python -m pip wheel -q --no-deps --disable-pip-version-check -w "$LBUILT" "$(grep ^openit-link requirements.lock)"
LWHL=$(ls "$LBUILT"/openit_link-*.whl | head -1)
TAG="synthetic-data-dataset-store:smoke-$$"
NAME="synthetic-data-dataset-store-smoke-$$"
SECRETS=$(mktemp -d)
trap 'smoke_diag $? "$NAME"; rm -rf "${BUILT:-}" "${LBUILT:-}" "$SECRETS"; docker rm -f "$NAME" >/dev/null 2>&1 || true; docker volume rm "$NAME-data" >/dev/null 2>&1 || true; docker rmi "$TAG" >/dev/null 2>&1 || true' EXIT
# wheel 폴더 전체가 아니라 고른 wheel 하나만 컨텍스트로 준다
WCTX=$(mktemp -d); cp "$WHL" "$LWHL" "$WCTX"/; trap 'smoke_diag $? "$NAME"; rm -rf "${BUILT:-}" "${LBUILT:-}" "$WCTX" "$SECRETS"; docker rm -f "$NAME" >/dev/null 2>&1 || true; docker volume rm "$NAME-data" >/dev/null 2>&1 || true; docker rmi "$TAG" >/dev/null 2>&1 || true' EXIT
docker build -q --build-context wheels="$WCTX" --build-context survey_schema="$SCHEMA" \
  --build-arg "BC_SPEC=/wheels/$(basename "$WHL")" --build-arg "LINK_SPEC=/wheels/$(basename "$LWHL")" --build-arg "BC_VERSION=v$BC_VER" --build-arg "SURVEY_SCHEMA_VERSION=$(sed -n 's/^openit-survey-schema @ .*@survey-schema-v\([0-9][0-9]*\)\..*/\1/p' requirements.lock)" \
  --build-arg "REVISION=$(git rev-parse --short HEAD)" -t "$TAG" .
docker volume create "$NAME-data" >/dev/null
# 토큰은 환경 변수가 아니라 파일로 준다(D84). 시험 전용 무작위 값이고 끝나면 버려진다.
RT=$(od -An -N24 -tx1 /dev/urandom | tr -d ' \n'); WT=$(od -An -N24 -tx1 /dev/urandom | tr -d ' \n')
printf 'model-lab=%s\n' "$RT" > "$SECRETS/read"; printf 'synthetic-data=%s\n' "$WT" > "$SECRETS/write"
chmod 755 "$SECRETS"; chmod 644 "$SECRETS"/*
docker run -d --name "$NAME" --read-only --tmpfs /tmp --cap-drop ALL --security-opt no-new-privileges:true -p 127.0.0.1::8080 -v "$NAME-data":/data -v "$SECRETS":/run/secrets:ro \
  -e DATASET_STORE_READ_TOKENS_FILE=/run/secrets/read -e DATASET_STORE_WRITE_TOKENS_FILE=/run/secrets/write "$TAG" >/dev/null
PORT=$(docker port "$NAME" 8080/tcp | head -1 | sed 's/.*://')
URL="http://127.0.0.1:$PORT"
for i in $(seq 1 30); do curl -fsS "$URL/healthz" >/dev/null 2>&1 && break; sleep 1; done
echo "healthz: $(curl -fsS "$URL/healthz")"
echo "readyz: $(curl -fsS "$URL/readyz")"
echo "user: $(docker exec "$NAME" id -u)"
echo "restic: $(docker exec "$NAME" restic version | cut -c1-40)"      # 백업·복구 잡(dataset-backup, dataset-restore)이 부르는 도구가 이미지에 있다
echo "labels: $(docker inspect -f '{{json .Config.Labels}}' "$TAG")"
[ "$(curl -s -o /dev/null -w '%{http_code}' "$URL/v1/datasets")" = 401 ]
curl -s -i "$URL/v1/datasets" | grep -qi "^www-authenticate: Bearer"
[ "$(curl -s -o /dev/null -w '%{http_code}' -H "Authorization: Bearer $RT" "$URL/v1/datasets")" = 200 ]
[ "$(curl -s -o /dev/null -w '%{http_code}' -X POST -H "Authorization: Bearer $RT" --data-binary x "$URL/v1/datasets")" = 403 ]
# 게시와 조회(계약 클라이언트로). 개발 환경(.venv)의 boundary_contracts를 쓴다.
.venv/bin/python scripts/smoke_client.py "$URL" "$WT" "$RT"
docker logs "$NAME" 2>&1 | sh scripts/assert_no_secret.sh "$RT" "$WT"
echo SMOKE_OK
