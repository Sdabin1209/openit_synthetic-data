# ADR 0021: 영역 내부를 컴포넌트·스키마·wiring으로 나누고 통신은 openit-link 위에 둔다

## 상태
채택(2026-10-30, 헤드 지시서 U400, `head/docs/DESIGN.md` D117·D118). 이전 모듈 배치(`importer.py`, `job.py`, `store/`, `service/app.py` 등)를 대체한다. 기존 ADR의 결정 자체(0001~0020)는 바뀌지 않았고 코드 위치만 옮겨졌다.

## 맥락
이전 구조는 `importer.py`가 설정 해석·행 검증·집계·판정·패키징·보고서·게시를 한 파일에서 했고, 서비스(`service/app.py`)는 인증·HTTP 규약·tar·서버 종료를 직접 구현했다. 컴포넌트가 자기 입출력 스키마 밖의 무엇을 아는지(구조 규칙 4)를 코드에서 확인할 수 없었고, 거부 조건이 코드 곳곳의 if/raise에 흩어져 있었다.

## 결정
- 일을 업무 단계로 나눠 컴포넌트 29개를 `synthetic_data/components/`에 둔다(표: `docs/components.md`). 컴포넌트마다 입력·출력 JSON Schema가 `schemas/`에 있고 컴포넌트는 입력을 스키마로 검사하며 내기 전에 출력을 검사한다. 컴포넌트끼리 import하지 않는다.
- 컴포넌트를 잇는 일(순서, 저장소·이웃 클라이언트·문진 스키마 검사 함수의 주입)은 `synthetic_data/wiring/`가 한다. 판정하지 않는다.
- 코드 타입은 `schemas/`에서 datamodel-code-generator(TypedDict)로 `types/`에 생성하고, 같은 생성이 스키마 사본(`types/schema_registry.py`)도 낸다.
- 이웃과의 HTTP는 `link_*` 컴포넌트만 한다. 받는 쪽(dataset-store)은 `openit_link.App/Route` 위에, 보내는 쪽은 `openit_link.clients` 위에 쓴다(D118).
- 동작(와이어 형식, 잡 출력, 종료 코드, 매니페스트 digest·version)은 바꾸지 않는다.

## 왜
- 구조 규칙 6개(D104)와 DESIGN.md가 정한 배치다. 근거: functional core, imperative shell(Gary Bernhardt)과 포트·어댑터(Alistair Cockburn). 컴포넌트는 같은 입력이면 같은 출력인 함수이고, 상태·바깥 자원은 주입받는 모양(`publish_decision(store=...)`, `question_set_admit(survey_check=...)`)으로만 드러난다.
- 스키마 사본을 코드에 생성해 넣는 이유: 이미지는 `COPY synthetic_data`만 하고 리포 루트 `schemas/`가 없다. 정본(`schemas/`)과 사본이 어긋나는 것은 `tests/test_structure.py`가 재생성 비교로 막는다.
- 오류 메시지에 위반 값을 싣지 않는 규칙(ADR 0003)은 스키마 검사 함수가 위치와 규칙 이름만 내는 것으로 유지했다.
- 컴포넌트 수 29개는 측정이나 표준에서 나온 값이 아니다. "입력 스키마 하나 -> 출력 스키마 하나"로 말해지는 업무 단위를 나눈 결과이고, 이름 붙은 단계(줄 검증, 집계, 허용치 판정, 겹침 판정, 패키징, 보고서, 시드 수집·짝짓기·조립, 분할 등)가 기존 코드와 브리프에서 이미 구분돼 있었다.

## 검토한 대안과 버리는 이유
- 모듈 배치만 옮기고 스키마를 두지 않는다: 구조 검사 4·5(스키마와 생성 타입)를 충족하지 못하고 거부 조건이 코드에 남는다.
- pydantic 모델을 생성해 쓴다: 출력이 모델 인스턴스가 돼 와이어 형식(plain dict, JSON 한 줄)과 어긋나고 이미지에 pydantic을 더해야 한다. TypedDict는 dict 그대로다.
- 저장소 파일·메모리 구현을 컴포넌트 둘로 나눈다: 게시 검증 규칙을 공유해야 하는데 컴포넌트끼리 import할 수 없어 규칙이 복제된다. 한 컴포넌트(`dataset_store.py`)에 두 구현을 둔다.
- 서버 규약을 영역 코드에 그대로 둔다: D118이 금지한다(401/403, 413, 계약 검증, BoundaryError 본문, /healthz, /readyz는 라이브러리).

## 결과
얻는 것: 입출력 경계가 스키마로 보이고, 구조 검사로 import·HTTP 위치가 강제되며, 서버 규약 코드가 사라졌다.
감수하는 것:
- 파일 다운로드를 메모리에 올린다. openit_link v0.1.0의 Response는 bytes만 받아 이전의 청크 스트리밍(1MiB 단위)이 없다. 동시 다운로드 상한(기본 8)은 그대로이고 데이터셋 크기를 이 서비스에서 측정하지 않았다(큰 데이터셋에서 메모리 위험, 변경 요청 CR-S-002).
- 본문 전체를 메모리로 받는다(게시 tar, 상한 1GiB). 같은 이유다.
- 경로 해석 순서가 라이브러리의 것이다: 없는 경로는 인증 전에 404가 나온다(이전에는 401). 알려진 경로에 지원하지 않는 메서드는 405(`Allow` 머리글 없음). 시험을 이 동작에 맞췄다(`tests/test_service.py`).
- 서버 겉옷 한 겹이 남는다: 파일 경로 `%2F` 보존(WSGI PATH_INFO가 디코딩하므로 REQUEST_URI에서 조각마다 다시 인코딩), 인증 실패 횟수 제한(ADR 0012), 처리하지 못한 예외의 503. 앞의 둘은 라이브러리에 없는 이 서버만의 방어다.
- 설정 값 `synthetic_data.adapters:http_question_reader`가 배포 설정(deploy)에 있어 `adapters/__init__.py`를 별칭으로 남겼다(CR-S-001).

## 되돌리는 조건
openit_link가 스트리밍 응답과 경로 퍼센트 인코딩 보존을 지원하면 겉옷과 메모리 적재를 걷어낸다. 컴포넌트 분할이 실제로 어긋나면(같이만 바뀌는 컴포넌트 쌍이 반복되면) 합친다.
