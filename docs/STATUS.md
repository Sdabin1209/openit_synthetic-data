# STATUS (synthetic-data)

마지막 갱신: 2026-10-29. 의존 버전의 정본은 `requirements.lock`이다(이 문서에 복사하지 않는다).

**버전 표기(사실)**: `pyproject.toml`의 version은 0.2.0이고, `docs/CHANGELOG.md`는 0.2.1과 0.2.2를 '제안 버전'으로 적었다. pyproject는 올리지 않았으므로 두 값이 어긋난다. 어느 쪽이 맞는지는 헤드 결정 사항이며 이 문서에서 정하지 않는다.

**시험 개수**: README 5절에만 적는다. 2026-10-28 v1 생성 경로와 보류 시험 15건을 제거했다(ADR 0010).

## 단위 3 (2026-10-29)
- 계약 v2.2.1, 문진 스키마 survey-schema-v1.1.0 핀. 잡 설정 두 가지와 잡 출력(결과 한 줄, report.json, import_report.json, 설정 오류 한 줄)을 계약 스키마(`SyntheticJobConfigRun/Import`, `SyntheticJobResult`, `SyntheticRunReport`, `SyntheticImportReport`, `SyntheticJobError`, `SyntheticDefs`)로 검사한다(ADR 0016). 손으로 쓴 키·형식 검사는 지웠다. Dockerfile ARG 기본값은 `n/a`이고 REVISION이 hex가 아니면 빌드가 멈춘다. 시험: `tests/test_contract_schemas.py`. turn-engine 코드 의존은 없다(`job.py`의 `resolve_turn_engine_version`이 설치돼 있으면 읽는 선택적 import만 있고 설정 값이 우선 대안이다).

## G02 방향 반영: 게시기(import) 모드 (2026-10-27)
- 한 일: 사용자 결정(데이터셋 담당의 최종 학습 데이터를 그대로 가져와 검증 후 게시, 재생성 없음)에 따라 `synthetic_data/importer.py`, CLI `import`, `configs/import.example.json`, `tests/test_import.py`(가짜 입력 17건) 추가. 설계는 docs/design.md 부록 A. `pytest -q` 결과 106 passed, 15 skipped.
- 재사용: 검증기(`schemas.Validators`), 해시(`boundary_contracts.canonical`), 패키징 직렬화(`dumps_line`), I2 `publish`와 멱등 규칙, run-once/종료 코드/보고서 틀, 설정 파싱 방식. 버리는 것(import에서 안 씀): 시나리오 설계, 발화/응답 생성기, 노이즈, 정답 구성, 시드 수집, 중복 제거, 분할(`scenario.py`, `generators/`, `noise.py`, `labeler.py`, `plans.py`, `directives.py`, `seeds.py`, `split.py`, `pipeline.py`, `job.py`). 보류 시험 15건과 이 코드의 최종 처분(삭제 여부)은 헤드 결정.
- 점검 반영(2026-10-28): 중복 발화 거부, 값 비노출, version 지정 멱등, pending 정책, 의심 패턴 건수 추가. 시험 113 passed, 15 skipped. 생성 경로 제거 제안은 CR-007.
- 실제 데이터 첫 실행(2026-10-28): C1 최종 파일 6개 64,459행이 전부 통과, 멱등 재실행 확인(결과 표는 docs/design.md 부록 B). 중복 판정 키를 엄격 키로 고침(ADR 0004). 임시 저장소에만 게시했고 운영 저장소 게시는 안 함.
- 막힌 것/안 한 것: 다른 빌드 미확인(행 형식은 C1에서 확인). v2 의미 검사 없음. 문항 세트 출처·`pending` 행 정책은 CR-006. Dockerfile 스모크는 해당 없음(서비스 아님, 승인된 사항).

## 2.0.0 이전 (D74, D75)
- 한 일: I2 DatasetStore, 품질 검사기, 시드 수집, 패키저를 v2 샘플(`ActionExtractionSample`/`ResponseSample`, 역할 `LORA_A`/`LORA_B`)로. requirements.lock v2.0.0(당시). 시험 85건 통과, 15건 보류(당시 수치. 현재는 위 시험 개수 참고).
- (해소, 2026-10-28) 생성 파이프라인(scenario, labeler, generators, noise, plans, directives)과 보류 시험 15건은 ADR 0010으로 제거했다. 시드 경로는 `seeds.py`/`seed_samples.py`로 남겼다.
- v2 의미 검사(targets, next_item, 건너뛰기 순서, save)는 turn-engine `validate_extraction`이 나온 뒤 연결(미정).


## 한 일 (시험으로 확인)
- (0.1.2) v1.2.0, I1·I7 HTTP 연결과 통합 시험, 오류 보고, GPU 호스트 runbook. 시험 92건.
- docs/design.md, boundary.md, runbook.md, CHANGELOG.md.
- I2 DatasetStore 파일·메모리 구현과 같은 적합성 시험(47건 통과, 전체 83건).
- (v1 시점 기록, 제거됨) 규칙 기반 생성기 경로. 지금 `run`은 시드 -> 품질 -> 분할 -> 패키징 -> 게시가 끝까지 돈다(`configs/dev.job.json`, 이웃은 `tests/doubles.py` 대역).
- 같은 입력과 시드는 같은 `dataset_digest`와(`created_at` 고정 시) 같은 `content_hash`.

## 남은 일
- 이웃 영역의 읽기 SDK/메모리 구현이 나오면 `tests/doubles.py`를 그쪽으로 교체(설정 factory만 변경).
- turn-engine 연동(원격이 생긴 뒤 다음 구간): Directive를 `plan()`으로. DialoguePlannerInput은 합성 또는 turn-engine 예시 사용(승인됨). 그때까지 hand-built 표시 유지.
- O11 확정 후 평가셋 구성(합성·실제 비율, 지표, 임계치) 반영. 지금은 `split.ratios` 설정만 있다.
- 컨테이너(D22): I2 서버(dataset-store)는 `Dockerfile`과 `scripts/smoke_service.sh`가 있다. run-once 잡(`run`, `import`)은 이미지가 아니라 `requirements.lock` 환경이다(docs/runbook.md).

## 열림 (ADR 0010)
- 시드 `run`은 유지(헤드 결정 2026-10-28, deploy 단계 7이 호출). 제거 여부는 데이터셋 담당 이전 계획과 함께 나중에 정한다. `regeneration.mode`·감수 샘플링: deploy는 설정 값(`regeneration.mode=full`, `review.per_kind=2`)을 써넣기만 하고 `review_sample.jsonl`이나 affected_only 동작을 읽는 곳은 grep으로 찾지 못했다. 삭제하지 않고 열림으로 둔다. 배포 E2E 설정이 v1 키(scenarios, generators, style_guide_version)를 아직 싣고 있어 무시하는 호환을 두었다(deploy가 고치면 제거).

## 변경 요청
CR-001~005 모두 헤드가 결정(2026-10-15, D43). 반영: FailureCase 1.1 필드 사용과 폴백, SlotRef 마지막 '.' 분할, boundary-contracts v1.1.0 고정과 패키지 스키마 사용.
