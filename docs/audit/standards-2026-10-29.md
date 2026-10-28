# 표준성·근거 전수 점검: synthetic-data (2026-10-29, D89)

기준: `head/docs/audit/standards-audit-spec.md`(헤드가 읽기를 허락한 파일). 읽기 전용 점검이며 코드·설정·시험은 고치지 않았다. 점검 시점 HEAD는 `43ad43c`.

읽은 것: `CLAUDE.md`, `README.md`, `docs/brief.md`, `docs/design.md`, `docs/boundary.md`, `docs/runbook.md`, `docs/STATUS.md`, `docs/adr/0001~0014`와 `adr/README.md`, `synthetic_data/` 전 모듈(`importer.py`, `job.py`, `config.py`, `package.py`, `split.py`, `rng.py`, `seeds.py`, `seed_samples.py`, `schemas.py`, `adapters.py`, `__main__.py`, `store/*`, `service/*`), `Dockerfile`, `requirements*`, `pyproject.toml`, `configs/*.json`, `scripts/*`. 이웃 읽기(허용 범위): `boundary-contracts`의 `CONVENTIONS.md:86`, `HTTP.md:11`, `canonical.py`.

분류: S 표준+근거, S- 표준+근거 기록 없음, N 비표준+대안 비교 근거, N- 비표준+근거 없음, O 가져다 쓸 것을 직접 만듦, ? 표준 여부 확인 못 함.
증거 표기: `파일:줄`. 값(숫자)의 출처는 요소 설명에 "측정 안 함/표준/제약"으로 구분했다.

## 1. 결과표

### A. 데이터셋 저장·digest·불변(콘텐츠 주소 지정)

| ID | 요소 | 분류 | 표준 이름 | 근거 위치 | 증거 |
|---|---|---|---|---|---|
| A1 | 저장소 종류 = 파일 시스템(SQLite/PostgreSQL/객체 저장소 대신). 성능 비교는 측정 안 함 | N | 없음(대안 비교로 정함) | ADR 0008 | `store/file_store.py:1-6`, `adr/0008` |
| A2 | 게시 확정 = 임시 디렉터리에 쓰고 `os.rename`으로 확정 | S | POSIX `rename(2)` 원자성(ADR이 "POSIX 표준"으로 인용) | ADR 0008 왜 | `store/file_store.py:49-56` |
| A3 | 게시 내구성: 파일·디렉터리 `fsync` 없음. 정전·크래시 뒤 rename은 보였는데 파일 내용이 비어 있을 수 있다(추정, 장애 주입 시험 안 함). 같은 content_hash 재게시는 기존 것을 파일 재검증 없이 성공으로 돌려준다 | N- | 표준 관행(임시 파일 쓰기 -> fsync -> rename -> 디렉터리 fsync, POSIX `fsync(2)`)을 따르지 않음 | 근거 기록 없음(ADR 0008은 원자성만 말함) | `store/file_store.py:51-56`, `store/base.py:100-103` |
| A4 | 배치 `<root>/<dataset_id>/<version>/{manifest.json,meta.json,files/}`와 `meta.json`의 `seq`(게시 순서). 이 seq를 읽고 쓰는 구간은 동시 게시에 경합이 있어 서버가 ID 단위 락으로 막는다 | N- | 없음 | 배치는 ADR 0008, `meta.json`/`seq`를 둔 이유는 근거 기록 없음(ADR 0012가 경합만 설명) | `store/file_store.py:5,48,54`, `service/app.py:157-170` |
| A5 | 데이터셋 해시 = `boundary_contracts.canonical`의 SHA-256 위에 RFC 8785(JCS) 정규화. 직접 구현하지 않고 계약 패키지 것만 씀(시험 `test_hashes_only_via_canonical`) | S | RFC 8785(JCS), SHA-256(FIPS 180-4) | ADR 0006 | `package.py:57`, `importer.py:423`, `store/base.py:70,98`; 계약 쪽 `boundary_contracts/canonical.py:1` |
| A6 | `dataset_digest` 입력 구성(입력 파일 sha256들, 쓴 파일 해시, 문항 세트, 계약 버전, `generator_version`, turn-engine 버전, pending 정책). `tolerance` 값은 넣지 않음 | N | 없음 | ADR 0006(대안: created_at 고정, 시각 기반 버전) | `importer.py:423-427`, `package.py:57-60` |
| A7 | 버전 이름 `v` + digest 앞 12자리(48비트). 충돌 확률은 계산하지 않음. 충돌 시 다른 내용이면 CONFLICT로 실패(안전한 쪽) | N- | 없음(git 짧은 해시와 비슷한 관행이나 표준은 아님) | ADR 0006이 "근거 기록 없음"이라고 명시 | `importer.py:431`, `package.py:236` |
| A8 | 불변 집행 = 수정·삭제 경로 없음 + 같은 (id, 버전)에 같은 hash면 멱등, 다르면 CONFLICT. 파일 시스템 수준 읽기 전용(chmod 등)은 하지 않음 | S- | 계약 `INTERFACES.md` I2 멱등 규칙, `HTTP.md ## I2`(200/201/409) | ADR 0006·0012가 있으나 "파일 수준 불변은 하지 않는다"는 기록 없음 | `store/base.py:100-104`, `service/app.py:427-437`, `store/file_store.py:51-56` |
| A9 | 읽기 때 매니페스트 content_hash와 파일 해시 재검증(청크 해시 후 스트리밍) | S | 계약 I2(INTEGRITY_ERROR) | ADR 0012 | `store/base.py:70,87`, `service/app.py:179-193` |
| A10 | 이미 게시됐는지 판정이 두 경로에서 다르다: `import`는 version을 지정해도 digest가 같으면 ALREADY_PUBLISHED, `run`은 `cfg.version is None`일 때만 그렇다(version을 고정하고 created_at이 다르면 `run`은 CONFLICT) | N- | 없음 | 근거 기록 없음. design.md 10절·CR-005는 version 생략 경우만 설명 | `job.py:192`, `importer.py:446-452` |
| A11 | 보존 기간·삭제·백업 정책: 문서에 없음. 버전은 영구 누적, 디스크 부족은 게시 거절(3n+1GB 규칙)로만 다룸 | N- | 없음 | 근거 기록 없음(grep: `보존`, `retention`, `백업`이 문서·코드에 없음) | `service/app.py:99-103`, docs 전체 grep |
| A12 | 샘플 줄 직렬화 `json.dumps(sort_keys, separators)`(해시 대상은 파일 바이트라 JCS와 달라도 결정적) | N | 없음(JSON Lines 관행) | `package.py` 독스트링 5행(키 정렬·샘플 ID 순이라 같은 바이트) | `package.py:20-21` |
| A13 | 식별자 규칙 `^[A-Za-z0-9][A-Za-z0-9._:-]*$`, 128자(경로 안전) | N | 없음 | CR-005 결정, `docs/boundary.md:49` | `store/base.py:27`, `config.py:15` |
| A14 | 시각 = UTC `YYYY-MM-DDThh:mm:ssZ`, 시계는 주입 가능 | S- | RFC 3339 / ISO 8601 UTC | 근거 기록 없음(주석 없음) | `importer.py:406`, `job.py:185` |

