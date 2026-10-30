# CR-S-001: adapters.factory 설정 값이 영역 내부 모듈 경로를 가리킨다

**상태: 닫음(2026-10-30). 계약을 v3.1.1에서 바꾸지 않기로 해서, 이 영역이 공개 진입점으로 약속하고 시험으로 지킨다: [ADR 0022](../adr/0022-잡-설정의-factory-이름은-공개-진입점이다.md).**

날짜: 2026-10-30. 보낸 곳: synthetic-data. 받는 곳: 헤드(boundary-contracts, deploy).

## 무엇이 부족한가
계약 `SyntheticJobConfigRun`의 `adapters.question_reader.factory`는 파이썬 `module:function` 문자열이고, deploy의 e2e 설정(`deploy/scripts/e2e_steps.py`)이 `synthetic_data.adapters:http_question_reader`, `synthetic_data.adapters:http_failure_store`를 적는다. 이것은 이웃(deploy)이 이 영역의 내부 모듈 경로를 안다는 뜻이라 구조 규칙 1(영역은 서로의 구조를 모른다)과 어긋난다.

## 임시 조치
D117 개편으로 어댑터 코드는 `components/link_question_reader.py`, `link_failure_reader.py`로 옮겼다. 배포 설정이 깨지지 않게 `synthetic_data/adapters/__init__.py`에 이름만 다시 내보내는 별칭을 남겼다(로직 없음).

## 제안(헤드 결정)
설정에서 factory를 없애고 계약에 `adapters.question_reader = {"kind": "http", "base_url": ..., "token_env": ...}` 꼴을 둔다(CR-008 초안이 제안했던 형식, 이 영역은 받아들일 준비가 돼 있다). 그러면 별칭 모듈과 `load_factory`를 지울 수 있다. 시험용 대역(`doubles:make_question_reader`)은 factory가 아니라 wiring 주입으로 바꾼다.
