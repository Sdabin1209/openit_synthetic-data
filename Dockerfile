# dataset-store 서비스(I2 서버, D100). 생성·게시 잡(run-once)은 이미지가 아니라 requirements.lock 환경이다(D22).
# 문진 스키마는 복사본을 리포지토리에 두지 않으므로 빌드 컨텍스트로 받는다(ADR 0011):
#   docker build --ssh default --build-context survey_schema=../survey-service/schema \
#     --build-arg BC_SPEC="$(grep ^boundary-contracts requirements.lock)" --build-arg BC_VERSION="$(grep -o '@v.*' requirements.lock | tr -d @)" --build-arg SURVEY_SCHEMA_VERSION=$(cat ../survey-service/schema/CONTRACT_VERSION) -t synthetic-data-dataset-store:dev .
# 로컬 확인(ssh 없이): scripts/smoke_service.sh
FROM scratch AS wheels
# 기본은 빈 컨텍스트. 로컬 확인에서는 --build-context wheels=<태그에서 만든 wheel 폴더> 로 바꾼다.
FROM scratch AS survey_schema
# 기본은 빈 컨텍스트(빌드 인자 없으면 빌드가 CONTRACT_VERSION 없음으로 실패한다).

FROM python:3.12-slim AS build
# 정본은 requirements.lock의 boundary-contracts 줄이다. 빌드 인자로 받고 여기에 값을 적지 않는다.
ARG BC_SPEC
RUN apt-get update && apt-get install -y --no-install-recommends git openssh-client && rm -rf /var/lib/apt/lists/* \
 && mkdir -p -m 0700 /root/.ssh && (ssh-keyscan github.com >> /root/.ssh/known_hosts 2>/dev/null || true)
RUN python -m venv /opt/venv
COPY requirements-service.txt /tmp/requirements-service.txt
RUN --mount=type=ssh --mount=type=bind,from=wheels,target=/wheels \
    /opt/venv/bin/pip install --no-cache-dir -r /tmp/requirements-service.txt "${BC_SPEC}"

FROM python:3.12-slim
# 왜: 값 없음의 표기는 n/a 하나다(계약 ImageLabels, D108). revision은 hex만 허용되므로 기본값 그대로(n/a) 빌드하면 아래 검사가 멈춘다.
ARG REVISION=n/a
ARG BC_VERSION=n/a
ARG SURVEY_SCHEMA_VERSION=n/a
RUN printf '%s' "${REVISION}" | grep -Eq '^[0-9a-f]{7,40}$' || { echo "REVISION은 소스 커밋 hex(7~40자)여야 한다(--build-arg REVISION=...)" >&2; exit 1; }
COPY --from=build /opt/venv /opt/venv
WORKDIR /app
COPY synthetic_data /app/synthetic_data
COPY --from=survey_schema CONTRACT_VERSION /app/survey_schema/CONTRACT_VERSION
COPY --from=survey_schema schemas /app/survey_schema/schemas
RUN useradd --uid 10001 --no-create-home --shell /usr/sbin/nologin dataset && mkdir /data && chown dataset /data \
 && find /app -name __pycache__ -prune -exec rm -rf {} +
ENV PATH=/opt/venv/bin:$PATH PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 DATASET_STORE_ROOT=/data DATASET_STORE_PORT=8080 \
    DATASET_STORE_SURVEY_SCHEMA_DIR=/app/survey_schema
VOLUME /data
USER 10001
EXPOSE 8080
HEALTHCHECK --interval=15s --timeout=3s CMD python -c "import urllib.request as u; u.urlopen('http://127.0.0.1:8080/healthz', timeout=2)"
LABEL io.openit.service="dataset-store" \
      io.openit.revision="${REVISION}" \
      io.openit.contracts.boundary="${BC_VERSION}" \
      io.openit.contracts.survey-schema="${SURVEY_SCHEMA_VERSION}" \
      io.openit.turn-engine="n/a" \
      io.openit.model-runtime="n/a"
CMD ["python", "-m", "synthetic_data.service"]
