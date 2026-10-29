# ADR 0018: 영역 빌드 진입점 `scripts/build-image.sh`

상태: 채택 (2026-10-30). 계약 boundary-contracts v2.5.0(`BuildImageRequest`, `BuildImageResult`), OPEN_GAPS U42.

## 맥락
deploy의 `build-images.sh`가 이 영역의 Dockerfile 인자 이름(`BC_SPEC`, `BC_VERSION`, `REVISION`, `SURVEY_SCHEMA_VERSION`)과 빌드 컨텍스트 이름(`wheels`, `survey_schema`)을 직접 알고, wheel을 만들어 건네 줬다. 구조 규칙 1(영역은 서로의 구조를 모른다) 위반이다.

## 결정
- 진입점은 `bash scripts/build-image.sh <요청 JSON>`이다. 요청은 `scripts/build_image_request.py`가 계약 validator(`BuildImageRequest`)로 검증한다. 이 영역이 쓰는 키(`versions.boundary`, `versions.survey_schema`, `dependency_sources.boundary`, `dependency_sources.survey_schema`)가 없으면 실패하고 기본값은 영역 안에 두지 않는다. `model_runtime`, `turn_engine`은 이 이미지가 쓰지 않으므로 무시한다(라벨 `n/a`). `variant`는 이 리포가 이미지 하나만 내므로 어떤 값이든 실패한다.
- 계약 wheel은 `dependency_sources.boundary`의 사본에서 `pip wheel`로 만들어 빌드 컨텍스트 `wheels`로 준다. 문진 스키마는 `dependency_sources.survey_schema`를 컨텍스트 `survey_schema`로 준다(ADR 0011). 빌드 중 SSH와 이웃 리포 경로는 쓰지 않는다.
- 라벨 값은 요청에서 온다(`revision`, `versions.boundary`, 문진 스키마는 `versions.survey_schema`의 주 버전). 결과의 `labels`는 요청을 되풀이하지 않고 `docker image inspect`로 이미지에서 읽은 `io.openit.*`이다. 결과는 `BuildImageResult`로 검증한 뒤 표준 출력 마지막 줄에 낸다.
- Dockerfile은 그대로 둔다(인자 이름이 이 영역의 내부 사항이 되었다). `scripts/smoke_service.sh`는 서비스 동작 스모크로 남긴다.

## 왜
- 계약이 진입점을 정했다(영역이 자기 빌드 방식을 정하고 deploy는 요청과 결과만 안다). 요청 검증은 경계 입력 검사라 계약 validator가 정본이다.
- 소스 트리 사본에서 wheel을 만드는 이유: `pip wheel`이 소스 트리에 `build/`를 남기지 않게 한다.
- 주 버전만 라벨로 쓰는 이유: `ImageLabels`의 `io.openit.contracts.survey-schema`가 정수 주 버전이다.

## 검토한 대안과 버리는 이유
- deploy가 계속 영역 Dockerfile 인자를 아는 방식: 규칙 1 위반이라 버린다.
- 쉘에서 JSON 파싱: 검증이 계약 validator와 달라진다. 파이썬 도우미를 쓴다.

## 결과
얻는 것: deploy가 이 영역의 Dockerfile 내부를 몰라도 된다. 감수하는 것: 이 스크립트를 돌리는 파이썬(`PYTHON` 또는 리포 `.venv`)에 `boundary_contracts`가 있어야 한다. 이미지 빌드 자체는 기존과 같은 Dockerfile을 쓰므로 이미지 내용과 라벨은 deploy의 기존 빌드와 같게 의도했으나, 같은 입력으로 두 방식을 나란히 비교하지는 않았다.

## 되돌리는 조건
계약이 빌드 요청 형식을 바꾸면(3.0.0에서 `turn_engine` 삭제 등) 이 스크립트도 맞춘다.
