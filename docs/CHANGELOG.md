# 변경 이력

## 0.1.0 (2026-10-15)
- 설계(`docs/design.md`), 경계(`docs/boundary.md`), 런북 추가.
- I2 DatasetStore: 파일 구현과 메모리 구현, 공통 게시 검증(파일 해시, 줄 수, 분할 일치, 평가 시나리오 분리, 문진 스키마), 멱등 게시.
- 생성 파이프라인: 시나리오 설계, 시드 수집(I7), 정답 구성, 규칙 기반 발화·응답 생성기(교체 가능한 Protocol), STT 노이즈, 품질 검사, 중복 제거, 감수 샘플링, 시나리오 단위 분할(보지 못한 문항 평가 지원), 패키징.
- 생성 잡: 설정 파일 하나, `python -m synthetic_data run`, 재현성(`dataset_digest`), 멱등 재실행, `REGENERATE_SAMPLES` 부분 재생성.
- 시험용 이웃 대역(`tests/doubles.py`), 시험 83건.
- 변경 요청 CR-001~005.
