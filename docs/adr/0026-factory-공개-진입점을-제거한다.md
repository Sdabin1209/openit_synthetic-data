# ADR 0026: factory 공개 진입점(`synthetic_data.adapters`)을 제거한다

## 상태
채택(2026-11-08). [ADR 0022](0022-잡-설정의-factory-이름은-공개-진입점이다.md)를 대체한다(Supersedes 0022).

## 맥락
ADR 0022는 계약이 잡 설정에 `module:function` 형식의 `factory` 문자열을 두는 동안(계약 v3.1.1) 배포 설정이 가리키는 `synthetic_data.adapters:http_question_reader`·`http_failure_store`를 공개 진입점으로 약속하고 `tests/test_public_factories.py`로 지켰다. 같은 ADR의 "되돌리는 조건"은 "계약이 factory 문자열을 없애고 구조화된 어댑터 설정으로 바뀌면 새 ADR이 대체하고 공개 이름을 정리한다"였다. 전수 점검에서 이 조건이 이미 충족됐는데 모듈이 남아 있음이 드러났다(`adapters/__init__.py` 독스트링은 "지울지는 새 ADR로 정한다, 아직 정하지 않았다").

## 결정
- `synthetic_data/adapters/`(별칭 모듈)와 `tests/test_public_factories.py`를 지우고 `pyproject.toml`의 패키지 목록에서 뺀다.
- `http_question_reader`·`http_failure_store`는 `components/link_question_reader.py`, `link_failure_reader.py`에 남는다. wiring(`wiring/run_job.py`)이 설정의 `HttpClientSettings` 값으로 직접 부른다. 이 이름은 더는 이웃과의 약속이 아니라 영역 내부 이름이다.
- 비밀 파일이 없을 때 `TokenError`로 멈추는 동작은 `tests/test_tls_config.py`가 계속 지킨다. 시그니처·기본 timeout은 `test_default_timeouts_follow_r10_3`이 지킨다.
- `tests/test_structure.py::test_no_factory_entry_point_after_contract_4_0_0`이 별칭 모듈·패키지 목록 항목·`load_factory`·`"factory"` 키가 코드에 다시 생기지 않음을 지킨다.

## 왜
- 근거 1, 계약: `../boundary-contracts/CHANGELOG.md` 4.0.0(2026-11-07) "잡 설정의 구현 모듈 경로 factory 제거(D135): `_common.HttpClientSettings` … 제거". 설정이 factory 문자열을 가질 수 없으므로 배포 설정이 이 이름을 가리킬 길이 없다. (이 영역의 옛 주석이 적은 "3.7.0"은 계약 CHANGELOG에 그런 항목이 없어 4.0.0으로 바로잡는다.)
- 근거 2, 영역 기록: CR-S-001이 "설정에서 factory를 없애면 별칭 모듈과 `load_factory`를 지울 수 있다"고 제안했고, ADR 0022 자신이 그 경우 정리하도록 되돌리는 조건을 적었다. 설정 읽기 코드(`components/run_plan.py`)는 이미 `adapters.*`를 `HttpClientSettings`로만 읽고 `load_factory`는 코드에 없다.
- 근거 3, 구조 규칙 1·4: 아무도 부르지 않는 공개 이름을 시험으로 지키면 이웃이 모를 구조 약속을 계속 지게 된다.
- 확인하지 않은 것: deploy 리포의 현재 설정이 이 이름을 더는 적지 않음은 읽기 허용 범위 밖이라 직접 보지 않았다. 계약 4.0.0이 그 설정 값을 스키마에서 거절하므로 계약 검증을 통과하는 설정은 이 이름을 가질 수 없다는 추론이다.

## 검토한 대안과 버리는 이유
- 별칭을 계속 둔다: 호출자가 없고 계약상 가리킬 수도 없다. 시험과 문서만 늘린다.
- `DeprecationWarning`을 두고 한 판 더 유지한다: 계약 4.0.0이 병행 기간 없이 3.x 설정을 버렸다(CHANGELOG 4.0.0 머리말). 이 영역만 병행할 이유가 없다.

## 결과
얻는 것: 죽은 공개 약속과 그것을 지키는 시험이 없어지고 문서가 코드와 맞는다. 감수하는 것: 4.0.0 이전 계약의 설정으로 이 판을 돌릴 수 없다(계약이 이미 그렇다).

## 되돌리는 조건
계약이 구현 모듈 경로를 가리키는 설정 값을 다시 도입하면 그 계약 버전에 맞춰 새 ADR로 공개 진입점을 되살린다.
