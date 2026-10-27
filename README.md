# synthetic-data (합성 데이터)

문항 정의와 실패 사례로 LoRA-A(발화 해석)·LoRA-B(응답 문장) 학습·검증·평가 데이터를 만들어 데이터셋 저장소에 게시하는 **run-once 잡**입니다.

이 영역은 문진 시스템에서 모델을 학습시키는 쪽에 먹일 연습문제집을 만듭니다. 설정 파일 하나로 한 번 돌고 끝나며(같은 입력과 시드면 같은 결과, 여러 번 실행해도 안전), 결과는 불변 버전으로 저장소에 쌓입니다. 하지 않는 것: 모델 학습·평가, 평가셋의 합성·실제 비율 결정(O11, 사용자 몫), 실제 환자 발화 수집, 웹 서비스 운영(서비스가 아니라 `/healthz`도 없음).

> 중요(G02): 생성 파이프라인(`run`)은 v1 내용을 만들어 합성 샘플이 전부 걸러지므로 운영에서 돌리지 않습니다. 사용자가 정한 방향은 데이터셋 담당이 서버에서 만든 최종 학습 데이터를 재생성 없이 가져와 검증·게시하는 것이고, 그 **게시기(`import`) 모드**를 구현했습니다(docs/design.md 부록 A). 단 **실제 데이터로 게시한 적은 없습니다**(가짜 입력 시험만, 행 형식은 추정).

## 1. 전체 속의 위치

| 방향 | 이웃 | 인터페이스 | 내용 |
|---|---|---|---|
| 입력 | question-authoring | I1 `QuestionReader`(HTTP 클라이언트) | 문항 세트, 검수 결과, 변경 분류(`REGENERATE_SAMPLES`) |
| 입력 | ops-feedback | I7 `FailureStore`(HTTP 클라이언트) | 확정된 비식별 실패 사례(시드) |
| 입력 | turn-engine | I8 | 버전(`ENGINE_VERSION`)만. 호출은 아직 없음(CR-002) |
| 출력 | model-lab | I2 `DatasetStore` | `ActionExtractionSample`, `ResponseSample`, `DatasetManifest` |

HTTP 경로는 이 영역 문서에 없어 `../boundary-contracts/HTTP.md`로 확인해야 하며 이번에 읽지 않았습니다(미확인). 비식별되지 않은 사례를 받으면 실행을 거부합니다.

## 2. 구조

| 경로 | 역할 |
|---|---|
| `synthetic_data/job.py`, `__main__.py`, `config.py` | 잡 진입점(`run`)과 설정 |
| `scenario.py`, `plans.py`, `directives.py` | 시나리오 설계(v1 내용) |
| `generators/` | 발화·응답 문장 생성기(규칙 기반, 교체 가능한 Protocol) |
| `noise.py`, `labeler.py`, `seeds.py` | STT 노이즈, 정답 구성, 실패 사례 시드 |
| `quality.py`, `split.py`, `package.py` | 품질 검사, 시나리오 단위 분할, 패키징 |
| `store/` | I2 구현(파일 `FileDatasetStore`, 메모리 `MemoryDatasetStore`) |
| `importer.py` | 게시기(import) 모드: 외부 학습 데이터 검증·게시 |
| `adapters.py`, `schemas.py` | 이웃 HTTP 연결 공장, 스키마 검증 |
| `configs/dev.job.json` | 이웃 대역을 쓰는 개발용 설정 |
| `tests/` | 적합성·잡 종단·HTTP 통합·단위 시험, 이웃 대역 `doubles.py` |
| `requirements.lock` | 의존 고정(boundary-contracts v2.0.2 태그) |
| `docs/` | 7절 참고 |

```
설정(JSON) -> 문항 읽기(I1) -> 시나리오 설계 -> 발화 생성 -> STT 노이즈 -> 정답 구성 -+
              시드 수집(I7) -> 시드 샘플 ----------------------------------------------+
                                                                                        v
  게시(I2) <- 패키징 <- 분할(시나리오 단위) <- 중복 제거 <- 품질 검사 <- 샘플 레코드
```
(docs/design.md 1절의 도식을 줄인 것)

## 3. 실행 방법

전제: Python 3.10 이상(pyproject.toml), git. `../boundary-contracts`(개발용 작업 트리)와 `../survey-service/schema`가 형제 폴더에 있어야 합니다. Docker는 필요 없습니다. 서비스가 없는 잡이라 Dockerfile 없이 `requirements.lock`으로 고정하기로 헤드가 승인했습니다(docs/runbook.md).