### B. 행 검증, 누수 검사, 분할, 허용치

| ID | 요소 | 분류 | 표준 이름 | 근거 위치 | 증거 |
|---|---|---|---|---|---|
| B1 | 행 검증 3단계(구조 -> user/assistant를 입출력 스키마로 -> 샘플 스키마). 스키마는 계약 패키지 것(복사본 없음) | S | JSON Schema Draft 2020-12(`Draft202012Validator`) | ADR 0003 | `importer.py:198-245`, `schemas.py:57-60` |
| B2 | 거부 사유를 `<단계>: <경로>#<키워드>` 코드로만 기록(값 비노출) | N | 없음(요구사항 SD-1에서 옴) | ADR 0003(대안: 한 단계 검증, 스키마 메시지 기록) | `schemas.py:66-73`, `importer.py:230,244` |
| B3 | 값 비노출 주장이 일부 경로에 안 지켜진다: `Validators.boundary`는 jsonschema 메시지(입력 값이 섞임, 200자까지)를 `BoundaryError` 메시지에 넣고, 이것이 `report["error"]`, 종료 시 stderr, 서버의 HTTP 오류 본문으로 나간다. `design.md:96`은 "오류 레코드에 입력 값이 없다"고 쓴다. `import`는 사전 검증으로 대부분 막지만 `run`·서버 게시 경로에는 적용되지 않는다 | N- | 없음(개인정보 최소화 원칙은 ADR 0003이 목표로 삼음) | 근거 기록 없음. 문서 진술(`design.md:96`)과 코드가 어긋남 | `schemas.py:19-21,81`, `importer.py:276`, `service/app.py:303` |
| B4 | 평가 누수 정규화 = NFKC -> `lower()` -> 유니코드 범주 P·S·Z·C 문자 제거. `lower()`는 완전한 대소문자 접기가 아니다(영문·한국어 혼합 발화에는 영향이 작을 것으로 보나 측정 안 함) | S | Unicode UAX #15(NFKC), UAX #44(General Category) | ADR 0004 | `importer.py:55-62` |
| B5 | 누수 판정 키 = 정규화한 발화 + 입력 나머지 전체의 SHA-256 완전 일치만. 의미·유사 문장은 못 잡는다. 상류(데이터셋 담당)의 유사도 검사(`leak_jaccard 0.7`)는 재현하지 않으므로 상류보다 약하다. 근거 데이터는 C1 한 번의 측정이다 | N | 없음 | ADR 0004(대안: scenario_id만, 원문 비교, 유사도 -> 임계 근거 없음으로 버림) | `importer.py:65-71,368-388` |
| B6 | 발화+맥락 키(`utterance_key`)는 참고 건수로만 남기고 판정에 쓰지 않음. 맥락을 어디까지 볼지는 "근거 기록 없음" | N- | 없음 | ADR 0004가 "근거 기록 없음"이라고 명시 | `importer.py:74-80,382` |
| B7 | scenario_id가 TRAIN/VALIDATION/EVAL 사이에 겹치면 거부(import에서 한 번, 저장소 게시에서 한 번 더) | N | 없음(계약 경계 규칙 9) | brief 4절, ADR 0004 맥락 | `importer.py:389-396`, `store/base.py:148-151` |
| B8 | 분할 방법(run): `sha256(seed, "split", scenario_id) % 10^9`를 비율 구간에 대응(결정적 해시 분할). 이름 있는 표준은 확인하지 못함. ADR 없음, 근거는 `split.py` 독스트링·design.md 8절에만 있음 | ? | 표준 여부 확인 못 함 | design.md 8절, `split.py:1-5` | `split.py:15-21` |
| B9 | 분할 비율: 코드 기본값 없이 설정 필수(`split.ratios`), 예시 0.8/0.1/0.1는 자리 표시, 실제 구성은 O11(사용자 결정). `import`는 파일 이름으로 분할(비율 없음) | N | 없음 | `config.py:1-4` 독스트링, design.md 8절, ADR 0002 | `config.py:93-95`, `configs/dev.job.json:36-42`, `importer.py:34` |
| B10 | 시드 처리: `seed`는 정수 필수, 난수는 전역 `random` 없이 `sha256(seed, 용도)`에서 파생. 이름 있는 표준은 확인하지 못함. ADR 없음 | ? | 표준 여부 확인 못 함 | design.md 10절(재현성) | `config.py:90-92`, `rng.py:7-12` |
| B11 | 허용치 `max_invalid_rows`, `max_invalid_rate`는 필수(기본값 없음), 값은 사용자 몫. 실패율 0/64,459는 C1 한 번의 측정 | N | 없음 | ADR 0005 | `importer.py:145-150` |
| B12 | `max_cross_split_duplicate_inputs` 기본 0 | N | 없음(fail-safe 기본값 원칙. ADR은 표준 이름을 적지 않음) | ADR 0004·0005("가장 엄격한 값을 시작점", C1에서 0건, 다른 빌드 측정 안 함) | `importer.py:151-153` |
| B13 | `pending_policy` 기본 `report`(걸러내지 않음). 정책은 사용자 결정으로 미룸 | N | 없음 | ADR 0005, CR-006 4항 | `importer.py:157-159` |
| B14 | `max_pii_suspect_rows` 기본은 생략 = 경고만. 이메일·전화·주민번호 형태가 발견돼도 게시한다. ADR 0005의 제목은 "기본값은 가장 엄격하다"이나 이 기본값과 pending 기본값은 가장 엄격하지 않다. 건강 데이터 게시에서 경고만으로 두는 이유는 ADR 0007이 "정규식은 거짓 음성이 있어 판정에 쓰지 않는다"로 설명하지만, 검출된 것까지 통과시키는 이유는 아니다 | N- | 없음 | 부분 근거만(ADR 0007), ADR 0005 제목과 불일치 | `importer.py:154-156,356-357`, ADR 0005 제목 |
| B15 | 파일에 통과 행 0건, 총 0행이면 항상 거부(`rejected` 목록) | N | 없음 | ADR 0005 | `importer.py:342-352` |
| B16 | 입력 형식 = JSON Lines 6개 `lora_{a,b}_{train,val,test}.jsonl`, 파일 이름으로 분할 결정(행의 `split`은 개수만) | N | JSON Lines 관행(RFC 아님) | ADR 0002(대안: 행의 split, 디렉터리 전체) | `importer.py:34-36,248-264` |
| B17 | 입력 파일을 통째로 메모리로 읽음(`read_bytes`). 한계 크기는 측정 안 함(C1 6개 64,459행은 약 30초에 처리) | N- | 없음 | 근거 기록 없음(design.md 부록 B에 소요만 있음) | `importer.py:259` |
| B18 | `run`의 중복 제거(역할+입력 해시): 같은 입력에 다른 정답이면 모두 제거, 시드가 이김. 감수 샘플링 `per_kind` 기본 2는 값의 근거 없음, 산출물을 읽는 곳도 못 찾음(ADR 0010·README 6절) | N- | 없음 | design.md 7절은 방법만, `per_kind=2`는 근거 기록 없음 | `job.py:152-168,223-236`, `config.py:132` |
| B19 | 의미 검사 미수행을 `semantic_checks.performed=false`로 명시, 복사하지 않고 CR-006으로 요청 | N | 없음 | ADR 0009 | `importer.py:337`, `importer.py:439` |

