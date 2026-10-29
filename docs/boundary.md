# 경계 문서: synthetic-data

근거: `../boundary-contracts/INTERFACES.md`, `CONVENTIONS.md`. 상대 영역은 블랙박스로 보고 이 명세 밖을 가정하지 않는다.

## 1. 소유하는 저장소

데이터셋 저장소(불변 버전). 쓰는 영역은 이 영역뿐이다. 구현은 파일 기반(`FileDatasetStore`)과 메모리(`MemoryDatasetStore`)이며, 배치는 `<root>/<dataset_id>/<version>/{manifest.json, meta.json, files/<path>}`. 한 번 게시한 `(dataset_id, version)`은 바뀌지 않는다(같은 내용의 재게시는 멱등, 다른 내용은 CONFLICT).

## 2. 제공하는 인터페이스 (HTTP 서버와 SDK)

**HTTP(운영, D100·D49)**: dataset-store 서버(`synthetic_data/service/`)가 `boundary-contracts/HTTP.md ## I2`를 서비스한다. 읽기 토큰은 소비자(model-lab), 쓰기 토큰(역할 `synthetic-data`)은 이 영역의 잡이 쓴다. 경로·인증·한도의 근거는 `docs/adr/0012`, 잡의 게시 설정은 `docs/adr/0013`이다. 이웃은 이 영역의 저장소 볼륨을 읽지 않는다.

아래는 서버 안에서 쓰는 저장소 구현과 같은 Protocol이다(로컬 개발·시험용으로 직접 쓸 수도 있다).

**I2 DatasetStore** (`boundary_contracts.sdk.DatasetStore` Protocol). 생성자 인자로만 설정을 받고 환경 변수를 읽지 않는다.

```python
from synthetic_data.schemas import Validators
from synthetic_data.store import FileDatasetStore, MemoryDatasetStore
v = Validators(survey_schema_dir=<문진 스키마 디렉터리>)       # 게시(쓰기)에는 필요, 읽기만 하면 생략 가능
store = FileDatasetStore(root, v)     # 또는 MemoryDatasetStore(v)
```

| 호출 | 동작 | 오류 |
| --- | --- | --- |
| `publish(manifest, files)` | 5절의 검증 후 원자적 저장. 멱등 | INVALID_RECORD, INTEGRITY_ERROR, CONFLICT, UNSUPPORTED_VERSION, UNAVAILABLE |
| `get_manifest(dataset_id, version)` | 매니페스트 반환, 저장된 content_hash 재확인 | NOT_FOUND, INTEGRITY_ERROR |
| `list_versions(dataset_id)` | 게시 순서(오래된 것부터). 모르는 데이터셋은 `[]` | |
| `open_file(dataset_id, version, path)` | 파일 해시 재확인 후 `BinaryIO` | NOT_FOUND, INTEGRITY_ERROR |

- 모든 실패는 `BoundaryError`다. 메모리 구현도 같은 조건에서 같은 코드를 던진다(같은 적합성 시험).
- 소비자는 model-lab이고 운영에서는 HTTP 클라이언트(`HttpDatasetStore`)로 읽는다. 읽기용 별도 SDK는 없다.
- `dataset_id`와 `version`은 Id 규칙(`[A-Za-z0-9][A-Za-z0-9._:-]*`, 128자 이하)을 지켜야 한다(경로 안전, CR-005). 파일 경로(`files[].path`)는 상대 경로이고 `..`, 절대 경로, 중복 슬래시를 쓸 수 없다.

## 3. 산출 계약

`ActionExtractionSample`(role `LORA_A`), `ResponseSample`(role `LORA_B`)(JSON Lines, UTF-8), `DatasetManifest`(스키마 버전은 설치된 boundary-contracts 패키지가 정본, D74). 파일은 `lora_a/{train,validation,eval,eval_unseen}.jsonl`, `lora_b/...`. 샘플의 `input`/`expected`는 `ActionExtractionInput`/`ActionExtraction`, `ResponseRequest`/`ResponseText`(문자열)이며 샘플 스키마가 함께 검증한다. 샘플에 `runtime_contract_version`·`style_guide_version`은 없다(매니페스트에는 `runtime_contract_version`이 그대로 있다). `eval_unseen`은 학습에 쓰지 않은 문항 세트의 평가 샘플이고 `files[].question_sets`로 표시한다(D32). 모든 파일의 `files[].question_sets`에 그 파일의 샘플이 쓰는 문항 세트가 적힌다. `ext["synthetic-data"]`의 내용(소비자는 판단에 쓰지 않는다): 샘플 `kind`, `utterance_generator`/`response_generator`, `directive_source`; 매니페스트 `dataset_digest`, `unseen_eval_files`. 정식 필드 승격은 CR-004.

## 4. 소비하는 것과 지원 버전

| 소비 | 인터페이스 | 용도 | 영역 안의 형태 |
| --- | --- | --- | --- |
| 문항, 변경 분류 | I1 `QuestionReader` | `latest(reviewed_only)`, `list_versions`, `get_question_bank`(해시 재확인), `get_reviews`, `get_change`(REGENERATE_SAMPLES) | 설정의 `adapters.question_reader.factory`가 만든 객체. Protocol만 안다 |
| 실패 사례, 비식별 trace | I7 `FailureStore`(`question_set`, `expected_kind` 사용, 없으면 폴백) | `list_cases(review_status=CONFIRMED)`, `get_trace` | `adapters.failure_store.factory` |

