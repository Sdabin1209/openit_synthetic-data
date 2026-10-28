# 구조 규칙 R1~R7 전수 점검 보고서: synthetic-data (2026-10-28)

기준서: `head/docs/audit/structure-rules-audit-spec.md`(헤드가 이번 점검에 한해 읽기를 허락). 점검은 읽기 전용이며 코드·설정·시험을 고치지 않았다. 점검 대상 커밋: `99613e6`(작업 트리 변경 없음). 계약 대조 기준: `../boundary-contracts`(`v2.1.1-1-gf984b3c`, HTTP.md, INTERFACES.md, CONVENTIONS.md, schemas/).

요약: P1 2건, P2 12건, P3 8건(합계 22건). 이 영역의 시험은 이 점검에서 다시 돌렸다: `.venv/bin/python -m pytest -q -rs` -> 164 통과, 1 건너뜀(`SD_REFERENCE_DATA_DIR` 없음), 0 실패. 시험 개수의 정본은 README 5절이며 여기서는 재현했다는 사실만 적는다.

## 0. 확인 범위

읽은 것(전부 끝까지): `CLAUDE.md`, `docs/brief.md`, `README.md`, `docs/boundary.md`, `docs/runbook.md`, `docs/STATUS.md`, `docs/adr/README.md`, ADR 0010·0013·0014(전문), `docs/design.md` 1~10절(부록 A·B는 읽지 않음), CR-006, `synthetic_data/` 전 파일(`__init__`, `__main__`, `adapters`, `config`, `context`, `importer`, `job`, `package`, `quality`, `rng`, `schemas`, `seed_samples`, `seeds`, `split`, `store/*`, `service/app.py`, `service/tarutil.py`), `configs/*.json`, `Dockerfile`, `scripts/*`, `requirements*.txt|lock`, `pyproject.toml`. 계약 쪽: `HTTP.md` 전체, `INTERFACES.md` I1·I2·I7·I8, `CONVENTIONS.md` 9·10절과 상태 확인 절, `boundary_contracts/clients/{datasets,questions,ops,_http}.py`, `schemas/` 목록, `FailureCase.schema.json` 일부.

검색한 패턴: `../`, `model-lab|deploy|question-authoring|ops-feedback|survey-service`(코드·설정·스크립트), `turn_engine|turn-engine`, `environ|os.environ`, `_list_versions|_vdir|_check_path`, `startswith("as-")`, `_ID_RE`, `get_trace|get_change|get_reviews|latest(`.

## A. 컴포넌트 목록

이 영역에는 컴포넌트 경계를 코드로 드러낸 선언(Protocol, 컴포넌트 표, I/O 스키마 표)이 없다. 아래는 코드를 읽고 내가 나눈 작업 단위이며 영역의 문서가 정한 목록이 아니다(브리프 8절의 이름과 대응만 맞췄다).

| # | 컴포넌트(작업 단위) | 파일 | 입력 | 출력 | 업무 한 줄 |
|---|---|---|---|---|---|
| 1 | 시드 잡 `run` (조율) | `job.py` | `JobConfig`, I1 `QuestionReader`, I7 `FailureStore`, `DatasetStore` | `JobResult`, `report.json`, `review_sample.jsonl`, 게시된 데이터셋 | 읽기에서 게시까지 한 번 돈다 |
| 2 | 시드 수집기 | `seeds.py` | I7 `FailureStore`(`FailureCase`) | `Seed` 데이터클래스(`seeds.py` 12행대) 목록, 건너뛴 사유 | CONFIRMED 사례를 시드로 고른다 |
| 3 | 시드 샘플 조립기 | `seed_samples.py` | `(Seed, QuestionSetContext)` 쌍 | 샘플 dict(`ActionExtractionSample`/`ResponseSample` 모양) | 시드를 샘플 레코드로 만든다 |
| 4 | 품질 검사기 | `quality.py` | 샘플 dict, `Validators` | 사유 코드 목록 | 샘플이 경계 스키마를 통과하는지 본다 |
| 5 | 중복 제거 | `job.py:152-168` (함수 아님) | 통과한 샘플 | 최종 샘플 | 같은 입력 중복을 정리한다 |
| 6 | 분할기 | `split.py`, 호출은 `job.py:174-175` | `scenario_id`, usage, ratios, seed | `TRAIN|VALIDATION|EVAL` | 시나리오 단위로 나눈다 |
| 7 | 감수 샘플링 | `job.py:223-236` | 최종 샘플 | `review_sample.jsonl` | 사람 감수용 표본 |
| 8 | 패키저 | `package.py` | 샘플 목록, `QuestionSetContext`, `JobConfig` | JSONL 파일, `DatasetManifest` dict, digest | 파일과 매니페스트를 만든다 |
| 9 | 데이터 게시기 `import` | `importer.py`(`run_import`) | `ImportConfig`, jsonl 6개(messages 형식) | `ImportResult`, `import_report.json`, 게시된 데이터셋 | 외부 학습 데이터를 검증해 게시한다 |
| 10 | 행 검증 | `importer.py:189-236` `validate_row` | 원시 바이트 한 행, 역할, 분할 | 샘플 dict 또는 사유 코드 | 한 행을 3단계로 검증한다 |
| 11 | 평가 누수 검사 | `importer.py:358-387` (`_run_import` 안, 함수 아님) | 통과한 행들 | 분할 사이 중복 입력·`scenario_id` 겹침 건수 | 평가가 학습과 겹치는지 본다 |
| 12 | 개인정보 의심 패턴 | `importer.py:83-86` `pii_kinds` | 샘플 dict | 패턴 종류 목록 | 경고용 집계 |
| 13 | I2 저장소 공통 | `store/base.py` `DatasetStoreBase` | `DatasetManifest`, `{path: Path}` | 매니페스트, `BinaryIO`, 버전 목록 | 게시 검증·멱등·무결성 |
| 14 | I2 저장소 구현 | `store/file_store.py`, `store/memory_store.py` | 같음 | 같음 | 파일/메모리 저장 |
| 15 | I2 저장소 선택·HTTP 클라이언트 만들기 | `store/spec.py` | `output.store` 설정 dict | 정규화 dict, `HttpDatasetStore` | file/memory/http 중 고른다 |
| 16 | I2 서버 dataset-store | `service/app.py`, `service/tarutil.py`, `service/__main__.py` | HTTP 요청, 환경 변수/비밀 파일 | HTTP 응답(`HTTP.md ## I2`) | 저장소를 HTTP로 서비스한다 |
| 17 | 이웃 클라이언트 공장 | `adapters.py` | `base_url`, `token_env`, `timeout` | `HttpQuestionReader`, `HttpFailureStore` | I1·I7 클라이언트를 만든다 |

