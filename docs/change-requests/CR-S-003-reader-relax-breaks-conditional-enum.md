# CR-S-003: 읽기 모드 `_relax`가 조건부 규칙의 `if` 열거를 지워 정상 FailureCase 를 INTEGRITY_ERROR 로 거절한다

**상태: 열림(2026-11-07).** 날짜: 2026-11-07. 보낸 곳: synthetic-data. 받는 곳: 헤드(boundary-contracts).

## 무엇이 틀렸나
`boundary_contracts/clients/_http.py` 의 `_relax`는 문자열 열거 `enum`을 `{"type": "string"}`으로 바꾼다(모르는 열거값을 받으려는 읽기 모드, CONVENTIONS 1절 3항). 그런데 `ActionExtraction.values[]`의 조건부 규칙은 `if: {properties: {status: {enum: [MISSING, UNCLEAR, UNKNOWN, REJECTED]}}, required: [status]}` 이다. `if` 안의 열거가 `type: string`이 되면 모든 문자열 status 가 `if`에 맞아, `then`(value 는 null, precision 은 `unspecified`)이 모든 항목에 적용된다. 정상 항목(`status: ANSWERED`, `value: 5`, `precision: approximate`)이 거절된다.

## 재현 (v4.0.1, v4.0.2 의 `_relax` 도 같다)
1. `validator("FailureCase")`로 검증하면 `expected.values[0]` = `{key, value: 5, precision: approximate, status: ANSWERED, save: true}`는 통과한다.
2. `clients._http._reader("FailureCase")`로 같은 레코드를 검증하면 `expected/values/0/value: 5 is not of type 'null'`, `expected/values/0/precision: 'unspecified' was expected`.
3. `HttpFailureStore`로 이런 사례를 읽으면 INTEGRITY_ERROR(서버 결함으로 분류)가 나, 정상 서버와 정상 사례로도 실패 사례를 읽을 수 없다.

## 제안
`_relax`가 `if`·`not`·`contains` 안의 `enum`은 건드리지 않게 한다(조건 판별에 쓰는 열거는 값 집합이 그대로여야 한다). 읽기 모드 완화는 값을 검증하는 위치의 `enum`에만 적용한다. 계약 시험에 "조건부 `if` 열거를 가진 정상 레코드가 읽기 모드 검증기를 통과한다"를 더한다.

## 이 영역의 영향
정상 사례를 실제 HTTP 클라이언트로 읽는 시험 4건(`tests/test_job.py::test_cli`, `tests/test_job_http_publish.py::test_run_job_publishes_over_http`, `tests/test_http_integration.py` 의 토큰 파일 시험 2건)이 이 결함 때문에 실패한다. 시험 데이터는 계약 검증기를 통과하는 정상 값이라 시험을 고치지 않는다.
