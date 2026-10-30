# 변경 이력

## 미배포 (2026-10-30, U400: 영역 구조 개편 D117·D118)
- 의존: boundary-contracts v3.1.1, openit-link v0.4.0(통신 기반). 동작(와이어 형식, 잡 출력, 종료 코드, digest·version)은 바꾸지 않았다.
- 변경: 코드를 `components/`(29개), `wiring/`, `types/`로 옮겼다. `schemas/`에 영역 내부 타입 58개와 통과·거부 예시. 옛 모듈 경로(`synthetic_data.importer`, `.job`, `.store`, `.schemas`, `.service.app` 등)는 없어졌다. 설정 값으로 쓰이는 `synthetic_data.adapters:http_question_reader`·`http_failure_store`만 별칭으로 남겼다(CR-S-001).
- 변경(서버 면): dataset-store가 `openit_link.App/Route` 위로 옮겨 인증·413·계약 검증·오류 본문·/healthz·/readyz를 라이브러리가 한다. 동작 차이: 없는 경로는 인증 전에 404(ADR 0021). 다운로드는 1MiB 청크 스트리밍을 유지한다(link v0.2.0, CR-S-002).
- 변경: 저장소 생성자가 `Validators` 대신 문진 스키마 정수 버전을 받는다. 개발 도구(datamodel-code-generator 등)를 `requirements.lock`에 고정했다.

## 미배포 (2026-10-30, U300: 계약 3.0.0 전환)
- 의존: boundary-contracts v3.0.0.
- 변경(깨짐): 매니페스트·잡 설정의 `turn_engine_version`을 `action_rules_version`으로 바꿨다. 값은 설치된 계약 규칙 데이터의 `rules_version`이고, 설정 값은 기대값이라 다르면 거부한다(`run`은 선택, `import`는 필수). 이미지 라벨 `io.openit.turn-engine`을 뺐다. 2.x 매니페스트는 읽지 않는다(`SUPPORTED_PIPELINE_MAJOR`가 하드코딩 2였던 것을 계약의 MAJOR에서 읽게 고침).
- 변경: `build-image.sh` 라벨 정직성(U50). 라벨은 실제 설치한 wheel 버전과 `CONTRACT_VERSION`에서 찍고, 요청이 `requirements.lock`·실제 소스와 다르면 멈춘다.

## 미배포 (2026-10-30, U49: 승격된 스키마 사본 정리)
`docs/change-requests/` 아래 스키마 파일을 분류했다. (가) 계약 패키지(boundary-contracts)에 같은 이름이 있음 = 승격된 사본이라 삭제(내용은 git 기록), (나) 계약에 없음.

| 파일 | 분류 | 처리 | 근거 |
|---|---|---|---|
| `contract-ready/schemas/Synthetic{Defs,ImportReport,JobConfigImport,JobConfigRun,JobError,JobResult,RunReport}.schema.json` (7) | (가) | 삭제 | 계약 `schemas/`에 같은 이름 7개가 있다(`ls` 대조) |
| `contract-ready/examples/valid` 17, `examples/invalid` 21, `MANIFEST.json`, `make_examples.py`, `validate.py` | (가) | 삭제 | 같은 예시가 계약 `conformance/examples`·`examples_invalid`·`promoted`에 있다. 이 영역 시험은 이미 그 예시를 읽는다(`tests/test_contract_schemas.py`) |
| `schemas/{_defs,job-config-run,job-config-import,job-result,job-error,import-report,run-report}.schema.json` (7) | (가) | 삭제 | 위 `Synthetic*`의 초안 원본이다(승격 후 계약 쪽이 정본) |
| `schemas/examples/` 중 import-config, run-config, import-report 2, run-report, stderr-config-error, stdout 4 (10) , `schemas/validate_examples.py` | (가) | 삭제 | 초안 스키마용 예시·검증 스크립트 |
| `schemas/training-data-row.schema.json` | (나) | `schemas/`로 이동 | 외부 데이터셋 담당과의 형식이라 승격하지 않고 영역이 소유(MANIFEST `not_promoted`). 정본 위치는 변경 요청 폴더가 아니라 영역의 `schemas/` |
| `schemas/examples/row-lora-a.json`, `row-lora-b.json`, `row-invalid-two-messages.json` | (나) | `schemas/examples/`로 이동 | 위 스키마의 예시. 어긋나지 않게 `tests/test_training_data_row_schema.py`를 추가 |
결과: 삭제 파일 수와 시험은 커밋 메시지 참고. 이 사본을 읽는 시험·스크립트는 없었다(grep: `change-requests/schemas`, `validate_examples`, `contract-ready` 참조는 CR-008 문서뿐).