### C. 비식별·개인정보

| ID | 요소 | 분류 | 표준 이름 | 근거 위치 | 증거 |
|---|---|---|---|---|---|
| C1 | 비식별 보증 안 함: `deid_attested: false`를 보고서·매니페스트에 항상 기록, 확인 주체는 데이터셋 담당. 이 영역에는 법적·표준 비식별 방식(예: 가명처리 기준)이 없다. 의도된 설계이며 표준 이름은 ADR이 인용하지 않았다 | N | 없음(대안 비교: 정규식 판정, NER, 문서로만) | ADR 0007 | `importer.py:335-336,439` |
| C2 | 의심 패턴 정규식 4종(이메일·휴대전화·유선전화·주민번호 형태), 행 수로만 셈, 값은 기록 안 함. 주민번호는 검증 숫자 확인이 없고 성별 자리 `[1-4]`라 외국인 번호(5-8) 등은 못 잡는다 | N | 없음. ReDoS 방지는 OWASP 지침의 일반 권고 인용(ADR이 "일반 권고"로만 적음) | ADR 0007 | `importer.py:48-53,83-86` |
| C3 | `PII_SCAN_LIMIT` = 20,000자: 앞 20,000자만 검사해 그 뒤의 패턴은 조용히 놓친다. 데이터 최대 길이는 측정 안 함 | N- | 없음 | 코드와 ADR 0007이 "근거 기록 없음"이라고 명시 | `importer.py:54,85` |
| C4 | `run`(시드) 경로의 비식별: 이웃의 `deidentified is True` 플래그만 믿고, 아니면 실행 전체를 거부(fail closed). 시드의 `reviewed_input`·`expected`에는 C2의 의심 패턴 검사를 하지 않는다(검사는 `import`에만 있음) | N- | 없음 | 플래그 거부는 brief 5절·ADR 없음, 패턴 검사 부재는 근거 기록 없음 | `seeds.py:293-294`, `importer.py:312`(import 전용) |
| C5 | 보고서·매니페스트·로그에 입력 값을 넣지 않는 원칙(건수·해시·줄 번호만). 서버 로그는 메서드·경로·상태만 | S- | 없음(데이터 최소화) | ADR 0003·0007 일부, 서버 로그는 ADR 0012 마지막 줄 | `importer.py:330-331`, `service/app.py:270-272` |

