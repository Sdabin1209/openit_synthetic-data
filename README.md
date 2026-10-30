# synthetic-data (합성 데이터)

데이터셋 담당의 최종 학습 데이터를 검증해(`import`), 그리고 확정된 실패 사례를 시드 샘플로 만들어(`run`) 데이터셋 저장소에 게시하는 **run-once 잡**입니다.

이 영역은 문진 시스템에서 모델을 학습시키는 쪽에 먹일 연습문제집을 만듭니다. 설정 파일 하나로 한 번 돌고 끝나며(같은 입력과 시드면 같은 결과, 여러 번 실행해도 안전), 결과는 불변 버전으로 저장소에 쌓입니다. 하지 않는 것: 모델 학습·평가, 평가셋의 합성·실제 비율 결정(O11, 사용자 몫), 실제 환자 발화 수집, 잡(`run`, `import`)의 웹 서비스 운영(잡에는 `/healthz`가 없다. I2 서버 dataset-store에는 있다).

> 중요(G02, D91): 이 영역은 합성 데이터를 생성하지 않습니다. 학습 데이터 본체는 데이터셋 담당이 서버에서 만든 최종 데이터를 재생성 없이 가져와 검증·게시하는 **게시기(`import`) 모드**가 맡고(docs/design.md 부록 A), 실제 C1 학습 데이터 6개(64,459행)로 검증·임시 저장소 게시·멱등 재실행을 확인했습니다(결과: docs/design.md 부록 B). 운영 저장소 게시와 의미 검사는 하지 않았습니다. v1 생성 경로는 제거했고 `run`은 **시드 잡**(확정된 실패 사례를 시드 샘플로 게시)만 합니다(docs/adr/0010).

## 1. 전체 속의 위치

| 방향 | 이웃 | 인터페이스 | 내용 |
|---|---|---|---|
| 입력 | question-authoring | I1 `QuestionReader`(HTTP 클라이언트) | 문항 세트, 검수 결과, 변경 분류(`REGENERATE_SAMPLES`) |
| 입력 | ops-feedback | I7 `FailureStore`(HTTP 클라이언트) | 확정된 비식별 실패 사례(시드) |
| 출력 | model-lab | I2 `DatasetStore` | `ActionExtractionSample`, `ResponseSample`, `DatasetManifest` |

HTTP 경로는 이 영역 문서에 없어 `../boundary-contracts/HTTP.md`로 확인해야 하며 이번에 읽지 않았습니다(미확인). 비식별되지 않은 사례를 받으면 실행을 거부합니다.

## 2. 구조

영역 내부는 컴포넌트·스키마·wiring으로 나눈다(D117, ADR 0021). 컴포넌트 표(입력·출력 타입, 하는 일)는 `docs/components.md`, 스키마와 "스키마 밖 조건" 표는 `schemas/README.md`.

| 경로 | 역할 |
|---|---|
| `schemas/` | 영역 내부 타입의 JSON Schema(draft 2020-12)와 통과·거부 예시(`schemas/examples/`) |
| `synthetic_data/types/` | `schemas/`에서 생성한 코드 타입과 스키마 사본(손으로 고치지 않는다, 4절 생성 명령) |
| `synthetic_data/components/` | 컴포넌트마다 파일 하나(29개). 통신은 `link_*`(받는 쪽 `link_dataset_store_server`, 보내는 쪽 `link_question_reader`·`link_failure_reader`·`link_dataset_publish`), 저장소는 `dataset_store` |
| `synthetic_data/wiring/` | 컴포넌트 연결(`import_job.py`, `run_job.py`)과 주입(`stores.py`, `survey.py`), 설정→계획(`plans.py`), 서비스 기동(`service.py`) |
| `synthetic_data/__main__.py`, `config.py`, `service/__main__.py`, `adapters/__init__.py` | 진입점, 설정 읽기, 설정 값 호환 별칭(변경 요청 CR-S-001) |
| `Dockerfile`, `requirements-service.txt`, `scripts/smoke_service.sh` | I2 HTTP 서버 이미지(dataset-store, D100, ADR 0012·0017). 잡은 `output.store.kind: http`로 게시(ADR 0013) |
| `configs/dev.job.json` | 이웃 대역을 쓰는 개발용 설정 |
| `tests/` | 적합성·잡 종단·HTTP 통합·단위·구조 시험(`test_structure.py`), 이웃 대역 `doubles.py` |
| `requirements.lock` | 의존 고정(boundary-contracts·openit-link 태그의 정본. Dockerfile·스모크가 여기서 읽는다) |
| `docs/` | 8절 참고 |

