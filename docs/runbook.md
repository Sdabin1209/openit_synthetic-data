# 런북: synthetic-data

## 한 줄 실행 (GPU 서버 포함, 잡은 CPU만 쓴다)

```bash
. .venv/bin/activate && python -m synthetic_data run --config <설정.json>
```
(환경이 없으면 먼저 `python3 -m venv .venv && . .venv/bin/activate && pip install -r requirements.lock`.)

## 준비

```bash
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements.lock pytest                 # 배포: boundary-contracts v1.1.0 태그 고정
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