### D. I2 HTTP 서버(표준 라이브러리, 선택 I2)

| ID | 요소 | 분류 | 표준 이름 | 근거 위치 | 증거 |
|---|---|---|---|---|---|
| D1 | 서버 구현 = `http.server.ThreadingHTTPServer`. 의존 최소, model-lab I3 서버와 같은 구조, 트래픽이 적다는 이유이며 성능은 측정 안 함. Python 문서는 `http.server`를 프로덕션용으로 권하지 않고 기본 보안 점검만 한다고 적는 것으로 알고 있으나(원문 재확인 못 함), ADR은 이 경고를 다루지 않는다 | N | 없음(대안 FastAPI 등 비교) | ADR 0012 왜·대안 | `service/app.py:28,463-492` |
| D2 | 인증 = `Authorization: Bearer` 정적 토큰, 읽기/쓰기 역할 분리, 쓰기 역할은 `synthetic-data` 하나, 쓰기 토큰은 읽기도 허용, 같은 토큰을 양쪽에 쓰면 시작 거부. `Bearer` 스킴 이름을 대소문자 구분해 비교(RFC 9110은 스킴을 대소문자 무시로 정의) | S- | RFC 6750(Bearer), 계약 `HTTP.md:11`·CONVENTIONS 9절 | ADR 0012(읽기 포함 이유 설명), D84 | `service/app.py:77-81,105-124` |
| D3 | 토큰 비교 `hmac.compare_digest`(상수 시간), 일치해도 끝까지 순회 | S | Python 표준 라이브러리의 타이밍 안전 비교 | 코드 주석("시간이 일정하다") | `service/app.py:111-113` |
| D4 | 인증 정보가 없거나 틀리면 403(401 아님). RFC 9110은 인증 실패에 401과 `WWW-Authenticate`를 요구한다. 이 영역은 헤드 소유 계약(`CONVENTIONS.md:86`)을 따른 것이라 이 영역이 고칠 수 없고, 계약 쪽 이유는 그 줄에 서술 없음 | N- | RFC 9110(401/403) 이탈 | 이 영역에는 근거 기록 없음. 계약이 "403"이라고만 적음 | `service/app.py:40,122-124`, `boundary-contracts/CONVENTIONS.md:86`, `scripts/smoke_service.sh:36` |
| D5 | 토큰 강도 검사: 32자 이상, 서로 다른 문자 8종 이상. 주석은 OWASP 세션 관리 치트시트·NIST SP 800-63B를 "참고, 원문은 다시 확인하지 않았다"고 적음. 문자 종류 8은 근거 없음 | ? | 인용된 표준을 이 점검에서도 대조하지 못함 | `app.py:44` 주석만 | `service/app.py:44,63-68` |
| D6 | 자격 수명주기: 발급은 deploy(`gen-secrets`, 이 영역 밖, 읽지 않음), 보관은 파일(D84). 갱신·폐기·만료는 이 영역 문서에 없다(시작 때 한 번 읽으므로 교체는 재시작이 필요하다는 것은 코드에서 추정) | N- | 없음 | 근거 기록 없음(이 영역) | `service/app.py:498-502`, `docs/boundary.md:50-52` |
| D7 | 토큰 목록 형식 `역할=토큰,역할=토큰`(한 파일) | N | 없음 | 계약 `HTTP.md:11`이 정함 | `service/app.py:47-60` |
| D8 | 인증 실패 제한(주소당 10회/60초, 차단 중에는 올바른 토큰도 503). 직접 구현한 속도 제한이다. 프록시·게이트웨이·fail2ban류를 쓰지 않은 이유는 적혀 있지 않다(내부망 전용이라 한계를 "수용"한다고만 함, 같은 주소 호출자 전체가 막히는 한계 명시) | O | 속도 제한은 리버스 프록시·게이트웨이가 제공하는 기능 | ADR 0012에 한계는 있으나 "왜 가져다 쓰지 않았나"는 없음 | `service/app.py:126-144,335-342` |
| D9 | 헤더 수신 총 시간 마감(`_DeadlineRaw`, 10초, slowloris 완화), 연결 수·게시·다운로드 상한을 직접 구현. 본문 총 시간 마감은 없음(한계로 명시). 이런 방어는 프로덕션 서버나 프록시가 제공한다 | O | slowloris 방어는 서버·프록시 기능 | ADR 0012(소켓 timeout이 recv마다라 부족하다는 이유는 있음, 가져다 쓰지 않은 이유는 없음) | `service/app.py:200-226,463-488` |
| D10 | 자원 한도 값: 본문 1GiB, 소켓 timeout 30초, 동시 연결 32, 게시 8, 다운로드 8, tar 항목 1000, 디스크 3n+1GB, 헤더 마감 10초, 인증 실패 10회/60초, 이름 255바이트. 모두 측정 안 함(255바이트만 파일 시스템 한계라는 제약) | N | 없음(255바이트는 일반적 파일 시스템 이름 한계) | ADR 0012("측정하지 않은 보수적 시작값") | `service/app.py:72-76,99-103,506-514`, `service/tarutil.py:28` |
| D11 | 동시성 모델: 연결당 스레드 + 세마포어 상한 + 데이터셋 ID 단위 락(프로세스 안). 단일 프로세스·단일 복제본이라는 전제는 문서에 없다(여러 프로세스면 락이 무효) | N | 없음 | ADR 0012(락 단위 이유 설명). 단일 인스턴스 전제는 근거 기록 없음 | `service/app.py:89-93,157-170` |
| D12 | tar 수신: 일반 파일만, 링크·장치·sparse·`..`·절대 경로·중복 이름 거부, 압축 안 된 tar만, 항목 수·총 크기 상한. 직접 풀되 `extractall`을 쓰지 않아 경로 이탈 위험이 낮다(Python 3.12의 `filter='data'`는 쓰지 않음) | S- | CWE-22(경로 이탈) 대응 관행. ADR이 표준 이름은 안 적음 | ADR 0012 검증 항목 | `service/tarutil.py:31-66` |
| D13 | `Content-Length` 엄격 검사(숫자 하나만, 아니면 400)와 인증 전 검사 | S- | RFC 9112의 메시지 본문 길이 규칙(요청 밀반입 방어). ADR은 "요청 밀반입 방어"라고만 적음 | ADR 0012 | `service/app.py:292-297,325` |
| D14 | `Transfer-Encoding: chunked` 요청 본문은 지원하지 않고 `Content-Length` 필수(없으면 400). 프록시 뒤에서 TE와 CL이 함께 오는 경우의 처리는 시험을 읽지 않아 확인 못 함 | ? | RFC 9112 | 근거 기록 없음 | `service/app.py:383-386` |
| D15 | HEAD/OPTIONS는 405 + `Allow`, 모르는 메서드 토큰의 501은 RFC 9110 15.6.2대로 둠 | S | RFC 9110(405, 501) | ADR 0012 보강 | `service/app.py:451-458` |
| D16 | `/healthz`, `/readyz`(저장 볼륨·임시 폴더 쓰기 확인), 인증 전, 인증 실패 제한과 무관 | S | 워크스페이스 규칙(D22)과 프로브 관행 | CLAUDE.md(루트), ADR 0012 | `service/app.py:328-332`, `service/app.py:145-153` |
| D17 | 로그 = 표준 출력, 자유 형식 문자열(구조화 로그 아님), 토큰·본문 안 남김. 메트릭 엔드포인트 없음, 추적 없음 | S- | 12-factor 로그 항목(이벤트 스트림) | 근거 기록 없음. 메트릭 부재는 ADR 없음 | `service/app.py:270-272,526` |
| D18 | 기본 바인드 `0.0.0.0`(컨테이너 포트 게시에 필요), 프로세스 정상 종료(SIGTERM 처리, 진행 중 요청 대기) | S- | 컨테이너 관행 | 근거 기록 없음 | `service/app.py:518-523`, `service/app.py:464-465` |
| D19 | TLS 없음(내부망 전제). 근거는 deploy ADR 0032·D103 L05라고 ADR이 가리키나 이 점검에서는 읽지 않아 확인 못 함 | N | 없음 | ADR 0012 결과, ADR 0013 결과(다른 영역 문서 인용, 미확인) | `docs/adr/0012` 결과절, `docs/adr/0013` 결과절 |
| D20 | 쓰기 토큰도 읽기 허용, 읽기 경로는 읽기·쓰기 토큰 모두 허용 | N | 없음 | ADR 0012 | `service/app.py:116-117` |

