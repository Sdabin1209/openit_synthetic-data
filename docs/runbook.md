# 런북: synthetic-data

## 한 줄 실행 (GPU 서버 포함, 잡은 CPU만 쓴다)

```bash
. .venv/bin/activate && python -m synthetic_data run --config <설정.json>
```
(환경이 없으면 먼저 `python3 -m venv .venv && . .venv/bin/activate && pip install -r requirements.lock`.)

## GPU 호스트에서 돌리기 (D49)

이 영역은 GPU 호스트에서 돌 가능성이 높고, I2 DatasetStore는 같은 호스트의 파일 저장소다(잡은 CPU만 쓴다). (1) 코드 전송: `rsync -a --exclude .venv --exclude work --exclude '.git' ./ <호스트>:<경로>/synthetic-data/` 후 호스트에서 `python3 -m venv .venv && . .venv/bin/activate && pip install -r requirements.lock`. (2) 설정의 `output.store`를 `{"kind":"file","root":"<데이터셋 루트>"}`로 두고 `output.work_dir`는 임시 경로로 둔다. 이웃 읽기는 `adapters.*.factory`를 `synthetic_data.adapters:http_question_reader`/`http_failure_store`, `kwargs`를 `{"base_url": "...", "token_env": "<토큰 환경 변수 이름>"}`로 하고 토큰은 실행 셸의 환경 변수로만 준다(파일과 리포지토리에 넣지 않는다). (3) 데이터셋은 `<데이터셋 루트>/<dataset_id>/<version>/{manifest.json, files/...}`에 생긴다. model-lab은 같은 호스트에서 `FileDatasetStore(<같은 루트>, Validators())`의 `get_manifest`/`open_file`로 같은 경로를 읽는다(읽기만 하면 문진 스키마 경로는 필요 없다). 게시는 임시 디렉터리 후 rename이라 읽는 쪽이 반쯤 쓴 버전을 보지 않는다.

## 게시기(import) 실행 (G02 방향)

```bash
python -m synthetic_data import --config configs/import.example.json [--created-at 2026-10-27T00:00:00Z]
```
- 입력 디렉터리(`input_dir`)에 `lora_{a,b}_{train,val,test}.jsonl` 6개를 둔다. 파일을 가져오는 일은 이 영역 밖이다(학습 서버에는 접속하지 않는다).
- 출력은 JSON 한 줄(`status`: PUBLISHED / ALREADY_PUBLISHED / REJECTED). 종료 코드 0, 2(설정·입력 파일 없음), 3·75(경계 오류), 4(허용치 초과 등으로 게시 안 함).
- 결과 확인: `<work_dir>/import_report.json`(`invalid_reasons_by_file`, `inputs`의 sha256·건수). 예시 설정의 문항 세트 해시는 자리 표시이므로 실제 값으로 바꿔야 한다.
- 설정 선택 항목: `tolerance.max_cross_split_duplicate_utterances`(기본 0), `tolerance.max_pii_suspect_rows`(생략 = 경고만), `pending_policy`(report/exclude/reject, 기본 report, 값은 사용자 결정). 보고서의 `deid_attested`는 항상 false(비식별 확인은 게시기가 하지 않음), `semantic_checks.performed`는 false.
- REJECTED면 보고서의 사유를 데이터셋 담당에게 넘긴다. 이 영역이 데이터를 고치지 않는다.
- 실제 데이터로 돌린 적 없음. 형식은 추정(docs/design.md 부록 A).

## 이웃 호출 오류가 보고서에 남는 방식

I1·I7 클라이언트는 읽기 모드다. 같은 MAJOR의 모르는 필드와 모르는 열거값은 받아들인다(시드의 모르는 필드·`expected_kind`는 `report.json`의 `notes`에 남고, 열거값은 expected 형태로 판별). 그 밖은 잡을 중단하고 `report.json`의 `error`(BoundaryError 레코드)를 남긴 뒤 종료 코드로 끝난다: MAJOR 불일치 `UNSUPPORTED_VERSION`(3), 형식·해시 위반 `INTEGRITY_ERROR`(3), 토큰 `PERMISSION_DENIED`(3), 서버 불가·타임아웃 `UNAVAILABLE`(75, 스케줄러가 재시도). 중단 시 아무것도 게시하지 않는다. 토큰 환경 변수 누락은 설정 오류(2).

## 준비

```bash
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements.lock pytest                 # 배포: boundary-contracts v2.0.2 태그 고정
pip install -e ../boundary-contracts                    # 개발: 작업 트리 사용(위 설치 뒤에 덮어쓴다)
```
(배포에서는 boundary-contracts를 Git 태그로 고정한다.)

## 시험

```bash
python -m pytest -q          # 적합성(파일·메모리 저장소), 잡 종단, 단위
```

## 잡 실행 (run-once)

