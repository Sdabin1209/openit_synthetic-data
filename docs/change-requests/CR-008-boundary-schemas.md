# CR-008: 영역 경계를 넘는 형식 5종의 스키마 초안 (SD-01, SD-03, SD-04, SD-05)

상태: 초안, 헤드의 결정 대기 (2026-10-28, 작업 지시서 1 B). 코드는 이 스키마를 쓰도록 바꾸지 않았다. 근거: `docs/audit/structure-rules-2026-10-28.md` E절(R6).
헤드에게 요청: 아래 형식을 boundary-contracts에 올릴지(올린다면 이름과 위치) 결정한다. 올리면 이 영역은 `parse_config`·`parse_import_config`의 손코드 검증을 스키마 검증으로 바꾼다(다음 단계).

스키마 위치: `docs/change-requests/schemas/*.schema.json`(JSON Schema 2020-12), 예시 문서: `docs/change-requests/schemas/examples/`, 검증 스크립트: `docs/change-requests/schemas/validate_examples.py`.

## 검증 (jsonschema 4.10.3, Draft202012Validator, 이 리포의 `.venv`)

```
.venv/bin/python docs/change-requests/schemas/validate_examples.py
```
출력 끝줄: `합계 28건, 기대와 다름 0건` (유효 기대 13건 통과, 거부 기대 15건 거부; 각 줄은 스크립트가 낸다). 스키마 자체도 `check_schema`로 검사한다. 예시 문서는 실제 설정(`configs/dev.job.json`, `configs/import.example.json`)과 이 코드가 실제로 낸 출력(stdout, report.json, import_report.json, 시험 도우미가 만든 행)이다. 단 `kind: http` 어댑터 예시는 제안 형식이라 코드에 없다(검증 스크립트가 만든 값).

## 1. 잡 설정 `run` — `job-config-run.schema.json` (SD-01)
- 만드는 쪽/읽는 쪽: deploy 스케줄러(또는 개발자) / `synthetic_data/config.py` `parse_config`. 이 영역이 **받는** 형식.
- 예시: `examples/run-config.dev.json`.
- 모르는 키: **거부**. 이유: ADR 0014(조용히 무시된 설정은 효과가 있다고 믿게 한다). 현재 코드는 최상위만 거부하고 중첩 객체의 모르는 키는 무시한다; 초안은 중첩도 거부하는 제안이다(헤드가 받아들이면 코드를 맞춘다).
- 불변식: 같은 입력·시드는 같은 결과(멱등); 토큰 값은 설정에 넣지 않는다(`token_env`로 이름만, D84); 스키마로 못 쓴 규칙은 설명에 적었고 코드가 검사한다(같은 문항 세트를 TRAIN_POOL과 HELD_OUT_EVAL에 함께 쓰지 않음, `seeds.enabled`이면 `failure_store` 필요).

## 2. 잡 설정 `import` — `job-config-import.schema.json` (SD-01)
- 만드는 쪽/읽는 쪽: deploy 또는 개발자 / `importer.py` `parse_import_config`. **받는** 형식.
- 예시: `examples/import-config.example.json`(`content_hash`가 0으로 채워진 자리 표시이며 형식은 유효).
- 모르는 키: **거부**(ADR 0014). 이번 작업에서 최상위는 코드에 반영했다(커밋 2075fe2). 중첩은 제안.
- 불변식: `tolerance` 기본은 가장 엄격(ADR 0005); `origin`은 SYNTHETIC만; `pending_policy` 기본은 보고만(사용자 결정 전까지 정책 아님).

## 3. 외부 학습 데이터 jsonl 행 — `training-data-row.schema.json` (SD-03)
- 만드는 쪽/읽는 쪽: 데이터셋 담당(영역 밖) / `import`. **받는** 형식. 파일 이름 6개 `lora_{a,b}_{train,val,test}.jsonl`이 역할과 분할을 정한다(ADR 0002; 이름은 V2_DRAFT 기록의 추정이라는 `importer.py`의 주석이 그대로 남아 있다: 확인되지 않음).
- 예시: `examples/row-lora-a.json`, `row-lora-b.json`. 이 행은 시험 도우미(`tests/test_import.py`의 `row()`)가 만든 것이며 실제 C1 파일의 행이 아니다(실제 파일 형식은 docs/design.md 부록 B가 기록한 관측에 기댄다).
- 모르는 키: **무시**(읽기 모드). 이유: 데이터셋 담당이 필드를 더해도 게시기가 깨지지 않아야 하고, 필요한 필드는 `messages`와 `scenario_id`로 이미 고정이다. 행의 `split` 값은 읽지 않는다(파일 이름이 정본).
- 불변식(스키마로 못 쓰는 것은 설명에 적고 코드가 검사): messages는 정확히 `[system, user, assistant]` 3개; user content는 LORA_A면 `ActionExtractionInput`, LORA_B면 `ResponseRequest` JSON; 같은 `scenario_id`는 분할에 걸치지 않음; 행 값은 보고서에 남기지 않는다.