### E. 잡 설정, 어댑터 factory, 실행, 빌드·배포

| ID | 요소 | 분류 | 표준 이름 | 근거 위치 | 증거 |
|---|---|---|---|---|---|
| E1 | 잡 설정 = JSON 파일 하나, 상대 경로는 설정 파일 기준, 비밀은 설정에 넣지 않음 | S- | RFC 8259(JSON) | D39(영역 간 자동화는 잡+설정 파일) | `config.py:137-143`, `store/spec.py:27-28` |
| E2 | 알 수 없는 최상위 키 거부(`KNOWN_KEYS`, `IMPORT_KNOWN_KEYS`). 하위 객체(`tolerance`, `output` 등)의 알 수 없는 키는 거부하지 않는다(오타 가능) | N | 없음(fail fast) | ADR 0014 | `config.py:75-82`, `importer.py:116-123` |
| E3 | 어댑터 factory = 설정의 `"module:function"` 문자열을 `importlib.import_module`+`getattr`로 직접 로드. `module:attr` 표기는 파이썬 entry point 표기와 같지만 entry point 메커니즘(`importlib.metadata`)은 쓰지 않았고, 설정 작성자가 `PYTHONPATH`의 임의 모듈을 실행할 수 있다(설정을 신뢰한다는 전제가 문서에 없음). ADR 없음, `design.md:67`은 용도만 설명하고 이 방식을 고른 이유(대안 비교)는 없음 | N- | 없음(entry point 표기 유사, 메커니즘은 다름) | 근거 기록 없음(용도 설명만: `design.md:67`, `adapters.py:1-6`) | `job.py:44-46`, `config.py:67-71`, `job.py:245-246` |
| E4 | 운영 어댑터 두 개(`http_question_reader`, `http_failure_store`)는 계약 클라이언트를 얇게 감싼 공장, 토큰은 `read_secret(NAME)`(`NAME_FILE` 우선) | S | 워크스페이스 D84(파일 비밀, Docker/Compose `_FILE` 관행) | D84(CLAUDE.md), `runbook.md` 비밀 절 | `adapters.py:16-30` |
| E5 | 개발용 설정은 `tests/doubles.py`(이웃 대역)를 `PYTHONPATH=tests`로 로드 | S- | 없음(D22 규칙: 이웃은 메모리 구현으로 대신) | CLAUDE.md(루트) D22 | `configs/dev.job.json:11-16`, `runbook.md:73` |
| E6 | run-once 잡, 종료 코드: 0 성공, 2 설정, 3 경계(재시도 불가), 75 재시도 가능, 4 허용치 초과. 75는 BSD `sysexits.h`의 `EX_TEMPFAIL`과 같은 값으로 알고 있으나 ADR·주석은 이를 인용하지 않는다. 2·3·4는 자체 규약 | S- | sysexits.h(75) 부분, 나머지 없음 | D39. 값 선택의 근거 기록 없음 | `__main__.py:1-4,33,37,40` |
| E7 | 잡 HTTP 게시 timeout 60초(측정 안 함), 읽기 어댑터 기본 timeout 10초(근거 없음), 목록 페이지 크기 100(근거 없음), 서버 limit 상한 500(근거 없음) | N- | 없음 | 60초는 ADR 0013이 "측정 안 함"으로 명시(그 경우 N). 10초·100·500은 근거 기록 없음 | `store/spec.py:13`, `adapters.py:23,27`, `job.py:64`, `seeds.py:27`, `service/app.py:256` |
| E8 | 재시도: 잡은 재시도하지 않고 종료 코드 75로 스케줄러에 넘김(D39). 설치 스크립트만 1회·5초 재시도 | S- | 없음 | D39(CLAUDE.md). `setup-env.sh`는 "왜 1회 재시도" 주석, 5초는 근거 없음 | `__main__.py:40`, `scripts/setup-env.sh:22-25` |
| E9 | 의존 고정: `requirements.lock`(경계 계약·문진 스키마는 git 태그, 나머지 `==`), 서비스 이미지는 `requirements-service.txt`로 따로 복제 고정. 해시 고정(`pip --require-hashes`)은 없다. 태그는 변경 가능한 참조다 | N- | pip 해시 확인 모드가 표준 수단이나 쓰지 않음. 태그 고정은 루트 CLAUDE.md 규칙 | 태그 고정은 CLAUDE.md. 해시 미사용·`requirements-service.txt` 복제의 이유는 근거 기록 없음 | `requirements.lock:1-11`, `requirements-service.txt:1-5` |
| E10 | `jsonschema==4.10.3` 고정(2022년대 버전으로 알고 있음). 고른 이유는 근거 기록 없음(CR-008 검증 환경으로만 언급) | S- | 버전 고정 관행 | 근거 기록 없음 | `pyproject.toml:12`, `requirements.lock:6` |
| E11 | Dockerfile: 다단계 빌드, 비루트 uid 10001, `HEALTHCHECK`, 라벨 6종(D50), 비밀 없음, 문진 스키마는 `--build-context`로 받음 | S | Docker 모범 사례(다단계·비루트), D22/D50, BuildKit 추가 컨텍스트 | 루트 CLAUDE.md, ADR 0011 | `Dockerfile:11-44`, ADR 0011 |
| E12 | 베이스 이미지 `python:3.12-slim`(태그만, digest 고정 없음). 소프트웨어는 `requires-python>=3.10`이라 3.12를 고른 이유도 없다. `apt-get install git openssh-client`는 버전 미고정 | N- | Docker 모범 사례(베이스 이미지 버전·digest 고정 권장). 따르지 않음 | 근거 기록 없음 | `Dockerfile:11,21,14`, `pyproject.toml:8` |
| E13 | 빌드 때 `ssh-keyscan github.com`으로 호스트 키를 받음(지문 검증 없음, 실패는 `|| true`로 무시). Docker 문서의 SSH 마운트 예시와 같은 형태로 알고 있으나 원문을 재확인하지 못함 | ? | 표준 여부(그리고 지문 검증 생략의 적절성) 확인 못 함 | 근거 기록 없음 | `Dockerfile:14-15` |
| E14 | 스모크: 포트는 Docker 배정(`-p 127.0.0.1::8080`), 토큰은 `/dev/urandom` 생성 파일로 전달, 로그에 비밀이 있으면 실패(`assert_no_secret.sh`) | S | 루트 CLAUDE.md(D22, D84) | CLAUDE.md, 스크립트 주석 | `scripts/smoke_service.sh:29-33`, `scripts/assert_no_secret.sh` |
| E15 | 시드 `run` 존속, `regeneration.mode`·감수 샘플링 유지 | N | 없음 | ADR 0010(대안 비교, 헤드 결정 2026-10-28) | `job.py:223-236`, ADR 0010 |

