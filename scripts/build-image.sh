#!/usr/bin/env bash
# 영역 빌드 진입점(계약 v2.5.0 BuildImageRequest/BuildImageResult, OPEN_GAPS U42, ADR 0018).
# 사용: bash scripts/build-image.sh <요청 JSON 파일>   (영역 리포 루트에서)
# 결과: 표준 출력 마지막 줄에 BuildImageResult JSON 한 줄. 진행 기록은 표준 오류. 종료 0 성공.
# 환경 변수: DOCKER(기본 docker), PYTHON(기본: 리포의 .venv/bin/python, 없으면 python3. boundary_contracts가 설치돼 있어야 한다)
set -euo pipefail
[ $# -eq 1 ] || { echo "사용: bash scripts/build-image.sh <요청 JSON 파일>" >&2; exit 2; }
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DOCKER="${DOCKER:-docker}"
PY="${PYTHON:-}"; [ -n "$PY" ] || { [ -x "$HERE/.venv/bin/python" ] && PY="$HERE/.venv/bin/python" || PY=python3; }

# 1. 요청 검증(계약 validator). 값은 요청에서만 온다: 이 스크립트에 버전 기본값이 없다
REQ="$("$PY" -I "$HERE/scripts/build_image_request.py" "$1")" || { echo "build-image: 요청 검증 실패" >&2; exit 2; }
mapfile -t R <<<"$REQ"
SRC="${R[0]}"; REV="${R[1]}"; BC="${R[2]}"; SS="${R[3]}"; BC_SRC="${R[4]}"; SS_SRC="${R[5]}"; TAG="${R[6]}"
[ -d "$SRC" ] && [ -f "$SRC/Dockerfile" ] || { echo "build-image: source_dir에 Dockerfile이 없다" >&2; exit 2; }
[ -f "$BC_SRC/pyproject.toml" ] || { echo "build-image: dependency_sources.boundary에 pyproject.toml이 없다" >&2; exit 2; }
[ -f "$SS_SRC/CONTRACT_VERSION" ] && [ -d "$SS_SRC/schemas" ] || { echo "build-image: dependency_sources.survey_schema가 문진 스키마 디렉터리(CONTRACT_VERSION, schemas/)가 아니다" >&2; exit 2; }

# 2. 계약 wheel을 소스 트리에서 만든다(빌드 중 SSH·이웃 리포 경로 없이). 소스 트리를 더럽히지 않게 사본에서 빌드한다
WORK="$(mktemp -d)"; trap 'rm -rf "$WORK"' EXIT
mkdir "$WORK/bc" "$WORK/wheels"; cp -a "$BC_SRC/." "$WORK/bc/"
echo "build-image: 계약 wheel 만들기 ($BC)" >&2
"$PY" -m pip wheel -q --no-deps --disable-pip-version-check -w "$WORK/wheels" "$WORK/bc" >&2
WHL="$(basename "$(ls "$WORK"/wheels/boundary_contracts-*.whl | head -1)")"

# 라벨 정직성(U50): 라벨은 요청 값을 적지 않고 실제로 설치·사용한 버전에서 찍는다. 요청 버전이 이 리포의 고정 버전(requirements.lock)이나
# 실제 소스와 다르면 라벨을 찍지 않고 멈춘다(거짓 라벨이 게시 단계까지 가지 않게).
die() { echo "build-image: $*" >&2; exit 2; }
LOCK_BC="$(sed -n 's/^boundary-contracts @ .*@\(v[0-9][0-9.]*\)$/\1/p' "$HERE/requirements.lock")"
LOCK_SS="$(sed -n 's/^openit-survey-schema @ .*@survey-schema-\(v[0-9][0-9.]*\)#.*$/\1/p' "$HERE/requirements.lock")"
[ -n "$LOCK_BC" ] && [ -n "$LOCK_SS" ] || die "requirements.lock에서 고정 버전을 읽지 못했다"
[ "$BC" = "$LOCK_BC" ] || die "요청의 boundary 버전($BC)이 이 리포의 고정 버전($LOCK_BC)과 다르다. 라벨을 찍지 않는다"
[ "$SS" = "$LOCK_SS" ] || die "요청의 survey_schema 버전($SS)이 이 리포의 고정 버전($LOCK_SS)과 다르다. 라벨을 찍지 않는다"
BC_ACTUAL="v$(printf '%s' "$WHL" | sed -n 's/^boundary_contracts-\([0-9][0-9.]*\)-.*/\1/p')"
[ "$BC_ACTUAL" = "$BC" ] || die "dependency_sources.boundary에서 만든 wheel의 버전($BC_ACTUAL)이 요청($BC)과 다르다. 라벨을 찍지 않는다"
# 왜 pyproject의 version인가: 라벨 io.openit.contracts.survey-schema는 문진 스키마 패키지의 주 버전이다(ImageLabels). CONTRACT_VERSION은 런타임 계약의
# 정수 버전이라 다른 개념이다(v2.0.0 패키지의 CONTRACT_VERSION은 1이다).
SS_PKG="$(sed -n 's/^version = "\([0-9][0-9.]*\)"$/\1/p' "$SS_SRC/pyproject.toml" | head -1)"
[ -n "$SS_PKG" ] || die "dependency_sources.survey_schema/pyproject.toml에서 version을 읽지 못했다"
[ "v$SS_PKG" = "$SS" ] || die "dependency_sources.survey_schema의 패키지 버전(v$SS_PKG)이 요청($SS)과 다르다. 라벨을 찍지 않는다"
SS_ACTUAL="${SS_PKG%%.*}"

# 잡 선언(계약 JobsDeclaration)을 라벨 io.openit.jobs로 싣는다: deploy는 argv·비밀 파일 이름·설정 파일 위치를 이 라벨에서 읽는다
JOBS="$("$PY" -I "$HERE/scripts/build_image_request.py" --jobs "$SRC/jobs.json")" || { echo "build-image: jobs.json 검증 실패" >&2; exit 2; }

# 노출 선언(계약 Exposure)을 라벨 io.openit.exposure로 싣는다: 게이트웨이 노출 표. 이 서비스는 게이트웨이 밖으로 내지 않으므로 전부 denied다
EXPOSURE="$("$PY" -I "$HERE/scripts/build_image_request.py" --exposure "$SRC/deploy-exposure.json")" || { echo "build-image: deploy-exposure.json 검증 실패" >&2; exit 2; }

# 3. 빌드. Dockerfile 인자 이름은 이 영역의 것이고 deploy는 모른다
echo "build-image: 이미지 빌드 $TAG" >&2
"$DOCKER" build -q -t "$TAG" --build-context "wheels=$WORK/wheels" --build-context "survey_schema=$SS_SRC" \
  --label "io.openit.jobs=$JOBS" --label "io.openit.exposure=$EXPOSURE" --build-arg "BC_SPEC=/wheels/$WHL" --build-arg "BC_VERSION=$BC_ACTUAL" --build-arg "REVISION=$REV" \
  --build-arg "SURVEY_SCHEMA_VERSION=$SS_ACTUAL" "$SRC" >&2

# 4. 결과: docker가 준 ID와 이미지에 실제로 붙은 io.openit.* 라벨(요청 값을 되풀이하지 않고 inspect로 읽는다)
ID="$("$DOCKER" image inspect -f '{{.Id}}' "$TAG")"
"$DOCKER" image inspect -f '{{json .Config.Labels}}' "$TAG" | "$PY" -I -c '
import json, sys
from boundary_contracts import validator
labels = {k: v for k, v in json.load(sys.stdin).items() if k.startswith("io.openit.")}
res = {"image": sys.argv[1], "image_id": sys.argv[2], "labels": labels}
validator("BuildImageResult").validate(res)
print(json.dumps(res, ensure_ascii=False, sort_keys=True))' "$TAG" "$ID"
