# 기반 이미지는 digest 로 고정한다(공통 규칙 '빌드 때 고정'). 태그는 읽기 쉬우라고 남기며 digest 가 있으면 docker 는 digest 만 쓴다.
# 값: 2026-11-05 이 PC 에서 `docker pull <태그>` 로 받은 뒤 `docker image inspect --format '{{index .RepoDigests 0}}' <태그>` 로 읽은 멀티 아키텍처 index digest 다(이 PC 에 이미 있던 python:3.12-slim 의 값, 태그 시각 2026-10-31).
# 올리는 방법: 새 태그를 `docker pull` 하고 같은 명령으로 digest 를 다시 읽어 아래 ARG 한 곳만 바꾼 뒤 이미지 시험·스모크를 다시 돌린다. 레지스트리의 태그가 움직여도 이 digest 는 그대로다(자동으로 보안 갱신을 받지 않는 대가).
ARG PYTHON_IMAGE=python:3.12-slim@sha256:aa943ce411423c7582288f18707ff66eddcbaeb510502d747a72aeb34f30d159
# dataset-store 서비스(I2 서버, D100). 생성·게시 잡(run-once)은 이미지가 아니라 requirements.lock 환경이다(D22).
# 통신 기반 openit-link(D118)는 requirements.lock의 태그로 wheel을 만들어 wheels 컨텍스트로 받는다(LINK_SPEC=/wheels/<wheel>; 계약 wheel과 같은 방식).
# 문진 스키마는 복사본을 리포지토리에 두지 않으므로 빌드 컨텍스트로 받는다(ADR 0011):
#   docker build --ssh default --build-context survey_schema=../survey-service/schema \
#     --build-arg LINK_SPEC="$(grep ^openit-link requirements.lock)" \
#     --build-arg BC_SPEC="$(grep ^boundary-contracts requirements.lock)" --build-arg BC_VERSION="$(grep -o '@v.*' requirements.lock | tr -d @)" --build-arg SURVEY_SCHEMA_VERSION=$(cat ../survey-service/schema/CONTRACT_VERSION) -t synthetic-data-dataset-store:dev .
# 로컬 확인(ssh 없이): scripts/smoke_service.sh
FROM scratch AS wheels
# 기본은 빈 컨텍스트. 로컬 확인에서는 --build-context wheels=<태그에서 만든 wheel 폴더> 로 바꾼다.
FROM scratch AS survey_schema
# 기본은 빈 컨텍스트(빌드 인자 없으면 빌드가 CONTRACT_VERSION 없음으로 실패한다).

FROM ${PYTHON_IMAGE} AS build
# 정본은 requirements.lock의 boundary-contracts 줄이다. 빌드 인자로 받고 여기에 값을 적지 않는다.
ARG BC_SPEC
ARG LINK_SPEC
RUN apt-get update && apt-get install -y --no-install-recommends git openssh-client && rm -rf /var/lib/apt/lists/* \
 && mkdir -p -m 0700 /root/.ssh && (ssh-keyscan github.com >> /root/.ssh/known_hosts 2>/dev/null || true)
RUN python -m venv /opt/venv
COPY requirements-service.txt /tmp/requirements-service.txt
RUN --mount=type=ssh --mount=type=bind,from=wheels,target=/wheels \
    /opt/venv/bin/pip install --no-cache-dir -r /tmp/requirements-service.txt "${BC_SPEC}" \
 && /opt/venv/bin/pip install --no-cache-dir --no-deps "${LINK_SPEC}"      # --no-deps: link의 계약 의존(git+ssh 직접 URL)이 위의 BC_SPEC와 겹쳐 충돌하지 않게

FROM ${PYTHON_IMAGE}
# 왜: 값 없음의 표기는 n/a 하나다(계약 ImageLabels, D108). revision은 hex만 허용되므로 기본값 그대로(n/a) 빌드하면 아래 검사가 멈춘다.
ARG REVISION=n/a
ARG BC_VERSION=n/a
ARG SURVEY_SCHEMA_VERSION=n/a
RUN printf '%s' "${REVISION}" | grep -Eq '^[0-9a-f]{7,40}$' || { echo "REVISION은 소스 커밋 hex(7~40자)여야 한다(--build-arg REVISION=...)" >&2; exit 1; }
# 왜 restic을 apt로: 백업·복구 잡(RUNTIME R10.1, 저장소 프로토콜 restic REST)이 부르는 도구이고, Debian 공식 패키지가 표준 설치 경로다. 정확한 버전을 고정한다(잠금 파일 원칙; 값은 Debian 13 저장소의 현재 버전).
ARG RESTIC_DEB_VERSION=0.18.0-1+b4
RUN apt-get update && apt-get install -y --no-install-recommends "restic=${RESTIC_DEB_VERSION}" && rm -rf /var/lib/apt/lists/*
COPY --from=build /opt/venv /opt/venv
WORKDIR /app
COPY synthetic_data /app/synthetic_data
COPY --from=survey_schema CONTRACT_VERSION /app/survey_schema/CONTRACT_VERSION
COPY --from=survey_schema schemas /app/survey_schema/schemas
RUN useradd --uid 10001 --no-create-home --shell /usr/sbin/nologin dataset && mkdir /data && chown dataset /data \
 && find /app -name __pycache__ -prune -exec rm -rf {} +
ENV PATH=/opt/venv/bin:$PATH PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 DATASET_STORE_ROOT=/data DATASET_STORE_PORT=8080
VOLUME /data
USER 10001
EXPOSE 8080
# 왜: 포트는 DATASET_STORE_PORT로 바뀔 수 있어 HEALTHCHECK도 같은 변수를 읽는다(기본 8080, 계약 DatasetStoreEnv). 0(빈 포트)은 컨테이너에서 쓰지 않는다.
HEALTHCHECK --interval=15s --timeout=3s CMD python -c "import os, urllib.request as u; u.urlopen('http://127.0.0.1:%s/healthz' % os.environ.get('DATASET_STORE_PORT', '8080'), timeout=2)"
LABEL io.openit.service="dataset-store" \
      io.openit.revision="${REVISION}" \
      io.openit.contracts.boundary="${BC_VERSION}" \
      io.openit.contracts.survey-schema="${SURVEY_SCHEMA_VERSION}" \
      io.openit.model-runtime="n/a"
CMD ["python", "-m", "synthetic_data.service"]