## 2. 요약 개수

(1절 표의 분류 열을 awk로 세었다. E13은 셀 안에 `|`가 있어 awk가 열을 잘못 나누므로 ?로 따로 더했다. 센 방법은 6절.)

| 분류 | 개수 |
|---|---|
| S | 11 |
| S- | 13 |
| N | 24 |
| N- | 18 |
| O | 2 |
| ? | 5 |
| 합계 | 73 |

## 3. N- / O / ? 목록 (한 줄씩)

N-
- A3 `fsync` 없는 rename 게시: 정전 시 빈 파일 버전이 가능(추정)하고 같은 hash 재게시는 파일을 재검증하지 않고 성공 처리(`store/file_store.py:51-56`, `store/base.py:100-103`).
- A4 `meta.json` seq 설계: 이유 기록 없음, 동시 게시 경합의 원인이 되어 서버 락이 필요(`store/file_store.py:48,54`).
- A7 버전 이름 digest 앞 12자리(48비트): 근거 기록 없음(ADR 0006이 인정), 충돌 확률 미계산(`importer.py:431`).
- A10 ALREADY_PUBLISHED 판정이 `import`와 `run`에서 다름(`job.py:192` vs `importer.py:446`).
- A11 보존 기간·삭제·백업 정책이 어디에도 없음.
- B3 값 비노출 주장 불일치: publish 오류 메시지에 jsonschema 메시지(값 포함, 200자)가 실려 보고서·stderr·HTTP 본문으로 나감(`schemas.py:21,81`, `service/app.py:303`; 주장은 `design.md:96`).
- B6 발화+맥락 키의 맥락 범위: "근거 기록 없음".
- B14 PII 의심 패턴 기본값이 경고만(검출돼도 게시), ADR 0005 제목("가장 엄격")과 불일치(`importer.py:154-156,356`).
- B17 입력 전체를 메모리에 읽음, 한계 미측정(`importer.py:259`).
- B18 `run`의 감수 샘플링 `per_kind=2` 등: 값의 근거 없음, 산출물을 읽는 곳 없음(`config.py:132`).
- C3 `PII_SCAN_LIMIT` 20,000자: 초과 구간 패턴을 조용히 놓침, 측정 안 함(`importer.py:54`).
- C4 `run`(시드) 경로에 PII 의심 패턴 검사가 없고 `deidentified` 플래그에 의존(`seeds.py:293`).
- D4 인증 실패를 403으로 답함(RFC 9110은 401): 계약 소관이고 이 영역에 근거 기록 없음(`CONVENTIONS.md:86`).
- D6 자격 갱신·폐기·만료 절차가 이 영역 문서에 없음.
- E3 어댑터 factory를 `importlib`로 직접 로드: ADR 없음, 대안 비교 없음, 임의 모듈 로드의 신뢰 전제 미기록(`job.py:44-46`).
- E7 timeout 10초·페이지 100·limit 500 등 값의 근거 없음(60초는 "측정 안 함" 명시).
- E9 의존 고정에 해시 확인 없음, `requirements-service.txt` 복제 이유 기록 없음.
- E12 베이스 이미지 digest·패치 버전 미고정, 3.12를 고른 이유 없음(`Dockerfile:11,21`).