## 4. 잡 결과: stdout JSON, 종료 코드, `import_report.json`/`report.json` (SD-04)
- 만드는 쪽/읽는 쪽: 이 영역의 잡 / deploy 스케줄러. **내는** 형식. deploy 쪽이 실제로 어떤 필드를 읽는지는 읽지 못했다(미확인).
- 스키마: `job-result.schema.json`(stdout 한 줄), `job-error.schema.json`(종료 코드 2의 stderr), `import-report.schema.json`, `run-report.schema.json`. 종료 코드 표는 `job-result.schema.json` 설명에 있다: 0 성공(게시, 이미 게시됨, 할 일 없음), 2 설정 오류, 3 재시도 불가 경계 오류, 75 재시도 가능 경계 오류, 4 import가 게시하지 않음. 3·75의 stderr는 계약에 이미 있는 `BoundaryError`.
- 예시: `stdout-run-published.json`(실제로는 재실행이라 `ALREADY_PUBLISHED`), `stdout-run-nothing-to-do.json`, `stdout-import-published.json`, `stdout-import-rejected.json`(종료 코드 4), `stderr-config-error.json`(종료 코드 2), `import-report.published.json`, `import-report.rejected.json`, `run-report.json`. 모두 이번에 실제로 돌려 얻었다.
- 모르는 키: **읽는 쪽은 무시**. 이유: 이 영역이 보고 필드를 더해도 deploy가 깨지지 않게. 설정과 달리 이 영역이 만드는 값이라 거부할 대상이 아니다.
- 불변식: `deid_attested`는 항상 false(ADR 0007), `semantic_checks.performed`는 항상 false(ADR 0009); 게시/이미 게시 상태에는 `version`·`content_hash`·`dataset_digest`가 있다; 보고서에 입력 행의 값은 없다(건수와 사유 코드, ADR 0003); `report_path`는 실행 호스트 기준 경로.

## 5. 어댑터 지정 `adapters.*.factory` 대안 — `job-config-run.schema.json`의 `Adapter` (SD-05)
- 지금 형식은 파이썬 `module:function` 문자열과 `kwargs`라서 설정을 쓰는 쪽이 이 영역의 내부 모듈 경로를 알아야 한다(R1). 초안은 `oneOf`로 두 형식을 함께 정의한다: 현재의 `factory`, 제안하는 `{kind: "http", base_url, token_env, timeout}`(저장소 `output.store.kind`와 같은 방식, `store/spec.py`). 시험용 대역은 시험 코드에서만 주입한다.
- 만드는 쪽/읽는 쪽: 1번 형식의 일부. **받는** 형식.
- 모르는 키/불변식: 두 형식 중 정확히 하나(둘을 함께 쓰면 거부, 검증에서 확인); 토큰 값 대신 `token_env`만.
- 이 대안은 제안일 뿐이며 코드에 없다. 받아들일지는 헤드가 정한다.

## 하지 않은 것
- 코드가 이 스키마로 설정을 검증하도록 바꾸지 않았다(지시: 헤드가 계약에 올린 뒤).
- `$ref`는 초안 안의 `_defs.schema.json`을 쓴다. `ArtifactRef`는 boundary-contracts의 `_common.schema.json`과 같은 모양을 옮겨 적은 것이며, 계약에 올릴 때 그쪽을 `$ref`한다. 옮겨 적은 모양이 계약과 정확히 같은지는 이번에 `_common.schema.json`을 읽어 눈으로만 대조했고(id, version, content_hash, 추가 키 없음) 기계로 대조하지 않았다.
- SD-06·SD-07·SD-09는 이 CR의 범위 밖이다.
