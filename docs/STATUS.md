# STATUS (synthetic-data)

마지막 갱신: 2026-10-15, 첫 구간.

## 한 일 (시험으로 확인)
- docs/design.md, boundary.md, runbook.md, CHANGELOG.md.
- I2 DatasetStore 파일·메모리 구현과 같은 적합성 시험(47건 통과, 전체 83건).
- 규칙 기반 생성기로 시나리오 설계 -> 발화/응답 생성 -> 노이즈 -> 정답 -> 품질 -> 분할 -> 패키징 -> 게시가 끝까지 돈다(`configs/dev.job.json`, 이웃은 `tests/doubles.py` 대역).
- 같은 입력과 시드는 같은 `dataset_digest`와(`created_at` 고정 시) 같은 `content_hash`.

## 남은 일
- 이웃 영역의 읽기 SDK/메모리 구현이 나오면 `tests/doubles.py`를 그쪽으로 교체(설정 factory만 변경).
- turn-engine 연동(CR-002): Directive를 `plan()`으로, 정답 구성 규칙 확인.
- LLM 생성기(같은 Protocol): 비결정 생성기의 재현성(응답 캐시), 호출 비용 보고.
- O11 확정 후 평가셋 구성(합성·실제 비율, 지표, 임계치) 반영. 지금은 `split.ratios` 설정만 있다.
- 감수 결과를 되먹이는 경로(감수 샘플에서 잘못된 라벨이 나오면 생성기/규칙 수정)는 사람 절차라 미정.
- 컨테이너(D22): run-once 잡이라 이번 구간에서 Dockerfile을 만들지 않음. 필요 여부 확인.
- 규칙 문서 6절(과거 증상 진술은 무관 vs 위험 신호) 충돌 조합은 만들지 않음. 규칙 쪽 확인 필요.

## 막힌 것 / 변경 요청
CR-001 FailureCase 문항 세트 참조, CR-002 turn-engine, CR-003 affected_slots 형식, CR-004 ext 승격, CR-005 created_at/version.