2026-10-28(헤드 허가, ADR 0010): 위 I1·I7은 시드 잡 `run`만 소비한다. `import` 모드는 이웃 읽기 SDK를 쓰지 않고 파일 jsonl 6개를 읽는다. v1 합성 생성은 제거돼 I1은 문항 세트 참조·본문 확인용이다.
| LoRA-A 출력 규칙의 세대 | 계약 규칙 데이터 | `boundary_contracts.action_rules.load_rules()["rules_version"]` | 매니페스트 `action_rules_version`. 설정 값은 기대값이라 다르면 거부 |

- 이웃 코드를 가져오지 않는다. 의존은 boundary-contracts(Protocol, 오류, 해시), 문진 스키마(읽기 전용 파일)뿐이다.
- 사용하는 비밀(D84: `NAME_FILE`로 파일 경로를 받고 `read_secret(NAME)`으로 읽는다. 환경 변수 `NAME`은 개발용):
  - 서버(dataset-store) 쪽, 복수형(역할=토큰 목록 파일): `DATASET_STORE_READ_TOKENS_FILE`, `DATASET_STORE_WRITE_TOKENS_FILE`.
  - 잡(`run`/`import`의 `store.kind=http`) 쪽, 단수형(쓰기 토큰 값 하나): `DATASET_STORE_WRITE_TOKEN_FILE`(`token_env` 설정으로 이름을 바꿀 수 있다).
  - 정본 배선은 deploy compose를 본다(이 목록은 이름만 적는다).
- 지원 버전: 문진 스키마 정수 버전은 `CONTRACT_VERSION`과 정확히 일치해야 한다(현재 1, 다르면 `UNSUPPORTED_VERSION`). 경계 계약은 `pipeline_schema_version` MAJOR 2(쓰는 값은 설치된 `boundary_contracts.PIPELINE_SCHEMA_VERSION`, 계약 태그는 `requirements.lock`). 이웃 호출은 HTTP(`boundary_contracts.clients.HttpQuestionReader`/`HttpFailureStore`, 설정의 factory로 선택). 다른 MAJOR는 `UNSUPPORTED_VERSION`이다. 쓸 때는 엄격하다(`additionalProperties: false`라 모르는 필드는 `INVALID_RECORD`). 저장된 파일은 해석하지 않고 바이트 그대로 돌려주므로 `ext`는 보존된다.
- 시험용 대역은 `tests/doubles.py`(`FakeQuestionReader`, `FakeFailureStore`)에 있다. 소유 영역의 메모리 구현이 나오면 설정의 `factory` 문자열만 바꾼다.
- 비식별되지 않은 실패 사례(`deidentified != true`)를 받으면 실행을 `INVALID_RECORD`로 거부한다.

## 5. 게시 검증 (I2 `publish`)

1. 매니페스트가 `DatasetManifest` 스키마를 통과, `scenario_disjoint_across_splits=true`.
2. `content_hash` == `canonical.content_hash(manifest)` (아니면 INTEGRITY_ERROR).
3. 같은 `(dataset_id, version)`: 같은 hash면 기존 것을 반환(멱등), 다르면 CONFLICT.
4. `runtime_contract_version` == 문진 스키마 `CONTRACT_VERSION`.
5. `files`의 키 집합 == `manifest.files[].path`.
6. 파일마다: `canonical.file_hash` 일치(INTEGRITY_ERROR), 줄마다 `ActionExtractionSample`(LORA_A)/`ResponseSample`(LORA_B) 스키마, `split`이 파일과 일치, `question_set`이 파일의 문항 세트 안에 있음, `seed_case_id`가 `manifest.seed_case_ids`에 있음, `sample_id` 유일, 줄 수 == `sample_count`.
7. 분할 간 `scenario_id` 겹침(EVAL-TRAIN, EVAL-VALIDATION, TRAIN-VALIDATION)이 있으면 INVALID_RECORD.

## 6. 장애 영향

| 상황 | 영향 | 처리 |
| --- | --- | --- |
| 이 영역(잡)이 멈춤 | 새 데이터셋이 안 생긴다. 기존 버전은 불변이라 model-lab의 읽기는 계속된다 | 필요할 때만 도는 작업이라 가용성 요구 없음. 재실행이 안전하다(멱등) |
| 저장소 디스크 문제 | 게시가 `UNAVAILABLE`(재시도 가능). 반쯤 쓴 버전은 보이지 않는다(임시 디렉터리 후 rename) | 재시도 |
| 저장된 파일 훼손 | `open_file`/`get_manifest`가 `INTEGRITY_ERROR` | 새 버전으로 다시 게시 |
| I1이 `UNAVAILABLE` | 잡이 `BoundaryError`로 끝나고 종료 코드 75, 아무것도 게시하지 않음 | 스케줄러가 재시도 |
| I1/I7 데이터가 스키마·해시 위반 | `INVALID_RECORD`/`INTEGRITY_ERROR`로 잡 중단 | 상대 영역 확인 |
| 비식별 안 된 사례 | 실행 거부 | ops-feedback에 알림 |

잡의 종료 코드: 0 성공(게시, 이미 게시됨, 할 일 없음), 2 설정 오류, 3 경계 오류(재시도 불가), 75 경계 오류(재시도 가능).

## 7. 건드리지 않는 것

경계 계약과 문진 스키마를 수정하지 않는다. 문항 저장소와 실패 사례 저장소에 쓰지 않는다. 변경 요청 CR-001~005는 헤드가 결정했다(`docs/change-requests/`의 결정 절).
