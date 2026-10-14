# 변경 이력

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