## 미배포 (2026-10-30, U47)
- 추가: 노출 선언 `deploy-exposure.json`(라벨 `io.openit.exposure`, 계약 Exposure로 검증해 `build-image.sh`가 싣는다). 이 서비스는 게이트웨이 밖으로 내지 않으므로 경로 전부 `denied`(ADR 0020).

## 미배포 (2026-10-30, U43)
- 추가: 잡 선언 `jobs.json`(라벨 `io.openit.jobs`, 빌드 진입점이 계약 JobsDeclaration으로 검증해 싣는다), 이미지 ENV `SYNTHETIC_SURVEY_SCHEMA_DIR`(설정의 `survey_schema_dir`보다 우선, CR-009), `scripts/setup-env.sh`의 마지막 줄 SetupEnvReport(ADR 0019).
- 의존: boundary-contracts v2.6.0.

## 미배포 (2026-10-30, U42)
- 추가: 영역 빌드 진입점 `scripts/build-image.sh`(계약 v2.5.0 BuildImageRequest/Result, ADR 0018), `scripts/smoke_build_image.sh`, 시험 `tests/test_build_image.py`.
- 의존: boundary-contracts v2.5.1.

## 미배포 (2026-10-29, 단위 4a, D111)
- 변경: I2 서버를 `http.server` 직접 구현에서 WSGI 앱 + waitress 3.0.2로 옮겼다(ADR 0017). 지운 자체 코드: 헤더 마감 래퍼, 연결 상한 서버, 본문 drain, Content-Length 직접 검사.
- 동작 변화: 본문 상한 초과는 413(text/plain), 연결 상한 초과는 503이 아니라 대기, 헤더 총 마감 없음, 인증 전에 본문을 받는다, 긴 요청 줄은 401/431. 환경 변수 `DATASET_STORE_HEADER_DEADLINE`은 없어졌다. 추가: `DATASET_STORE_THREADS`, `DATASET_STORE_DRAIN_GRACE`.

## 미배포 (2026-10-29, 단위 3)
- 의존: boundary-contracts v2.2.1, 문진 스키마 survey-schema-v1.1.0.
- 변경: `run`·`import` 설정을 계약 스키마로 검사한다(중첩 객체의 모르는 키도 거부: `tolerance`, `split`, `output`, `seeds` 등). 이전에는 최상위만 거부했다. 잡 출력은 내보내기 전에 계약 스키마로 자기 검사한다. 빈 `rejected_reasons`는 거부가 아닐 때 결과 한 줄에서 뺀다(ADR 0016).
- 변경: Dockerfile ARG 기본값 `unknown`을 `n/a`로, REVISION이 hex가 아니면 빌드 실패. 스모크는 `git rev-parse` 실패 시 unknown으로 빠지지 않고 멈춘다.

## 미배포 (2026-10-28)
- 추가(D100): I2 HTTP 서버 `python -m synthetic_data.service`(dataset-store), `Dockerfile`, `scripts/smoke_service.sh`, 서버·계약 클라이언트 시험(ADR 0011, 0012). 계약 v2.1.0이 필요하다(태그 전에는 작업 트리 wheel로 확인).
- 서버 보강(독립 검토 반영, ADR 0012): 인증 실패 제한을 인증 앞으로, 데이터셋 단위 게시 락(동시 같은 버전 200/409), Content-Length·tar 이름·sparse·항목 수 검사, 청크 스트리밍·다운로드 상한, 헤더 수신 마감, 시작 정리, 토큰 중복 거부, 스모크 비밀 검사 수정, Dockerfile 라벨 ARG와 `requirements-service.txt`.
- 추가(CR-D26, ADR 0013): `output.store.kind: http`(run·import 모두).
- 제거: v1 생성 경로(scenario, plans, directives, generators, noise, labeler, bank, josa)와 보류 시험 15건, 생성 전용 시험(ADR 0010). `run`은 시드 잡으로 남는다. `generator_version`은 `seed-only+job@<버전>`. `scenarios`·`generators`·`style_guide_version` 설정 키는 무시하고 보고서에 남긴다. `pipeline.py`의 시드 조립은 `seed_samples.py`로, `QuestionSetContext`는 `context.py`로 옮겼다.

## 0.3.0 (제안 버전, 미적용: pyproject는 올리지 않음)
- 실제 C1 데이터 첫 실행: 중복 판정을 '같은 입력' 엄격 키로 바꿈(설정 `max_cross_split_duplicate_inputs`).
- 점검 반영: 중복 발화 거부, 사유에서 입력 값 제거, version 지정 재실행 멱등, pending 정책, origin/비식별 미확인 명시, 의심 패턴 건수, 의미 검사 한계 명시(CR-006), 생성 경로 제거 제안(CR-007).
- 게시기(import) 모드 추가(`python -m synthetic_data import --config`, G02 방향). 외부 학습 데이터 jsonl 6개를 v2 스키마로 행 단위 검증하고 허용치 안에서 게시. 종료 코드 4 추가. 시험 `tests/test_import.py`(가짜 입력). 실제 데이터로는 시험하지 않음. CR-006.

