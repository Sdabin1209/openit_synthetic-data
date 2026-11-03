# schemas/: 영역 내부 타입의 JSON Schema (draft 2020-12)

타입 하나에 파일 하나(`<타입>.schema.json`), 통과·거부 예시는 `examples/<타입>.valid*.json`, `<타입>.invalid*.json`이다. 정본은 이 폴더이고 코드 타입(`synthetic_data/types/`)과 스키마 사본(`types/schema_registry.py`)은 여기서 생성한다(README 4절). 영역 사이 타입(DatasetManifest, ActionExtractionSample, FailureCase, QuestionBank, 잡 설정·보고서 등)은 복사하지 않고 계약(boundary-contracts)을 쓴다: 계약 타입이 든 자리는 `{"type":"object"}`로 두고 컴포넌트가 계약 스키마로 검사한다(`contract_codes`, `check_contract`).

타입이 어느 컴포넌트의 입력·출력인지는 `docs/components.md`에 있다. `TrainingDataRow`는 외부 학습 데이터 jsonl 한 행의 형식이다(데이터셋 담당과의 형식이라 계약으로 승격하지 않았다, U49).

## 스키마로 옮긴 거부 조건

기존 코드의 거부 지점(if 검사, raise, ConfigError 등)을 전부 훑어 아래처럼 옮겼다.

| 기존 거부 | 옮긴 곳 |
|---|---|
| 행 모양: messages가 [system,user,assistant] 세 개, content는 문자열 | `TrainingDataRow` |
| scenario_id가 문자열 | `TrainingDataRow` |
| 입력 파일 이름이 역할·분할을 정함(lora_a는 LORA_A, _val은 VALIDATION 등) | `ImportSource`, `ImportTallyInput`의 `allOf` if/then |
| 줄 판정: 통과면 샘플과 빈 사유, 실패면 sample null과 사유 | `RowVerdict`의 `oneOf` |
| 분할 비율의 합이 0보다 큼 | `RunPlan.ratios`의 `anyOf`(음수 아님과 함께) |
| seeds.enabled인데 failure_store가 없음 | `RunPlan`의 `if/then` |
| 저장소 종류별 필수(file은 root, http는 http 설정, memory는 둘 다 없음) | `RunPlan.store`, `ImportPlan.store`의 `if/then` |
| 비식별(deidentified=true)이 아닌 실패 사례 | `SeedCollectInput.cases[].deidentified`의 `const true` |
| 시드의 정답 모양(LORA_A는 객체, LORA_B는 문자열) | `Seed`의 `if/then` |
| dataset_id·version 문자 규칙과 길이, 파일 경로 정규형('..'·절대 경로·역슬래시·빈 마디·'.' 없음) | `PublishRequest`, `ManifestRequest`, `VersionsRequest`, `FileRequest`, `PublishDecisionInput`의 `pattern` |
| 서비스 시작 시 읽기·쓰기 토큰이 하나도 없음 | `ServiceSettings`의 `anyOf` |
| 허용치 범위(건수 0 이상, 비율 0~1, 의심 행 허용치 정수 또는 null) | `ImportJudgeInput.tolerance`, `ImportPlan.tolerance` |
| 문항 세트 판정 결과의 모양(ADMITTED는 context, REJECTED는 error) | `QuestionSetAdmission`의 `if/then` |
| 개인정보 관문 거부 시 메시지 필수 | `SeedPiiGateResult`의 `if/then` |

## 스키마 밖 조건

스키마로 쓰지 못한 조건이다(목표 0건). 이유는 셋 중 하나다: 교차 필드·교차 레코드 집합 연산, 계산한 값과의 비교(해시), 실행 시점 상태(파일 시스템·설치된 패키지·이웃의 스키마 파일)에 기대는 조건.