```
run:    설정(JSON) -> 문항 읽기(I1) -> 시드 수집(I7) -> 시드 샘플 -> 품질 검사 -> 분할 -> 패키징 -> 게시(I2)
import: 설정(JSON) + 학습 데이터 jsonl 6개 -> 행 검증 -> 허용치 판정 -> 패키징 -> 게시(I2)
```


## 3. 실행 방법

전제: Python 3.10 이상(pyproject.toml), git, 계약·문진 스키마 태그를 받을 SSH 접근. 이웃 폴더는 시험에 필요 없습니다(둘 다 `requirements.lock`의 태그로 설치). Docker는 필요 없습니다. 잡은 이미지 없이 `requirements.lock`으로 고정하기로 헤드가 승인했습니다(docs/runbook.md). I2 서버만 Dockerfile이 있습니다.

```bash
# 설치 (멱등. .venv 생성, requirements.lock + pytest + -e . 설치)
bash scripts/setup-env.sh
. .venv/bin/activate

# 시험
python -m pytest -q

# 개발용 잡 실행 (이웃은 tests/doubles.py 대역)
PYTHONPATH=tests python -m synthetic_data run --config configs/dev.job.json [--created-at 2026-10-15T00:00:00Z]
```

- 출력은 JSON 한 줄(`status`, `version`, `content_hash`, `counts`, `report_path`). 종료 코드: 0 성공, 2 설정 오류, 3 재시도 불가 경계 오류, 75 재시도 가능(스케줄러가 재실행).
- 비밀(D84): 이웃 호출 토큰은 값이 아니라 `NAME_FILE`(파일 경로, 배포에서는 `/run/secrets/...`)로 받습니다. 설정의 `token_env`는 비밀 이름이고, 파일이 없을 때만 `NAME` 환경 변수(개발 전용)를 씁니다. 값은 로그·보고서에 남지 않습니다.
- 게시기: `python -m synthetic_data import --config configs/import.example.json`. 입력 jsonl 6개를 행마다 v2 스키마로 검증하고, 실패는 사유별로 집계하며 허용치를 넘으면 게시하지 않습니다(종료 코드 4). 자세한 것은 docs/runbook.md.
- 게시기 보고서: 중복 발화·개인정보 의심 패턴 건수, `deid_attested: false`(비식별은 확인하지 않음), 의미 검사 미수행 표시. 입력 값은 담지 않습니다.
- 결과 확인: `<work_dir>/report.json`(버린 사유 `dropped`), `review_sample.jsonl`, 저장소의 `<root>/<dataset_id>/<version>/manifest.json`.

이 문서를 쓰며 **실제로 돌린 것**과 시험 개수는 5절에 있습니다. I2 서버 스모크는 `scripts/smoke_service.sh`(이미지 빌드, `/healthz`·`/readyz`, 권한, 계약 클라이언트로 게시·조회; 빈 포트를 Docker가 배정). 빌드에 문진 스키마 컨텍스트와 계약 wheel이 필요하다(wheel은 스크립트가 태그에서 만든다. ADR 0011, 스크립트 머리말).

## 4. 현재 상태

확인된 것은 5절의 실행 결과입니다. 문서의 진술에 기댄 것(이번에 다시 확인하지 않음):
- I2 파일·메모리 구현이 같은 적합성 시험을 통과, 같은 입력과 시드는 같은 `dataset_digest`(docs/STATUS.md).
- D84(NAME_FILE)와 boundary-contracts 갱신 반영, 비밀이 산출물에 안 나오는 시험 추가(CHANGELOG 0.2.2, 제안 버전). 버전은 pyproject 0.2.0, CHANGELOG는 0.2.2(제안)로 어긋나 있다(docs/STATUS.md).
- 변경 요청 CR-001~005는 헤드가 결정(docs/STATUS.md). CR-007(v1 생성 경로 제거 제안)은 시드 경로를 남기는 범위까지 ADR 0010으로 실행했다.

확인 못 한 것: 게시기를 운영 저장소에 게시한 적 없음, v2 의미 검사 미수행(CR-006), 이웃 영역과의 실제 HTTP 연동(운영 환경), 이미지·E2E(해당 없음 또는 미실행).

### 타입 생성 (손으로 고치지 않는다)

`schemas/*.schema.json`을 고치면 아래로 `synthetic_data/types/`를 다시 만든다(도구 버전은 `requirements.lock`에 고정: datamodel-code-generator, black, isort). `tests/test_structure.py`가 다시 만든 결과와 저장소의 것이 같은지 본다.