## 0.2.2 (2026-10-27, boundary-contracts v2.0.2; 제안 버전)
- D84: 이웃 호출 토큰을 `boundary_contracts.read_secret`으로 읽는다(`NAME_FILE` 경로 우선, 없으면 `NAME` 환경 변수). 환경 변수 평문 노출(`docker exec env`/`inspect`)을 없앤다. boundary-contracts 태그를 v2.0.2로. 비밀 값이 로그·보고서·산출물에 나오지 않는 시험 추가. 이 영역의 비밀은 이웃 호출 토큰 둘(I1 읽기, I7 실패 사례 저장소)뿐이다.

## 0.2.1 (2026-10-27, boundary-contracts v2.0.1; 제안 버전)
- boundary-contracts 의존 태그를 v2.0.0에서 v2.0.1로(requirements.lock, runbook, boundary.md). v2.0.1은 ActionExtraction properties 순서만 사전순으로 바꾼 PATCH라 코드 변경 없음. model-runtime 의존은 없다.

## 0.2.0 (2026-10-27, 브랜치 migrate-contracts-2.0.0, boundary-contracts v2.0.0; 제안 버전)
- D74/D75 이전. 구조는 바꾸지 않고 v1 샘플 검증을 v2 샘플로 바꾼 최소 변경이다.
- I2 DatasetStore: 역할 `LORA_A`/`LORA_B`, 샘플 스키마 `ActionExtractionSample`/`ResponseSample`, 문진 스키마 input/expected 검사 삭제, 샘플의 `runtime_contract_version` 검사 삭제(매니페스트 검사는 유지), `pipeline_schema_version` MAJOR 2.
- 품질 검사기: 스키마 검사만 남김(`check_lora_a_sample`, `check_lora_b_sample`). v1 의미 검사 삭제(v2 의미 검사는 미정).
- 시드: `FailureCase.expected_kind` `LORA_A`/`LORA_B`, 입력은 `reviewed_input`만 사용(trace 키 미정). v1 노이즈 변형 없음.
- 샘플 ID 접두어 `as-`/`rs-`, 파일 경로 `lora_a/`, `lora_b/`.
- **알려진 한계(미정)**: 시나리오·정답 구성·발화/응답 생성기는 여전히 v1 내용을 만들어 합성 샘플은 모두 품질 검사에서 빠진다(보고서 `notes`에 남음). 생성기 이전은 영역 역할 결정 뒤.
- requirements.lock을 boundary-contracts v2.0.0 태그로. 시험 85건 통과, 15건 보류(생성기 v2 대기).

## 0.1.2 (2026-10-15)
- boundary-contracts v1.2.0, I1·I7을 HTTP 클라이언트로 연결(`synthetic_data.adapters`, base URL + 토큰 환경 변수 이름), 참조 서버 통합 시험.
- 경계 호출 실패를 report.json의 `error`로 남김. 시드의 모르는 필드·열거값은 `notes`로 남기고 받아들임.
- runbook: GPU 호스트 절차, 오류 보고 방식.

## 0.1.1 (2026-10-15)
- boundary-contracts v1.1.0로 전환: 경계 스키마는 `boundary_contracts.validator`로 읽고(자체 경로 설정 `boundary_schema_dir` 삭제), 쓰는 `pipeline_schema_version`은 1.1.
- 시드 수집: FailureCase 1.1의 `question_set`/`expected_kind`를 쓰고, 없는 1.0 레코드는 설정 문항 세트와 expected 형태 판별로 폴백.
- `affected_slots`를 마지막 '.'에서 나눠 문항 ID를 읽도록 수정(CR-003).
- requirements.lock에 boundary-contracts v1.1.0 태그 고정, runbook에 한 줄 실행 명령.

## 0.1.0 (2026-10-15)
- 설계(`docs/design.md`), 경계(`docs/boundary.md`), 런북 추가.
- I2 DatasetStore: 파일 구현과 메모리 구현, 공통 게시 검증(파일 해시, 줄 수, 분할 일치, 평가 시나리오 분리, 문진 스키마), 멱등 게시.
- 생성 파이프라인: 시나리오 설계, 시드 수집(I7), 정답 구성, 규칙 기반 발화·응답 생성기(교체 가능한 Protocol), STT 노이즈, 품질 검사, 중복 제거, 감수 샘플링, 시나리오 단위 분할(보지 못한 문항 평가 지원), 패키징.
- 생성 잡: 설정 파일 하나, `python -m synthetic_data run`, 재현성(`dataset_digest`), 멱등 재실행, `REGENERATE_SAMPLES` 부분 재생성.
- 시험용 이웃 대역(`tests/doubles.py`), 시험 86건.
- 변경 요청 CR-001~005.