| # | 조건 | 어디서 | 이유 |
|---|---|---|---|
| 1 | 같은 문항 세트 id를 TRAIN_POOL과 HELD_OUT_EVAL에 함께 쓰지 않음 | `run_plan` | 배열 원소 사이의 키별 일관성(집합 제약)이다 |
| 2 | seeds.question_set_id가 question_sets의 id 중 하나(시드가 켜졌을 때) | `run_plan` | 한 필드가 다른 배열의 원소를 가리키는 교차 참조다 |
| 3 | 설정의 action_rules_version이 설치된 계약의 규칙 세대와 같음 | `run_plan`, `import_plan` | 비교 대상이 실행 시점에 설치된 계약 데이터라 `const`로 적을 수 없다(입력에 값은 담아 오지만 같음 비교는 필드 사이 비교다) |
| 4 | 설정 파일을 읽을 수 있음, 최상위가 객체 | `config.py` | 파일 시스템 상태다 |
| 5 | 입력 디렉터리와 jsonl 6개가 있음 | `import_source` | 파일 시스템 상태다 |
| 6 | 실패 줄 수 ≤ max_invalid_rows, 실패율 ≤ max_invalid_rate, 통과한 행이 없는 파일 없음 | `import_judge` | 두 필드 사이 산술 비교다 |
| 7 | pending_policy=reject일 때 pending 행 없음, 의심 행 ≤ 허용치 | `import_judge` | 두 필드 사이 비교다 |
| 8 | 분할 사이 같은 입력 수 ≤ 허용치, 같은 scenario_id가 두 분할에 걸치지 않음 | `import_overlap` | 레코드 집합 사이의 교차 연산이다 |
| 9 | 문항 세트 승인(APPROVED이고 clinical_basis_approved)이 있음 | `question_set_admit` | 거부 입력이 아니라 판정 결과(REJECTED, FAILED_PRECONDITION)로 낸다 |
| 10 | QuestionBank 해시가 ArtifactRef.content_hash와 같음 | `question_set_admit` | 계산한 해시와의 비교다 |
| 11 | QuestionBank가 문진 스키마를 통과 | `question_set_admit` | 이웃 영역의 스키마 파일(설치된 문진 스키마)로 검사한다. wiring이 검사 함수를 주입한다 |
| 12 | regeneration.mode=affected_only이면 변경 분류에 REGENERATE_SAMPLES가 있음 | `question_set_admit` | 거부 입력이 아니라 판정 결과(SKIPPED)다 |
| 13 | 실패 사례가 이번 문진 스키마 정수 버전과 같음, CONFIRMED, expected·reviewed_input이 있고 계약 입출력 스키마를 통과 | `seed_collect` | 거부 입력이 아니라 "건너뜀 + 사유"가 정상 출력이다(실행 시점의 정수 버전과 비교) |
| 14 | 시드의 문항이 지정한 문항 세트에 있음, 시드가 학습 풀 문항 세트에 짝지어짐 | `seed_pairing`, `seed_assemble` | 교차 참조이고 건너뜀 + 사유가 정상 출력이다 |
| 15 | 개인정보 의심 시드 수 ≤ 허용치 | `seed_pii_gate` | 두 필드 사이 비교이고 결과는 거부 출력이다 |
| 16 | 샘플이 계약 샘플 스키마를 통과 | `sample_quality` | 계약 스키마로 검사한다(영역 스키마에 복사하지 않는다) |
| 17 | 매니페스트의 files[].path 중복 없음 | `dataset_store` | 배열 원소의 속성 유일성이다 |
| 18 | 게시 파일 집합과 manifest.files[].path 집합이 같음, 각 파일의 해시·줄 수(sample_count)·샘플 split·question_set·seed_case_id가 매니페스트와 맞음 | `dataset_store` | 계산한 해시·줄 수와 파일 내용을 매니페스트와 대조한다 |
| 19 | sample_id가 전역 유일, scenario_id가 분할 사이에 겹치지 않음 | `dataset_store` | 레코드 집합 사이의 조건이다 |
| 20 | 매니페스트의 content_hash가 내용과 같음, 같은 (dataset_id, version)에 다른 내용이면 CONFLICT, 문진 정수 버전·pipeline MAJOR 일치 | `dataset_store` | 계산한 해시, 저장소 상태, 실행 시점 버전과의 비교다 |
| 21 | tar 요청의 형식(압축 없음, 일반 파일만, 경로 정규형, 항목 수·총 크기 상한, manifest.json과 files/ 밖의 항목 없음) | `link_dataset_store_server` | 요청 본문이 JSON이 아니라 바이트 스트림(tar)이다 |
| 22 | 쿼리의 cursor(숫자)·limit(1 이상, 500 상한) | `link_dataset_store_server` | 쿼리 문자열은 요청 스키마의 대상이 아니다(openit_link.Route는 JSON 본문만 스키마로 검사) |
| 23 | 디스크 여유, 동시 게시·다운로드 상한, 인증 실패 횟수 제한 | `link_dataset_store_server` | 서버의 실행 시점 상태다 |
| 24 | 토큰 목록 문자열의 해석('역할=토큰', 쓰기 역할은 synthetic-data만, 읽기·쓰기에 같은 토큰 없음, 토큰 강도) | `link_dataset_store_server` | 값이 비밀이라 스키마 예시·오류 메시지에 실을 수 없는 문자열 안의 목록이다 |
| 25 | 쓰기 토큰이 있음(`NAME_FILE` 또는 `NAME`) | `link_dataset_publish`, `link_question_reader`, `link_failure_reader` | 파일 시스템·환경 상태다 |

## 약속

- 컴포넌트는 입력을 스키마 검증 하나로 거부한다(코드 안에 따로 거부 조건을 두지 않는다). 위 표의 조건만 예외이고, 결과는 "판정 출력"이거나 이유가 적힌 오류다.
- 오류 메시지에는 위반한 값을 싣지 않는다(위치와 스키마 키워드만, ADR 0003).
