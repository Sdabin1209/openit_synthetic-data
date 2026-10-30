# ADR 0022: 잡 설정의 factory 이름은 이 영역의 공개 진입점이다

## 상태
채택(2026-10-30, 헤드 결정: 계약은 v3.1.1에서 바꾸지 않는다). 변경 요청 CR-S-001을 닫는다.

## 맥락
계약 `SyntheticJobConfigRun`의 `adapters.question_reader.factory`·`adapters.failure_store.factory`는 `module:function` 문자열이고, 배포 설정(deploy e2e)이 `synthetic_data.adapters:http_question_reader`, `synthetic_data.adapters:http_failure_store`와 kwargs(`base_url`, `token_env`)를 적는다. D117 개편(ADR 0021)으로 구현이 `components/link_*`로 옮겨 가면서 이 이름을 별칭으로만 남겼고, 이웃이 내부 모듈 경로를 안다는 점이 구조 규칙 1과 어긋난다는 CR-S-001을 냈다. 계약을 바꾸지 않기로 해서 설정 값 형식은 그대로다.

## 결정
- `synthetic_data.adapters`의 `http_question_reader`, `http_failure_store`는 이 영역의 **공개 진입점**이다. 별칭이 아니라 계약 설정이 가리키는 영역의 약속이다. 이름·호출 시그니처 `(base_url: str, token_env: str, timeout: float = 10.0)`·반환(계약 읽기 클라이언트 `HttpQuestionReader`/`HttpFailureStore`)을 지우거나 옮기거나 바꾸지 않는다.
- 구현은 계속 `components/link_question_reader.py`, `link_failure_reader.py`에 있다. `adapters/__init__.py`는 이름을 내보내기만 하고 로직이 없다.
- 시그니처를 바꿔야 하면 새 이름을 더하고 옛 이름을 유지한다(계약 설정이 바뀔 때까지). 이름 변경은 계약 변경 요청 없이 하지 않는다.
- `tests/test_public_factories.py`가 모든 공개 factory 이름이 import되고 호출 시그니처가 맞으며 비밀을 `NAME_FILE`로 읽는지 지킨다.

## 왜
- 설정 값 `factory`는 계약이 정한 입력이다. 입력이 가리키는 이름이 깨지면 배포 설정과 이미 만든 설정 파일이 동작하지 않는다(소비자 호환, 입력 약속은 출력 약속과 같이 지킨다).
- 계약을 v3.1.1에서 고정했으므로 설정 형식 개선(kind: http 형식)은 지금 선택지가 아니다.
- 내부 구조를 이웃에게 숨기는 규칙 1과의 긴장은 "이름이 곧 공개 이름"으로 풀었다: 이웃이 아는 것은 구현 모듈(`components/…`)이 아니라 공개 진입점 `adapters`뿐이다.

## 검토한 대안과 버리는 이유
- 별칭만 두고 약속하지 않는다: 다음 개편에서 지워질 수 있고 이를 막는 시험이 없다.
- 계약 설정을 `kind: http` 형식으로 바꾼다: 계약 고정(v3.1.1)에 어긋난다.
- 구현을 `adapters/`로 되돌린다: D117 구조(통신은 `link_*` 컴포넌트)에 어긋난다.

## 결과
얻는 것: 배포 설정이 개편에 영향받지 않고, 공개 이름이 시험으로 지켜진다. 감수하는 것: 시그니처를 바꾸기 어렵다(더하기만 가능).

## 되돌리는 조건
계약이 factory 문자열을 없애고 구조화된 어댑터 설정으로 바뀌면(헤드 결정) 새 ADR이 이 ADR을 대체하고 공개 이름을 정리한다.
