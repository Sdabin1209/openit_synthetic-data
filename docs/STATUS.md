# STATUS (synthetic-data)

마지막 갱신: 2026-10-27, boundary-contracts v2.0.0 이전(브랜치 migrate-contracts-2.0.0, push 전).

## 2.0.0 이전 (D74, D75)
- 한 일: I2 DatasetStore, 품질 검사기, 시드 수집, 패키저를 v2 샘플(`ActionExtractionSample`/`ResponseSample`, 역할 `LORA_A`/`LORA_B`)로. requirements.lock v2.0.0. 시험 85건 통과, 15건 보류.
- **막힌 것/미정**: 생성 파이프라인(scenario, labeler, generators, noise, plans, directives)은 v1 내용(ParserOutput 항목, Directive)을 만든다. 합성 샘플은 모두 v2 스키마에서 빠지고 시드 샘플만 데이터셋에 남는다(report.json notes에 기록). 지시서는 이 영역의 역할(데이터 생성은 학습 서버 파이프라인이 이미 함)을 사용자가 정할 일이라 했으므로 생성기를 v2로 다시 쓰지 않았다.
- 보류한 시험 15건은 `tests/conftest.py`의 `needs_generator_v2` 표시(사유 포함). 생성기를 옮기거나 영역 역할이 바뀔 때 되살리거나 지운다.
- v2 의미 검사(targets, next_item, 건너뛰기 순서, save)는 turn-engine `validate_extraction`이 나온 뒤 연결(미정).


## 한 일 (시험으로 확인)
- (0.1.2) v1.2.0, I1·I7 HTTP 연결과 통합 시험, 오류 보고, GPU 호스트 runbook. 시험 92건.
- docs/design.md, boundary.md, runbook.md, CHANGELOG.md.
- I2 DatasetStore 파일·메모리 구현과 같은 적합성 시험(47건 통과, 전체 83건).
- 규칙 기반 생성기로 시나리오 설계 -> 발화/응답 생성 -> 노이즈 -> 정답 -> 품질 -> 분할 -> 패키징 -> 게시가 끝까지 돈다(`configs/dev.job.json`, 이웃은 `tests/doubles.py` 대역).
- 같은 입력과 시드는 같은 `dataset_digest`와(`created_at` 고정 시) 같은 `content_hash`.

## 남은 일
- 이웃 영역의 읽기 SDK/메모리 구현이 나오면 `tests/doubles.py`를 그쪽으로 교체(설정 factory만 변경).
- turn-engine 연동(원격이 생긴 뒤 다음 구간): Directive를 `plan()`으로. DialoguePlannerInput은 합성 또는 turn-engine 예시 사용(승인됨). 그때까지 hand-built 표시 유지.
- LLM 생성기(같은 Protocol): 비결정 생성기의 재현성(응답 캐시), 호출 비용 보고.
- O11 확정 후 평가셋 구성(합성·실제 비율, 지표, 임계치) 반영. 지금은 `split.ratios` 설정만 있다.
- 감수 결과를 되먹이는 경로(감수 샘플에서 잘못된 라벨이 나오면 생성기/규칙 수정)는 사람 절차라 미정.
- 컨테이너(D22): run-once 잡이라 이번 구간에서 Dockerfile을 만들지 않음. 필요 여부 확인.
- 과거 증상 진술(OUT_OF_SCOPE)과 현재 위험 진술(RISK_SIGNAL)을 별개 시나리오로 추가(충돌 아님, 헤드 확인).
- 컨테이너: 서비스 없는 잡이라 Dockerfile 없이 requirements.lock 고정으로 승인됨.

## 변경 요청
CR-001~005 모두 헤드가 결정(2026-10-15, D43). 반영: FailureCase 1.1 필드 사용과 폴백, SlotRef 마지막 '.' 분할, boundary-contracts v1.1.0 고정과 패키지 스키마 사용.