접착 코드(어느 컴포넌트에도 속하지 않음): `__main__.py`(CLI, 종료 코드), `config.py`(`run` 설정 파싱, `JobConfig`), `context.py`(`QuestionSetContext`), `schemas.py`(`Validators`: 경계 스키마와 문진 스키마 검증), `rng.py`(해시 파생), `__init__.py`(버전, `SUPPORTED_PIPELINE_MAJOR`), `scripts/*`, `Dockerfile`.

컴포넌트 경계가 없는 덩어리: `job.py::_run_job`(약 120행에 1·2·5·6·7이 한 함수), `importer.py::_run_import`(약 175행에 9·10의 집계·11·12·패키징·게시가 한 함수). 5·7·11은 함수조차 아니라 위 함수 안의 구간이다.

## B~G 발견

### P1

**SD-01 | R6 (E) | P1 | 잡 설정(`run`/`import`)은 영역 경계를 넘는 형식인데 계약 스키마가 없다**
- 위치: `synthetic_data/config.py:75-76`(`KNOWN_KEYS`), `config.py:79-82`, `importer.py:114-163`(`parse_import_config`), `configs/dev.job.json`, `configs/import.example.json`.
- 인용: `KNOWN_KEYS = frozenset({"_comment", "dataset_id", "seed", ... "regeneration", "output"})` / ADR 0014: "deploy가 `e2e_steps.py`에서 `generators` 전송을 지운다."
- 왜 위반인가: 설정 파일은 deploy 스케줄러가 만들어 넘기는 값이다(ADR 0010·0014가 `regeneration.mode`, `review.per_kind`, `generators`를 deploy가 써넣는다고 기록). 영역을 넘는 스키마인데 boundary-contracts에는 없다(`schemas/` 32개에 잡 설정 없음, 확인). 영역 안 데이터클래스(`JobConfig`, `ImportConfig`)와 손으로 쓴 `_req` 검증이 사실상의 계약이 되었고, 이미 한 번 깨진 전례가 있다(ADR 0014 맥락). 허용 키 목록을 코드의 집합으로만 두어 기계가 읽는 스키마가 아니다. 추가로 `import` 설정에는 알 수 없는 키 거부가 아예 없다(`importer.py:114-163`에 `KNOWN_KEYS` 같은 검사 없음; 오타 키는 조용히 무시됨), 즉 ADR 0014가 `run`에만 적용되었다.
- 최소 수정 방향: 헤드가 R6로 잡 설정 스키마(JSON Schema, `run`·`import` 두 형식)를 boundary-contracts에 둘지 정하게 변경 요청을 낸다. 그 전까지 영역 안에서는 JSON Schema 한 파일로 정의하고 `import`에도 같은 방식의 알 수 없는 키 거부를 적용(영역 안 R5 조치).

**SD-02 | R1 | P1 | 스모크 스크립트가 이웃 영역 폴더 `../model-lab/vendor/wheels`를 기본 경로로 쓴다**
- 위치: `scripts/smoke_service.sh:3`, `:8`.
- 인용: `WHEELS=${SMOKE_WHEELS:-../model-lab/vendor/wheels}` / 머리말 `기본 ../model-lab/vendor/wheels`
- 왜 위반인가: 워크스페이스 규칙이 허용한 읽기 전용 참조는 `../survey-service/schema`, `../boundary-contracts`, `../head/shared/areas.json`뿐이다. model-lab의 vendor 폴더(그 영역이 보관하는 wheel)는 이웃 구조에 기댄 것이며, 이 스크립트가 D22의 "변경 완료 전 이미지 스모크"를 하는 유일한 길이라 model-lab 폴더가 없으면 스모크가 `ls`에서 실패한다(실제 결합). 폴더 안에 `boundary_contracts-<버전>-*.whl`이 있다는 가정도 model-lab의 내부 배치다. README 5절이 "새 clone에서는 돌리지 않았다"고 한 이유와 맞닿는다.
- 최소 수정 방향: wheel을 `../boundary-contracts`에서 빌드하거나(허용 경로), 태그 설치(`BC_SPEC`가 `git+ssh` 태그, Dockerfile가 이미 지원)로 빌드하고 기본값에서 model-lab 경로를 뺀다. 스크립트가 `.venv/bin/python`을 가정하는 점도 같이 `setup-env.sh` 문서와 맞춘다.

### P2

**SD-03 | R6 (E) | P2 | 외부 학습 데이터 파일 형식(`lora_{a,b}_{train,val,test}.jsonl`, messages 3개 + `scenario_id`/`split`/`human_review`)이 계약에 없다**
- 위치: `importer.py:3-6`, `:34-36`(`SPLIT_OF_FILE`, `INPUT_FILES`), `:201-205`.
- 인용: `["system","user","assistant"]` 각각 문자열 content / `INPUT_FILES = [(f"lora_{r}_{s}.jsonl", role, split) ...]`
- 왜: 데이터셋 담당(영역 밖)과 이 영역 사이를 오가는 파일 형식인데 boundary-contracts 스키마가 없다. 형식은 "C1 실제 파일 6개로 확인"(importer 독스트링)이라는 관측에 기댄다. 파일 이름은 V2_DRAFT 기록의 추정이었다고 `importer.py:33` 주석이 쓴다. 다른 빌드에서 어긋나면 invalid로만 보인다.
- 수정 방향: 헤드에게 R6 대상 여부를 변경 요청(CR-006 3~4항이 일부 다룸). 정해질 때까지 영역 안에서 이 형식을 JSON Schema 한 파일로 둔다.

