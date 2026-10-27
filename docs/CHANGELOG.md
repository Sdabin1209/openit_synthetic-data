# 변경 이력

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