```bash
PYTHONPATH=tests python -m synthetic_data run --config configs/dev.job.json [--created-at 2026-10-15T00:00:00Z]
```
- `configs/dev.job.json`은 이웃 영역 대역(`tests/doubles.py`)을 쓰는 개발용 설정이다. 운영 설정은 `adapters.*.factory`를 소유 영역의 읽기 SDK 공장으로 바꾼다.
- 설정 필드: `dataset_id`, `seed`(정수), `created_at`(생략하면 실행 시각), `version`(생략하면 `v<digest 12자>`), `turn_engine_version`(turn-engine이 없을 때 필수), `survey_schema_dir`(문진 스키마 `schema` 디렉터리; 경계 스키마는 boundary_contracts 패키지에서 읽는다), `adapters`, `question_sets[{id, version?, usage: TRAIN_POOL|HELD_OUT_EVAL}]`, `reviewed_only`, `scenarios{variants, noise_variants, noise_types, kinds}`, `seeds{enabled, question_set_id?}`(question_set_id는 1.0 사례 폴백용), `generators{utterance, response}`, `split.ratios`(필수, O11 사용자 결정 전까지 예시 값만), `review.per_kind`, `regeneration.mode`(full|affected_only), `output{work_dir, store{kind: file|memory, root}}`. 상대 경로는 설정 파일 위치 기준이다.
- 출력(표준 출력, JSON 한 줄): `status`(PUBLISHED, ALREADY_PUBLISHED, NOTHING_TO_DO), `version`, `content_hash`, `dataset_digest`, `counts`, `report_path`.
- 종료 코드: 0 성공, 2 설정 오류, 3 경계 오류(재시도 불가), 75 경계 오류(재시도 가능, 스케줄러가 다시 실행).

## 자동 실행 (D39)

새 문항 세트 버전이나 실패 사례가 생기면 같은 설정으로 위 명령을 부른다. 입력이 같으면 같은 digest -> `ALREADY_PUBLISHED`로 끝나 부작용이 없다. 문항 변경이 `REGENERATE_SAMPLES`를 낸 경우에는 `regeneration.mode=affected_only`와 해당 `question_sets[].version`을 지정한 설정으로 빠르게 새 데이터셋 버전을 만든다.

## 결과 확인

- `<work_dir>/report.json`: 계획·생성 건수, 품질 검사에서 버려진 사유와 건수(`dropped`), 건너뛴 시드(`skipped_seeds`), 결과.
- `<work_dir>/review_sample.jsonl`: 사람 감수용 표본.
- 저장소: `<store.root>/<dataset_id>/<version>/manifest.json`.

## 문제 대응

| 증상 | 확인 |
| --- | --- |
| `CONFLICT` | 같은 `version`을 고정했는데 입력·시드가 바뀌었다. `version`을 비우거나 올린다 |
| `UNSUPPORTED_VERSION` | `survey_schema_dir/CONTRACT_VERSION`이 읽는 문항 세트의 계약과 다르다 |
| `INVALID_RECORD`(비식별) | 실패 사례 저장소가 `deidentified=false`를 냈다. 실행이 거부된 것이 정상이다. ops-feedback에 알린다 |
| `FAILED_PRECONDITION` | 지정한 문항 세트 버전에 검수 승인이 없다(`reviewed_only`), 또는 turn-engine 버전을 알 수 없다 |
| `NOTHING_TO_DO` | `affected_only`인데 `REGENERATE_SAMPLES`가 없거나 품질 검사 뒤 샘플이 없다. `report.json`의 `notes`, `dropped` |
| `dropped` 비율이 큼 | `reasons` 코드는 `synthetic_data/quality.py`. 생성기 또는 문항 정의 문제 |
| 해시 불일치 | 저장된 파일이 바뀌었다. 새 버전으로 다시 게시 |

## 컨테이너

이 영역은 서비스가 없는 run-once 잡이라 Dockerfile 없이 `requirements.lock`으로 환경을 고정한다(헤드 승인, D22 (2)).

## 비밀은 NAME_FILE로 (D84)

이웃 호출 토큰은 환경 변수 값으로 넘기지 않는다(`docker exec env`·`inspect`에 평문이 보인다). 설정 어댑터의 `token_env`는 비밀 **이름**이고, `boundary_contracts.read_secret(NAME)`이 `NAME_FILE`(파일 경로, 컨테이너에서는 시크릿 마운트 `/run/secrets/...`)을 먼저 읽고, 없을 때만 `NAME` 환경 변수(개발용)를 쓴다.

```bash
QUESTION_READER_TOKEN_FILE=/run/secrets/question_reader_token   # 배포
QUESTION_READER_TOKEN=...                                       # 개발만
```
파일을 못 읽거나 비어 있거나 둘 다 없으면 설정 오류(종료 코드 2)이며, 메시지에는 이름과 경로만 있고 값은 없다.