```bash
# 설치 (배포는 boundary-contracts를 git ssh 태그로 설치하므로 SSH 접근이 필요)
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements.lock pytest
pip install -e ../boundary-contracts          # 개발용: 작업 트리로 덮어씀

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

이 문서를 쓰며 **실제로 돌린 것**: `python -m pytest --collect-only -q`(104건 수집), `python -m synthetic_data --help`(정상). **돌리지 않은 것**: 전체 pytest 실행, `run` 잡, pip 설치. 스모크 스크립트는 없습니다(서비스가 아님).

## 4. 현재 상태

확인된 것(근거 문서의 진술이며 이번에 시험을 다시 돌려 확인하지는 않았음):
- v2 이전(D74/D75) 시점에 시험 85건 통과, 15건 보류(생성기 v2 대기, `tests/conftest.py`의 `needs_generator_v2`)였다(CHANGELOG 0.2.0). 현재 수집은 104건, 그중 skip 15건이고 D84가 시험 4건을 더해 실행 대상은 89건이다(수집·표시 개수는 확인, 통과 여부는 미확인). 버전은 pyproject 0.2.0, CHANGELOG는 0.2.2(제안)로 어긋나 있다(docs/STATUS.md).
- I2 파일·메모리 구현이 같은 적합성 시험을 통과, 같은 입력과 시드는 같은 `dataset_digest`(docs/STATUS.md).
- D84(NAME_FILE)와 boundary-contracts v2.0.2 반영, 비밀이 산출물에 안 나오는 시험 추가(CHANGELOG 0.2.2, 제안 버전).
- 변경 요청 CR-001~005는 헤드가 결정(docs/STATUS.md).

확인한 것(2026-10-27 `pytest -q` 실행 출력): 113 passed, 15 skipped(전체 128건 수집). 늘어난 24건은 게시기 시험(`tests/test_import.py`, 가짜 입력)이다. 확인 못 한 것: 게시기를 실제 학습 데이터 파일로 돌린 적 없음(행 형식 추정), v2 의미 검사 미수행(CR-006), 이웃 영역과의 실제 연동, 이웃 영역과의 실제 HTTP 연동(운영 환경), 이미지·E2E(해당 없음 또는 미실행), turn-engine 연동(미구현).

## 5. 이 영역의 열린 항목 (head/docs/OPEN_GAPS.md)

| ID | 요약 | 막는 것 |
|---|---|---|
| G02 | 생성 파이프라인이 v1 내용을 만들어 합성 샘플이 전부 걸러짐. 15개 시험 보류 | 방향은 사용자가 정함(서버 데이터를 그대로 가져와 게시). 게시기 구현됨, 실제 데이터 게시는 미실시, 열린 질문은 CR-006 |
| U07(일부) | v2 E2E에서 "단계 2(G02)"를 건너뜀 | G02 결정 |
| O11 | 평가셋 구성과 합성·실제 비율(OPEN_GAPS에는 없고 docs/brief.md에 있음) | 사용자 결정. `split.ratios`는 예시 값만 |

그 밖의 대장 항목 중 이 영역 직접 항목은 grep으로 찾지 못했으나(`synthetic`, `합성`, `G02`, `O11`, 데이터셋 검색) 전체를 정독하지는 않았습니다(미확인).
GPU가 막는 항목은 이 영역에 없습니다(잡은 CPU만 사용).

## 6. 남은 일 (docs/STATUS.md)

v2 의미 검사는 turn-engine `validate_extraction` 이후(미정), turn-engine 연동(CR-002), LLM 생성기와 재현성, 이웃 대역을 실제 SDK로 교체.

## 7. 더 자세한 문서

| 문서 | 내용 |
|---|---|
| `CLAUDE.md` | 이 영역 에이전트 지침 |
| `docs/brief.md` | 영역 목적, 범위, 수용 기준 |
| `docs/boundary.md` | 소유 저장소, I2 SDK, 소비 계약과 버전, 게시 검증, 장애 영향 |
| `docs/design.md` | 내부 설계(일부는 v1 시점 기록) |
| `docs/runbook.md` | 실행, GPU 호스트, 설정 필드, 문제 대응, 비밀 |
| `docs/STATUS.md` | 한 일, 남은 일, 막힌 것 |
| `docs/CHANGELOG.md` | 변경 이력 |
| `docs/change-requests/` | 헤드에게 낸 변경 요청 CR-001~005 |
| `docs/rules/` | 헤드가 전달한 업무 규칙(출처 SOURCE.md) |