**SD-04 | R6 (E) | P2 | 잡의 표준 출력 한 줄, 종료 코드, `report.json`·`import_report.json`이 deploy와의 비공식 계약이다**
- 위치: `__main__.py:1-3`, `:32-33`, `job.py:217-220`, `importer.py:461-464`.
- 인용: `종료 코드: 0 성공 ..., 2 설정 오류, 3 ..., 75 ..., 4 import 모드에서 ...`
- 왜: 스케줄러(deploy)가 종료 코드 75를 재시도 신호로 읽고(boundary.md 6절) 표준 출력 JSON을 읽을 수 있다. 형식의 정본은 이 영역의 독스트링·README뿐이다. 무엇을 deploy가 읽는지는 읽지 못했다(점검 범위 밖).
- 수정 방향: 헤드가 deploy와 맞춰 "잡 실행 결과" 계약(필드, 종료 코드)을 정할지 판단. 영역 안에서는 `JobResult`/`ImportResult` JSON Schema 한 곳.

**SD-05 | R1·R6 | P2 | 설정이 파이썬 `module:function` 문자열과 팩토리 kwargs 이름을 이웃(deploy)에 노출한다**
- 위치: `job.py:44-46`, `adapters.py:1-6`, `:25-30`, `config.py:67-71`.
- 인용: `return getattr(importlib.import_module(mod), fn)` / 예 `"factory": "synthetic_data.adapters:http_question_reader", "kwargs": {"base_url": ..., "token_env": ..., "timeout": 10}`
- 왜: deploy는 `synthetic_data.adapters:http_question_reader`라는 내부 모듈 경로와 `kwargs` 키를 알아야 설정을 쓸 수 있다(ADR 0010이 "공개 진입점은 그대로"라고 인정). 설정이 임의의 모듈을 import 하는 면이기도 하다(신뢰하는 설정이라는 전제는 문서화되지 않음). 이웃이 이 영역의 내부 구조(모듈명)에 기댄다는 뜻이라 R1에 가깝다.
- 수정 방향: 설정에 `factory` 대신 `kind: http` + `base_url`, `token_env`, `timeout`을 두고(저장소 `output.store.kind`와 같은 방식, `store/spec.py`), 시험용 대역은 시험에서만 주입.

**SD-06 | R1·R7 | P2 | turn-engine 버전을 두 경로로 얻고(`import turn_engine` 시도 vs 설정 문자열), 자리표시자가 계약 필드에 들어간다**
- 위치: `job.py:49-58`, `importer.py:159`(설정에서만), `configs/dev.job.json:6`, `configs/import.example.json:8`, `requirements.lock`(turn-engine 없음).
- 인용: `import turn_engine  # type: ignore` / `"turn_engine_version": "0.0.0-unpinned"`
- 왜: workspace 규칙상 turn-engine 의존은 허용이지만 이 영역은 이를 의존으로 선언하지 않았다(`requirements.lock`·`pyproject.toml`에 없음). `run`은 환경에 따라 설치돼 있으면 `ENGINE_VERSION`, 아니면 설정 값을 매니페스트 `turn_engine_version`(필수 필드)에 기록한다. 같은 설정이 환경에 따라 다른 `dataset_digest`를 낼 수 있다(digest에 `turn_engine_version` 포함, `package.py:60`). `import`는 항상 설정 값이라 두 모드가 다르다. 예시 설정의 `0.0.0-unpinned`는 실제 버전이 아닌 값이 계약 필드에 게시되는 길이다. 한편 호출은 하지 않으므로 코드 결합은 선택적 import 한 줄이다(CR-002, brief 3절).
- 수정 방향: 헤드가 매니페스트 `turn_engine_version`의 출처(설정이 정본인지, turn-engine 설치가 정본인지)를 정하고 두 모드를 같게 한다. 그때까지 `import turn_engine`의 조용한 분기를 없애거나 문서화한다.

**SD-07 | R1 | P2 | 문진 스키마를 이웃 폴더 경로로 받는다(설정, Dockerfile 빌드 컨텍스트)**
- 위치: `configs/dev.job.json:7`, `configs/import.example.json:5`, `Dockerfile:3-4`, `:28-29`, `scripts/smoke_service.sh:4`, `:9`.
- 인용: `"survey_schema_dir": "../../survey-service/schema"` / `--build-context survey_schema=../survey-service/schema`
- 왜: `../survey-service/schema` 읽기는 워크스페이스 규칙이 허용한다. 그러나 (a) 시험은 이미 설치된 패키지에서 읽는다(`tests/conftest.py:16-17` `survey_schema.contract_version_dir(1)`, `requirements.lock`의 `openit-survey-schema`), 운영용 설정·이미지는 형제 폴더를 읽어 두 갈래다. (b) 서버 이미지의 `/app/survey_schema`는 그 시점의 형제 폴더 내용이라 `requirements.lock`의 문진 스키마 태그(`survey-schema-v1.0.0`)와 어긋날 수 있다(빌드 인자 `SURVEY_SCHEMA_VERSION`은 `CONTRACT_VERSION` 파일 하나만 확인). (c) README 3절은 "이웃 폴더는 시험에 필요 없다"고 하지만 예시 설정과 스모크는 필요하다.
- 수정 방향: 설치된 문진 스키마 패키지에서 경로를 얻는 방식(`survey_schema.contract_version_dir`)을 설정 기본과 Dockerfile에 쓰고 형제 폴더 경로를 설정에서 뺀다.

**SD-08 | R5 | P2 | 샘플의 역할(LORA_A/LORA_B)을 `sample_id` 접두어 문자열("as-"/"rs-")에서 되읽는다**
- 위치: `job.py:146`, `:154`(`s["sample_id"][:2]`), `:210`, `:227`, `package.py:34`, `seed_samples.py:33,41`, `importer.py:41`(`_ID_PREFIX`).
- 인용: `role = "LORA_A" if s["sample_id"].startswith("as-") else "LORA_B"`
- 왜: 컴포넌트 3(조립기)이 만든 샘플 dict에는 `role` 필드가 없고(`ActionExtractionSample`/`ResponseSample` 스키마가 역할을 `sample_id`로만 구분), 5·7·8이 ID 문자열 관습으로 역할을 추론한다. 컴포넌트 사이 스키마가 암묵적이다. ID 형식이 바뀌면 조용히 `LORA_B`로 분류된다(`else` 분기).
- 수정 방향: 샘플과 함께 `(role, record)`를 타입 있는 구조로 넘긴다.