```bash
.venv/bin/python scripts/gen_types.py
```

구조 검사: `.venv/bin/python -m pytest -q tests/test_structure.py` (헤드 도구는 `python3 head/scripts/structure-check.py synthetic-data`).

## 5. 시험 상태

시험 상태(이 영역 시험 개수는 이 절에만 적는다). 2026-10-30 U400 구조 개편 후, 이 작업 환경(워크스페이스의 worktree, 계약 v3.1.1·openit-link v0.1.0을 태그에서 설치한 `.venv`)에서 `python -m pytest -q` -> 258 통과, 1 건너뜀, 0 실패(구조 시험 `tests/test_structure.py` 7건 포함). 건너뜀 1건은 `SD_REFERENCE_DATA_DIR`(실제 학습 데이터 파일 경로)가 없어서다. 구조 검사 `head/scripts/structure-check.py`: 통과. 이미지 스모크 `scripts/smoke_service.sh`와 빌드 진입점 `scripts/smoke_build_image.sh`: 같은 환경에서 SMOKE_OK와 BuildImageResult 확인(`/healthz`·`/readyz`·권한·게시·조회). 줄 검증 속도는 한 줄 약 0.5ms(LoRA-A 대표 행 2000줄 측정)이고 실제 C1 데이터 6개(64,459행) 전체로는 돌리지 않았다. 돌리지 않은 것: 서비스끼리 도는 시험, 운영 이웃 영역과의 연동. 서비스끼리 도는 시험의 결과는 deploy/docs/E2E_RESULTS.md를 본다.

## 6. 이 영역의 열린 항목 (head/docs/OPEN_GAPS.md)

| ID | 요약 | 막는 것 |
|---|---|---|
| G02 | v1 생성 경로와 보류 시험 15건 | 제거함(ADR 0010). 시드 경로(`run`)는 E2E 단계 7이 쓰므로 남김. 게시기 구현됨, 운영 게시는 미실시, 열린 질문은 CR-006. 시드를 이 영역에 계속 둘지는 헤드 결정(ADR 0010 대안 1) |
| (대장 밖) 시드 `run` 존속 | 헤드 결정(2026-10-28): 유지. deploy 단계 7이 호출 | 제거 여부는 데이터셋 담당 이전 계획과 함께 나중에(ADR 0010 후속) |
| (대장 밖) `regeneration.mode`, 감수 샘플링(`review_sample.jsonl`, `review.per_kind`) | 이름은 생성용. deploy는 설정 값을 써넣기만 하고 산출물을 읽는 곳은 grep으로 못 찾음 | 삭제하지 않고 열림(ADR 0010) |
| U07(일부) | v2 E2E에서 "단계 2(G02)"를 건너뜀 | G02 결정 |
| O11 | 평가셋 구성과 합성·실제 비율(OPEN_GAPS에는 없고 docs/brief.md에 있음) | 사용자 결정. `split.ratios`는 예시 값만 |

그 밖의 대장 항목 중 이 영역 직접 항목은 grep으로 찾지 못했으나(`synthetic`, `합성`, `G02`, `O11`, 데이터셋 검색) 전체를 정독하지는 않았습니다(미확인).
GPU가 막는 항목은 이 영역에 없습니다(잡은 CPU만 사용).

## 7. 남은 일 (docs/STATUS.md)

v2 의미 검사는 계약의 `boundary_contracts.action_rules.check_action_extraction` 연결 여부 미정(CR-006), 이웃 대역을 실제 SDK로 교체.

## 8. 더 자세한 문서

| 문서 | 내용 |
|---|---|
| `CLAUDE.md` | 이 영역 에이전트 지침 |
| `docs/brief.md` | 영역 목적, 범위, 수용 기준 |
| `docs/boundary.md` | 소유 저장소, I2 SDK, 소비 계약과 버전, 게시 검증, 장애 영향 |
| `docs/design.md` | 내부 설계(일부는 v1 시점 기록) |
| `docs/runbook.md` | 실행, GPU 호스트, 설정 필드, 문제 대응, 비밀 |
| `docs/STATUS.md` | 한 일, 남은 일, 막힌 것 |
| `docs/CHANGELOG.md` | 변경 이력 |
| `docs/adr/` | 구조 선택의 '왜' (ADR 0001~0015, 목록은 `docs/adr/README.md`) |
| `docs/change-requests/` | 헤드에게 낸 변경 요청 CR-001~005 |
| `docs/rules/` | 헤드가 전달한 업무 규칙(출처 SOURCE.md) |