O
- D8 인증 실패 속도 제한을 직접 구현(프록시·게이트웨이 대신), 가져다 쓰지 않은 이유 기록 없음(`service/app.py:126-144`).
- D9 slowloris 방어(헤더 마감 래퍼)·연결 수 제한을 표준 라이브러리 서버 위에 직접 구현, 프로덕션 서버나 프록시를 쓰지 않은 이유 기록 없음(`service/app.py:200-226,463-488`).

?
- B8 해시 구간 분할 방식의 표준 이름 확인 못 함(ADR 없음).
- B10 시드 정수 + `sha256` 파생 난수의 표준 이름 확인 못 함(ADR 없음).
- D5 토큰 강도 기준(32자, 문자 8종)이 인용한 OWASP·NIST 문서와 맞는지 확인 못 함(코드 주석도 재확인 안 했다고 적음).
- D14 chunked 요청 본문·TE/CL 동시 입력 처리를 확인 못 함.
- E13 빌드 중 `ssh-keyscan`의 표준성과 지문 검증 생략의 적절성 확인 못 함.

## 4. 요소 밖에서 본 문서 어긋남 (분류 대상 아님, 참고)

- `docs/runbook.md:77`, `README.md:44`: "Dockerfile 없이", "서비스가 없는 잡"이라고 쓰지만 `Dockerfile`과 I2 서버가 있다(같은 README 2절이 서버를 설명).
- `docs/runbook.md:12`: GPU 호스트 절이 이웃 토큰을 "실행 셸의 환경 변수로만" 주라고 하지만 D84는 `NAME_FILE` 파일이다. 같은 문서 비밀 절과 어긋난다.
- `docs/runbook.md:49`: 옛 v1 키를 "받되 무시"한다고 쓰지만 ADR 0014는 거부한다.
- `README.md:107`: "ADR 0001~0010"이나 실제는 0001~0014. `docs/STATUS.md` 첫 줄은 boundary-contracts v2.0.2, `requirements.lock`은 v2.1.1.
- `docs/adr/0004` 결정 문단은 처음 정의(발화+맥락)를 설명하고, 판정 키가 엄격 키로 바뀐 것은 뒤쪽 "실측으로 바뀐 결정" 절에만 있다(Supersedes 새 ADR이 아님).
- ADR 0005 제목은 "기본값은 가장 엄격하다"이나 B13·B14의 기본값은 그렇지 않다.