**SD-09 | R2·R3 | P2 | `run`과 `import`는 컴포넌트 경계가 없는 두 덩어리다**
- 위치: `job.py:86-204`(`_run_job`), `importer.py:272-449`(`_run_import`).
- 인용: `_run_job`이 문항 읽기, 시드 수집 호출, 시드-문항 짝짓기(`:121-136`), 품질 검사, 중복 제거(`:152-168`), 분할, 감수 샘플링, 패키징, 게시, 멱등 판정을 순서대로 한 함수에서 한다. `_run_import`는 행 순회·집계(`:283-312`), 보고서 필드 작성(`:313-331`), 허용치 판정(`:332-357`), 누수 검사(`:358-387`), 패키징(`:397-435`), 게시(`:436-445`)를 한 함수에서 한다.
- 왜: 평가 누수 검사(#11), 중복 제거(#5), 감수 샘플링(#7) 같은 업무가 입력·출력 스키마 없이 구간으로만 존재해 R2(컴포넌트가 작업 단위)에 못 미친다. 구간 사이는 지역 변수(`keys`, `skeys`, `valid`, `report` dict)로 직접 엮인다(R3). `report` dict는 모든 구간이 쓰는 공유 가변 상태다.
- 수정 방향: 최소한 #5, #7, #11을 입력·출력이 정해진 함수/모듈로 뽑는다.

**SD-10 | R4·R7 | P2 | 패키저가 `JobConfig`를 받고, 게시기는 같은 패키징을 다시 구현한다**
- 위치: `package.py:28-29`(`cfg: JobConfig`, `cfg.dataset_id`, `cfg.version`), `package.py:57-69` vs `importer.py:397-435`.
- 인용: `manifest = {"pipeline_schema_version": PIPELINE_SCHEMA_VERSION, "dataset_id": cfg.dataset_id, "version": cfg.version or ("v" + digest[7:19]) ...` / importer: `"version": cfg.version or ("v" + digest[7:19])`
- 왜: 패키저가 시드 잡의 설정 전체를 아는 것은 R4(자기 I/O 밖의 정보). 게시기가 `package()`를 못 쓰는 이유가 `JobConfig` 결합이고, 결과로 digest 계산·매니페스트 조립·파일 쓰기가 두 번 구현된다(importer 주석 `package.py와 같은 규칙`). 한쪽만 고치면 어긋난다.
- 수정 방향: `package()`가 `dataset_id`, `version`만 받게 하고 두 모드가 공유(필드 `ext`만 다름).

**SD-11 | R3 | P2 | I2 서버(`service/app.py`)가 저장소 구현의 비공개 멤버를 직접 쓴다**
- 위치: `service/app.py:175`, `:185`, `:367`.
- 인용: `self.store._list_versions(i)` / `self.store._vdir(did, ver) / "files" / path` / `svc.store._check_path(fp)`
- 왜: 서버(#16)가 저장소 구현(#14)의 파일 배치(`<root>/<id>/<ver>/files/<path>`)와 내부 메서드에 기댄다. `Service`는 `FileDatasetStore`에 고정(`app.py:83`)이라 메모리 구현으로 바꿀 수 없다.
- 수정 방향: 공개 메서드(`list_ids`, `file_path`)를 저장소에 추가하거나 서버가 `open_file`만 쓰게 한다.

**SD-12 | R5 | P2 | 컴포넌트 3→4→5→6→8 사이를 오가는 샘플이 형태 없는 dict이고 중간에 제자리 변경된다**
- 위치: `seed_samples.py:14-20`(`_record`), `job.py:175`(`s["split"] = assign_split(...)`), `job.py:213`, `:227`(`s["ext"]["synthetic-data"]["kind"]`).
- 인용: `s["split"] = assign_split(s["scenario_id"], usage[...], cfg.ratios, cfg.seed)`
- 왜: 샘플 정의는 경계 스키마(boundary-contracts)에 한 곳 있지만, 영역 안 흐름에서는 키 관습에 의존한다. 조립기가 `split: "TRAIN"`을 임시로 넣고 분할 단계가 덮어쓴다. 스키마 검증(품질 검사)이 분할 전에 일어나 최종 형태(분할 반영)는 게시 단계에서야 처음 검증된다. 영역 안의 "정의 위치"는 `schemas.py`(검증)이고 타입 정의는 없다. 타입 있는 데이터클래스는 `Seed`, `QuestionSetContext`, `JobConfig` 등에만 있다.
- 수정 방향: 샘플용 `TypedDict`/데이터클래스와 분할 반영 복사본.

**SD-13 | R7 (G) | P2 | 시드 수집기가 이웃(I7)이 보증한 값을 다시 검증한다**
- 위치: `seeds.py:30`(서버 필터 `review_status="CONFIRMED"`), `:56`, `:44`, `:72-75`.
- 인용: `if case["review_status"] != "CONFIRMED": return None, "CONFIRMED 아님"` / `v.check_boundary("ActionExtraction", exp) or v.check_boundary("ActionExtractionInput", inp)`
- 왜: `list_cases(review_status="CONFIRMED")`로 이미 거른 뒤 다시 거른다(`:56`). `expected`/`reviewed_input`의 스키마 일치는 HTTP.md I7(검토 게시 행)에서 서버가 보증한다("`expected`가 있으면 `expected_kind`가 필수이고 ... 아니면 INVALID_RECORD") 그런데 시드 수집기가 같은 규칙을 다시 구현한다. `deidentified` 확인(`:44`)은 brief 5절("비식별 전 데이터를 받으면 거부")이 이 영역에 요구한 정책이라 R7과 충돌한다.
- 수정 방향: 헤드가 R7 적용 범위를 정한다. 브리프의 비식별 거부를 유지하면 그것만 남기고 `:56`, `:72-75`는 제거 후보. 이웃이 보증하지 않는다고 판단되면 그 주장을 I7 계약에 적는 쪽이 R7에 맞다.

**SD-14 | R7 (G) | P2 | 같은 샘플 스키마를 한 게시 경로에서 4~5번 검증한다**
- 위치: `quality.py:14-19`(`ActionExtractionSample`/`ResponseSample`), `importer.py:233`, `store/base.py:172`(publish 줄 단위), `boundary_contracts/clients/datasets.py:94-96`(`check_outgoing`, `check_publish`; 계약이 요구), 서버 `service/app.py:436`(→`base.py:172`).
- 인용: `return ["schema_sample"] if v.check_boundary(name, rec) else []` / `v.boundary(_SAMPLE_SCHEMA[role], rec, what=where)`
- 왜: HTTP.md I2는 "클라이언트도 보내기 전에 같은 것을 확인한다"고 정해서 클라이언트+서버 이중은 계약이 정한 것이다. 그 위에 이 영역 내부의 품질 검사기(#4)와 `validate_row`의 `sample_schema` 단계(#10), 그리고 `store.publish`(file/memory)가 같은 스키마를 또 검증한다. 시드 경로(`run`)에서는 시드 수집기(SD-13)까지 합치면 같은 input/expected가 최대 5번 검증된다. `quality.py`의 `check_*_sample(rec, bank, v)`의 `bank` 인자는 쓰이지 않는다. `import`의 행 단위 검증은 허용치(`tolerance`) 계산이라는 별도 목적이 있어 완전한 중복은 아니나, `sample_schema` 단계(`:233`)는 `input_schema`+`output_schema`+봉투의 조합 재확인이다.
- 수정 방향: 헤드가 "게시 전 사전 검증은 클라이언트(계약)에 맡긴다"로 정하면 `quality.py`는 제거 후보. `import`는 행 단위 검증 단계 중 `sample_schema`만 남기는 쪽이 최소.

### P3

**SD-15 | R3 | P3 | `importer.py`가 `config.py`의 비공개 이름과 패키저·저장소 기반 클래스를 직접 가져오고, ID 정규식이 세 곳이다**
- 위치: `importer.py:26-31`, `config.py:15`, `store/base.py:27`, `importer.py:125`.
- 인용: `from .config import ConfigError, _ID_RE` / `from .store.base import DatasetStoreBase`
- 왜: 게시기가 시드 잡 설정 모듈의 `_` 비공개 상수에 기댄다. 같은 Id 규칙(CONVENTIONS 10절)이 `config.py`와 `store/base.py`에 따로 있다.
- 수정 방향: 공개 상수 한 곳(`ids.py`).

**SD-16 | R7 (G) | P3 | 게시기의 `scenario_id` 겹침 검사가 저장소 `publish`의 검사와 같은 규칙이다**
- 위치: `importer.py:380-387` vs `store/base.py:148-151`.
- 인용: `rejected.append(f"같은 scenario_id가 {a}와 {b}에 걸친다({len(both)}건)")` / `raise _inv(f"같은 scenario_id가 {a}와 {b}에 걸친다", ...)`
- 왜: 같은 규칙을 이웃 구성요소가 이미 보증한다. 게시기 쪽은 `REJECTED`(종료 코드 4)로 정상 종료시키려는 의도가 있다(저장소는 예외). 다만 같은 문구의 규칙 두 벌이다.
- 수정 방향: 게시기는 `INVALID_RECORD`를 받아 `REJECTED`로 변환하면 사전 검사를 뺄 수 있다.

**SD-17 | R7 (G) | P3 | 문항 은행 해시를 클라이언트가 이미 확인했는데 다시 확인한다**
- 위치: `job.py:99-100` vs `boundary_contracts/clients/questions.py:18`(`verify_json_hash(bank, ref["content_hash"], "QuestionBank")`).
- 인용: `if canonical.sha256_hash(bank) != ref["content_hash"]: raise BoundaryError("INTEGRITY_ERROR", ...)`
- 왜: HTTP.md 공통은 "해시는 클라이언트가 받은 뒤 다시 계산해 INTEGRITY_ERROR로 판정한다"고 한다. 그러나 `job.py`는 Protocol(`QuestionReader`)만 알고 인메모리 대역이면 확인이 사라지므로 의도적 방어일 수 있다. 근거 기록(ADR) 없음.
- 수정 방향: 유지한다면 한 줄 '왜' 주석.

**SD-18 | 계약 F (CONVENTIONS 상태 확인 절) | P3 | `/readyz` 503 본문에 사유가 없고 2초 상한이 코드에 없다**
- 위치: `service/app.py:145-153`, `:330-332`.
- 인용: `return self._json(200 if ok else 503, {"status": "ready" if ok else "not-ready"})`
- 왜: CONVENTIONS "상태 확인 응답 시간(2.1.0)": `/readyz`는 의존이 응답하지 않을 때도 총 2초 안에 "503과 사유"를 답한다. 구현은 디스크 쓰기 확인(`ready()`)에 마감이 없고 본문에 사유가 없다. 볼륨 장애 시 응답이 2초를 넘는지는 측정하지 않았다.
- 수정 방향: 사유 코드(`volume_unwritable` 등, 접속 정보 없이)와 스레드 마감.

**SD-19 | 문서(워크스페이스 규칙: 한 사실은 한 곳) | P3 | 문서가 현재 코드와 어긋난다**
- 위치와 인용:
  - `README.md:5` "웹 서비스 운영(서비스가 아니라 `/healthz`도 없음)"과 `README.md:49` "Dockerfile 없이 `requirements.lock`으로 고정" vs 실제 `Dockerfile`, `service/app.py:328-332`(`/healthz`, `/readyz`가 있음).
  - `docs/runbook.md` 설정 필드 절 "옛 키 ... 받되 무시하고 report.json notes에 남긴다" vs `config.py:80-82`(거부, ADR 0014). `docs/runbook.md` "컨테이너" 절 "Dockerfile 없이" vs `Dockerfile`.
  - `README.md:87` "ADR 0001~0010", `docs/adr/README.md`는 0014까지. `README.md:88`, `docs/boundary.md` 7절 "CR-001~005" vs `docs/change-requests/`는 CR-007까지.
  - `README.md:25-27` "HTTP 경로는 ... 이번에 읽지 않았습니다(미확인)" vs 이 보고서 F절의 I1·I2·I7 대조.
  - `docs/boundary.md` 4절 I7 행 "`get_trace`" vs 코드는 `get_trace`를 부르지 않는다(`grep get_trace synthetic_data` 결과 없음, `seeds.py:61` 주석이 trace 미사용을 쓴다).
  - `docs/STATUS.md:3` "boundary-contracts v2.0.2" vs `requirements.lock` v2.1.1. `pyproject.toml:7` 0.2.0 vs `docs/CHANGELOG.md` 0.2.2(STATUS가 이미 어긋남을 고지).
  - `synthetic_data/__init__.py:1`, `pyproject.toml:9` 설명이 "합성 데이터 생성 잡"(ADR 0001·0010로 생성 안 함).
- 수정 방향: 위 항목 갱신. (이번 점검에서 문서는 고치지 않았다.)

**SD-20 | R1 (워크스페이스: 이웃 메모리 구현으로 혼자 시험) | P3 | 이웃 대역을 영역 안에서 손으로 쓴다**
- 위치: `tests/doubles.py:1-3`, `:35`, `:129`, `:213`, `:222`, `docs/STATUS.md` 남은 일 첫 항목.
- 인용: `def make_question_reader(**_ignored) -> FakeQuestionReader`
- 왜: 이웃 영역이 배포하는 메모리 구현으로 바꾸는 일이 STATUS에 "남은 일"로 열려 있다. 대역이 `QuestionBank` 본문 모양(`make_bank`)까지 만든다 즉 이웃 데이터 모양을 가정한다. 현재는 Protocol과 계약 스키마 안에서만 동작하므로 코드 결합은 없다.
- 수정 방향: 이웃 메모리 구현이 나오면 교체(이미 기록됨).

**SD-21 | R1·R3 | P3 | 사소한 숨은 결합**
- `adapters.py:4` 독스트링 예시에 이웃 호스트·포트(`http://question-authoring:8080`)가 있다(설정 예시이며 코드는 쓰지 않음).
- `schemas.py:14` 모듈 import 시 `warnings.filterwarnings("ignore", category=DeprecationWarning, module="jsonschema")`로 프로세스 전역 경고 설정을 바꾼다(전역 상태).
- `scripts/smoke_service.sh:23`이 읽기 토큰 역할 이름 `model-lab=`를 쓴다. 이 이름은 HTTP.md I2의 소비자 역할과 일치하므로 계약상 허용으로 본다(결합 아님, 확인용 기록).

**SD-22 | 계약 F (INTERFACES I8, METRICS.md) | P3(확인 필요) | `import`는 v2 의미 검사를 하지 않는다**
- 위치: `importer.py:328`, `quality.py` 독스트링.
- 인용: `report["semantic_checks"] = {"performed": False, "reason": ... 스키마 검증만 했다"}`
- 왜: METRICS.md는 "기준 시험: 학습 데이터 A 출력 전수가 위반 0"이라 적고 INTERFACES I8은 `validate_extraction`이 의미 검증 안전망이라 한다. 이 영역은 그것을 호출하지 않는다고 스스로 밝힌다(CR-006 2항, brief). R7 관점에서 중복은 아니고 누가 이 기준 시험을 돌리는지가 정해지지 않았다. 규칙 위반이 아니라 계약 쪽 미정이다.

## C. R5: 영역 안 스키마 정의 위치

| 대상 | 정의 | 판정 |
|---|---|---|
| 샘플 레코드, 매니페스트, 모델 입출력 | boundary-contracts 패키지 스키마를 `Validators`로 검증(`schemas.py`) | 기계가 읽는 형태, 한 곳 |
| 문항 은행 | 문진 스키마(`survey_dir/schemas/*.json`), `Validators.survey` | 기계가 읽는 형태 |
| `Seed`, `QuestionSetContext`, `JobConfig`, `ImportConfig`, `JobResult`, `ImportResult` | 데이터클래스 | 타입 있음. 단 파싱은 손코드, 스키마 파일 없음(SD-01) |
| 시드 샘플 dict(3→4→5→6→8) | 정의 없음(키 관습) | 암묵(SD-08, SD-12) |
| 입력 jsonl 행(messages) | `validate_row` 코드와 독스트링 | 암묵(SD-03) |
| 보고서 `report.json`, `import_report.json` | 코드가 만드는 dict | 암묵(SD-04) |
| 저장소 배치 `<root>/<id>/<ver>/{manifest.json, meta.json, files/}` | `file_store.py` 독스트링 | 영역 안, 서버가 직접 의존(SD-11) |
| `output.store` 설정 | `store/spec.py::parse_store` 한 곳, 잡·게시기 공용 | 한 곳(좋음), 스키마 파일은 없음 |

## D. R1: 이웃 구조에 기대는 곳

- 이웃 패키지 import: 없음. `grep -rn "^import|^from" synthetic_data`로 확인한 외부 import는 `boundary_contracts`(+`clients`, `sdk`, `canonical`, `errors`), `jsonschema`, 표준 라이브러리뿐이다. 예외: `job.py:52` `import turn_engine`(SD-06, 허용된 라이브러리 의존이나 선언·핀 없음).
- 이웃 폴더 경로: `../model-lab`(SD-02, P1), `../survey-service/schema`(허용 범위, SD-07), `../boundary-contracts`(코드·스크립트에서는 참조하지 않음, `grep` 확인), 설정의 `../work/...`는 자기 영역 폴더(`work/`, `.gitignore`로 제외).
- 이웃 환경 변수 이름: 없음. 이웃 토큰은 설정의 `token_env`(이름을 설정으로 받음)로 받고 코드에 이웃 변수명이 없다. 서버 환경 변수는 `DATASET_STORE_*`(자기 것)이며 `boundary.md` 4절에 이름이 있다.
- 이웃 포트·호스트: `adapters.py:4` 독스트링 예시만(SD-21).
- 이웃 설정 키·Dockerfile 인자·응답 모양: I7 응답의 모르는 필드를 `load_schema("FailureCase")["properties"]`와 비교해 보고서에 남긴다(`seeds.py:48`, 읽기 모드 CONVENTIONS 1절을 따름, 계약 스키마만 참조).
- 허용된 참조의 실제 사용: `../survey-service/schema`(SD-07), `../boundary-contracts`는 사용하지 않음(태그 설치, `requirements.lock`).

## E. R6: 영역 간 인터페이스의 계약 스키마

| 인터페이스 | 제공/소비 | 계약 위치 | 상태 |
|---|---|---|---|
| I2 DatasetStore | 제공(model-lab이 소비) | `INTERFACES.md` I2, `HTTP.md ## I2`, `DatasetManifest`, `ActionExtractionSample`, `ResponseSample` 스키마 | 있음 |
| I1 QuestionReader | 소비 | `INTERFACES.md` I1, `HTTP.md ## I1`, `QuestionBank`(문진 스키마), `ArtifactRef`, `ReviewRecord`, `ChangeClassification` | 있음 |
| I7 FailureStore | 소비 | `INTERFACES.md` I7, `HTTP.md ## I7`, `FailureCase` | 있음 |
| I8 turn-engine | 버전만 | `INTERFACES.md` I8(`ENGINE_VERSION`) | 있음(호출 없음) |

계약에 없는데 영역 경계를 넘는 형식:
1. 잡 설정(`run`, `import`) (SD-01, P1).
2. 외부 학습 데이터 jsonl 6개 형식과 파일 이름 (SD-03).
3. 잡 표준 출력 JSON, 종료 코드(0/2/3/4/75), `report.json`/`import_report.json` (SD-04).
4. 설정의 `adapters.*.factory` 문자열과 kwargs (SD-05).
5. 서버 이미지의 빌드 인터페이스: 빌드 컨텍스트 `survey_schema`·`wheels`, 빌드 인자 `BC_SPEC`, `BC_VERSION`, `SURVEY_SCHEMA_VERSION`, `REVISION`(`Dockerfile:2-4,13,22-24`), 이미지 라벨 6개(`Dockerfile:38-43`, 워크스페이스 D50), 서버 환경 변수 `DATASET_STORE_*`(`app.py` 머리말, `boundary.md` 4절). 라벨은 워크스페이스 규칙이 정한 것이고 나머지는 영역 문서에 이름이 있으나 계약은 아니다. HTTP.md는 "영역 문서가 이름을 정한다"고 하므로 토큰 변수명은 허용된 위임이다.
6. 영역 안에서 정의됐지만 경계를 넘는 스키마: `ext["synthetic-data"]`(샘플 `kind`, 매니페스트 `dataset_digest`, `unseen_eval_files`, `import` 하위 객체; `package.py:67-68`, `importer.py:425-434`). 계약은 `ext` 자유 키를 허용하고 소비자는 판단에 쓰지 않는다고 boundary.md 3절이 적었다. 승격 요청은 CR-004.

## F. 계약 준수

### F-1. I2 서버 vs `HTTP.md ## I2` (한 줄씩)

| 계약 | 구현 | 판정 |
|---|---|---|
| `list_ids`: `GET /v1/datasets`, 사전순 | `app.py:349-350`, `list_ids`(`:172-177`) `sorted(...)`, 버전 없는 디렉터리 제외 | 일치 |
| `list_versions`: `GET /v1/datasets/{id}/versions`, 오래된 것부터 | `app.py:351-353`(`_DS`), `file_store.py:130-135`(`seq` 순) | 일치. 모르는 데이터셋은 200 `items: []`(계약은 침묵; INTERFACES는 `[]`) |
| `get_manifest`: `GET .../versions/{version}`, 없으면 404 | `app.py:354-356`; `base.py:68-69` NOT_FOUND; 잘못된 ID는 400(`_check_id`) | 일치 |
| `download`: `GET .../files`, tar, `manifest.files[].path` 그대로 | `app.py:357-363`, `dataset_tar`(`:195-197`), `tarutil.pack`; 서버가 파일 해시를 청크로 확인 | 일치(`test_service_contract` 통과) |
| `open_file`: `GET .../files/{path}`, `%2F` 한 덩어리, octet-stream, 매니페스트에 없으면 404 | `app.py:364-370`(정규식 `[^/]+` 후 `unquote`), `verified_file` NOT_FOUND(`:183-184`), 반환 `application/octet-stream` | 일치 |
| `path`에 `..`·절대 경로·역슬래시 금지 | `app.py:367` `_check_path`(400), `tarutil._safe`(`:22-28`) | 일치 |
| `publish`: `POST /v1/datasets`, 본문 tar `manifest.json` + `files/<path>` | `app.py:343-346`, `_publish_locked`(`:395-437`) | 일치 |
| 새로 만들면 201, 같은 hash면 200, 다르면 409 | `app.py:437` `200 if existed else 201`; 충돌은 `base.py:104` CONFLICT -> 409(`STATUS`); 잠금(`:427`)으로 같은 시점 판정 | 일치 |
| 응답은 매니페스트 | `app.py:436-437` `res` = `publish` 반환 | 일치 |
| 검증: manifest 스키마, 파일 집합, 파일 해시, 줄 수, EVAL 겹침 | `base.py:93`, `:115-118`, `:140-141`, `:146-147`, `:148-151` | 일치(400 `INVALID_RECORD`, 해시 불일치 422 `INTEGRITY_ERROR`) |
| 읽기 토큰은 `publish` 403 | `app.py:119-124` `authorize`: POST는 쓰기 역할만 | 일치(스모크 `smoke_service.sh:80`도 403) |
| 쓰기 역할 `synthetic-data` | `app.py:42`, `:77-79` | 일치 |
| 오류는 `BoundaryError`, 상태 코드 표 | `app.py:40-41` `STATUS`: 400/403/404/409/412/422/422/503 | 표와 일치(CONVENTIONS 9) |
| 토큰 없음/틀림 = 403(영역 사이 API) | `app.py:122-124` PERMISSION_DENIED | 일치(CONVENTIONS 9 보충 (2)) |
| 과다 요청은 503 `UNAVAILABLE` | `app.py:336`, `:376`, `:389`, `:472-481` | 일치. `Retry-After`는 없음(계약: 서비스마다 다르고 없을 수 있음) |
| 토큰을 `<이름>_TOKENS`, `_FILE`로(D84) | `app.py:498-499` `read_secret("DATASET_STORE_READ_TOKENS")` | 일치 |
| `/healthz`, `/readyz` 인증 없음 | `app.py:328-332` | 존재·무인증 일치. `/readyz`의 사유·2초 상한은 SD-18 |
| 페이지: `limit` 기본 100 최대 500, `cursor`, `next_cursor` | `app.py:235-256` | 일치 |
| tar에 `..`·절대·심볼릭 링크 금지 | `tarutil.unpack`(`:31-64`) 일반 파일만, 링크 거부 | 일치 |
| 멱등(CONVENTIONS 4) | 위 201/200/409, 같은 버전 동시 게시는 `dataset_lock` | 일치 |
| 지정 안 된 동작 | 본문 상한 초과를 400 `INVALID_RECORD`로 냄(`:386-387`), HEAD/OPTIONS는 405(`:451-458`) | 계약에 값 없음. 확인만 기록 |

적합성 시험: boundary-contracts에 서버용 적합성 모음은 `conformance/servers.py`(참조 서버)이며 이 영역 서버를 직접 겨누는 시험은 아니다. 이 영역의 `tests/test_service_contract.py`가 계약 클라이언트 `HttpDatasetStore`로 실제 서버를 읽고 쓴다(통과, 위 전체 164건에 포함). `boundary-contracts` 쪽 시험 모음은 돌리지 않았다.

### F-2. I1 소비 vs `HTTP.md ## I1`, `INTERFACES.md` I1

| 호출 | 코드 | 판정 |
|---|---|---|
| `latest(id, reviewed_only)` | `job.py:94` | 일치(Protocol 사용) |
| `list_versions(id, cursor, limit)` | `job.py:64` `_find_ref` 페이지 순회 | 일치 |
| `get_question_bank(ref)` | `job.py:98` + 해시 재확인 `:99`(SD-17) + 문진 스키마 검증 `:101` | 일치 |
| `get_reviews(ref)` | `job.py:96` `decision == "APPROVED" and clinical_basis_approved` | 일치. 필드명을 `ReviewRecord` 스키마와 대조하지는 않았다(대역 시험만) |
| `get_change(ref)` | `job.py:103-104` `"REGENERATE_SAMPLES" in ch["follow_ups"]` | 일치(`{"item": ...|null}`은 클라이언트가 푼다) |
| 호출 방식 | `adapters.py:25-26` `HttpQuestionReader(base_url, token, timeout)`; 토큰 `read_secret` | 계약(클라이언트 생성자 인자, D84) 일치 |

운영 이웃과 실제 HTTP 연동은 하지 않았다(대역·참조 서버 시험만).

### F-3. I7 소비 vs `HTTP.md ## I7`

| 호출 | 코드 | 판정 |
|---|---|---|
| `list_cases(review_status=CONFIRMED, latest_only)` | `seeds.py:30` | 쿼리 이름이 `HTTP.md` I7과 일치(클라이언트 `ops.py:27-36`) |
| `FailureCase` 필드 `expected`, `expected_kind`, `reviewed_input`, `question_set`, `deidentified`, `runtime_contract_version` | `seeds.py:44-75` | `FailureCase.schema.json`에 필드 존재 확인(`deidentified`, `expected_kind`, `reviewed_input`) |
| `get_trace` | 호출 없음(boundary.md는 쓴다고 적음, SD-19) | 코드가 문서보다 좁다 |
| 비식별 거부 | `seeds.py:44-45` | brief 요구. R7과의 충돌은 SD-13 |

### F-4. 매니페스트(I2 산출)

`package.py:61-69`와 `importer.py:420-434`는 `DatasetManifest`의 필수 필드를 채우며 `store.publish`가 스키마를 통과시킨다(시험 통과). `scenario_disjoint_across_splits`는 두 곳 모두 리터럴 `True`로, 실제 값은 `publish`의 겹침 검사가 보증한다(`base.py:148-151`). `pipeline_schema_version`은 설치된 패키지 값(`__init__.py:3`), 읽기 MAJOR는 2(`:4`)로 `boundary.md` 4절과 일치.

## G. R7 요약

이중 검증·재구현은 SD-10(패키징), SD-13(시드 재검증), SD-14(샘플 스키마 4~5중), SD-16(`scenario_id` 겹침), SD-17(문항 은행 해시). 재시도 이중화: 잡은 재시도하지 않고 종료 코드 75로 스케줄러에 맡긴다(`__main__.py`, boundary.md 6절). 서버·클라이언트 모두 자체 재시도는 없다(`grep -rn "retry|sleep"`에서 `setup-env.sh` 외 없음). 계약이 직접 정한 이중(클라이언트가 보내기 전에 확인 + 서버가 확인, 다운로드 해시 재확인)은 위반으로 세지 않았다.

## 문제없음 항목(확인 방법)

- 비밀: `grep -n "environ\|os.environ"`로 서버 진입점(`app.py:496-518`)과 `read_secret`(`adapters.py`, `store/spec.py`)에서만 읽음을 확인. 토큰 값은 설정에 못 들어간다(`store/spec.py:37-38`). 스모크가 로그에 비밀이 없음을 확인하는 스크립트를 가짐(`scripts/assert_no_secret.sh`, 내용만 확인). 환경 변수 `env` 출력·비밀 파일 읽기는 하지 않았다.
- 이웃 코드 import 없음(D 절).
- 이미지: 비루트(`Dockerfile:30,35` uid 10001), 라벨 6개 키가 D50과 일치(`:38-43`), `/healthz`, 설정은 환경 변수.
- 스모크가 고정 포트를 쓰지 않음(`smoke_service.sh:69` `-p 127.0.0.1::8080`).
- 의존 고정: `requirements.lock`, `requirements-service.txt`(boundary-contracts 태그 v2.1.1).
- ADR: `docs/adr/`에 14건(Nygard 형식 항목은 0010·0013·0014만 전문을 읽었다). 주요 선택(저장소, HTTP 서버, 한도) ADR 존재는 목록으로만 확인.

## 점검하지 못한 것

- deploy 쪽 코드(`deploy/scripts/e2e_steps.py` 등): 허용 범위 밖이라 읽지 않았다. 따라서 deploy가 이 영역의 설정·출력·종료 코드를 실제로 어떻게 쓰는지(SD-01, SD-04, SD-05)는 ADR 0010·0014의 진술에 기댄 것이다.
- `docs/design.md` 부록 A·B, `docs/CHANGELOG.md`, `docs/rules/*`, CR-001~005·007, ADR 0001~0009·0011·0012 전문(목록과 일부만 읽음).
- `tests/` 파일의 개별 본문(실행과 헤더·일부 확인만).
- 컨테이너 이미지 빌드와 `scripts/smoke_service.sh` 실행: wheel 폴더(model-lab)가 필요하고(SD-02) Docker/SSH가 필요해 돌리지 않았다. 따라서 이미지 `/healthz` 응답은 이번에 확인하지 못했다.
- boundary-contracts의 자체 시험·`verify.py`: 돌리지 않았다.
- I1·I7 실제 이웃 서비스와의 HTTP 연동, `ReviewRecord`·`ChangeClassification` 필드 이름의 스키마 대조.
- 서버의 부하·타임아웃 값 측정(ADR 0012·0013이 "측정 안 함"으로 적은 값들)과 `/readyz` 2초 상한 실측.
- 실제 학습 데이터 파일(`SD_REFERENCE_DATA_DIR`)을 쓰는 시험 1건.