## 5. 점검하지 못한 것

- 시험 파일(`tests/*`)은 읽지 않았다. 시험이 있다고 문서가 말하는 것(ReDoS 1초, 퍼징, 해시 canonical 전용 등)은 확인하지 않았다. 코드를 돌리거나 시험을 실행하지도 않았다.
- 인용된 외부 표준의 원문은 읽지 않았다(RFC 6750·8785·9110·9112, UAX #15·#44, OWASP, NIST, POSIX, Docker 문서, Python `http.server` 문서). 표의 표준 설명은 내가 아는 범위의 것이고, 위 `?` 항목은 그렇지 못한 곳이다.
- 헤드·deploy 문서(`head/docs/*`, `DECISIONS.md` D번호, deploy ADR 0032, D103)는 읽을 수 없어 확인하지 않았다. 인용된 D번호의 내용은 이 영역 문서에 적힌 만큼만 안다. 토큰 발급(`gen-secrets`)도 읽지 않았다.
- `boundary-contracts`는 `HTTP.md:11`, `CONVENTIONS.md:86`, `canonical.py` 일부만 읽었다. 계약 패키지 안의 클라이언트(`HttpDatasetStore` 등)의 timeout·재시도·TLS 처리는 점검하지 않았다.
- `docs/change-requests/CR-001~008`은 CR-005 일부만 읽었다. `docs/rules/*`(업무 규칙), `docs/CHANGELOG.md`, `docs/audit/structure-rules-2026-10-28.md`, `tests/doubles.py`, `tests/ref_server.py`는 읽지 않았다.
- 실제 데이터 파일과 `data/`, 빌드 로그(`data/build_C1.log`)는 읽지 않았다(워크스페이스 규칙상 범위 밖). 실측 값(64,459행, 중복 건수 등)은 ADR·design.md의 진술이며 재현하지 않았다.
- 도커 이미지는 빌드하지 않았고 컨테이너 안 동작(권한, healthcheck)은 확인하지 못했다.
- `.git` 이력, 비밀 파일, 환경 변수는 읽지 않았다.

## 6. 개수를 센 방법

1절 표에서 ID 행의 분류 열을 `awk -F'|'`로 세었다(E13 한 행은 수동 보정). 나중에 표를 고치면 2절도 함께 고쳐야 한다.
