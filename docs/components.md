# 컴포넌트 (D117, 구조 규칙 6개)

이 영역의 일을 업무 단계로 나눈 표다. 입력은 계약(boundary-contracts v3.1.2)과 `docs/brief.md`에서 받는다: 잡 설정(SyntheticJobConfigRun/Import)·학습 데이터 jsonl·문항 세트(I1)·실패 사례(I7)를 받고, 데이터셋(I2)·잡 결과·보고서를 낸다. 컴포넌트마다 입력 스키마와 출력 스키마가 `schemas/<타입>.schema.json`에 있고(코드 타입은 `synthetic_data/types/`에서 생성), 컴포넌트는 다른 컴포넌트를 import하지 않는다. 컴포넌트끼리는 `synthetic_data/wiring/`가 잇는다. 기존 코드는 정의의 근거가 아니라 빠진 업무 규칙과 거부 조건을 찾는 대조 자료로만 썼다.

컴포넌트는 입력을 스키마로 검사하고(DESIGN.md 5절) 출력을 내기 전에 스키마로 검사한다. 저장소(디스크·메모리)나 이웃(HTTP) 같은 바깥 자원은 wiring이 주입한다(`publish_decision`의 `store`, `question_set_admit`의 `survey_check`, `link_*`의 클라이언트).

## 게시기(import): 학습 데이터 jsonl 6개 검증·게시

| 컴포넌트 | 파일 | 입력 타입 | 출력 타입 | 하는 일 |
|---|---|---|---|---|
| 설정 정규화(게시기) | `components/import_plan.py` | ImportConfigInput | ImportPlan | 설정을 계약 SyntheticJobConfigImport로 검사하고 기본값을 채워(가장 엄격한 쪽) 실행 계획을 만든다 |
| 입력 읽기 | `components/import_source.py` | ImportSourceRequest | ImportSource | 입력 디렉터리의 jsonl 6개를 읽어 줄과 파일 해시를 낸다(역할·분할은 파일 이름이 정한다) |
| 줄 검증 | `components/import_row_check.py` | RawRow | RowVerdict | 한 줄을 3단계(줄 모양 TrainingDataRow, 입출력 내용, 샘플 조립)로 검증하고 통과하면 샘플을, 아니면 사유 코드를 낸다 |
| 개인정보 의심 검사 | `components/pii_scan.py` | PiiScanInput | PiiScanResult | 샘플·시드의 input/expected에서 이메일·전화·주민번호 형식 패턴을 찾는다(비식별 확인이 아니다). 게시기와 시드 잡이 같이 쓴다 |
| 집계 | `components/import_tally.py` | ImportTallyInput | ImportTally | 줄 판정을 파일·전체로 모아 건수·사유별 개수·human_review 분포·의심 행 수를 낸다 |
| 허용치 판정 | `components/import_judge.py` | ImportJudgeInput | ImportJudgement | 실패 건수·비율, 빈 파일, pending 정책, 개인정보 의심 허용치를 판정해 거부 사유를 낸다 |
| pending 제외 | `components/pending_filter.py` | PendingFilterInput | PendingFilterResult | pending_policy=exclude일 때 human_review가 pending인 행을 걷어낸다 |
| 겹침 판정 | `components/import_overlap.py` | OverlapInput | OverlapOutcome | 분할 사이 같은 입력·같은 scenario_id를 찾아 평가 누수를 거부한다 |
| 패키징(게시기) | `components/import_package.py` | ImportPackageInput | PackagedDataset | 통과한 샘플을 JSONL로 쓰고 DatasetManifest(digest, version, 해시)를 만든다 |
| 보고서(게시기) | `components/import_report.py` | ImportReportInput | ReportDocument | 계약 SyntheticImportReport를 조립한다(값 없이 건수와 사유 코드만) |

## 시드 잡(run): 확정된 실패 사례를 시드 샘플로 게시

| 컴포넌트 | 파일 | 입력 타입 | 출력 타입 | 하는 일 |
|---|---|---|---|---|
| 설정 정규화(시드 잡) | `components/run_plan.py` | RunConfigInput | RunPlan | 설정을 계약 SyntheticJobConfigRun으로 검사하고 불변식(분할 비율 합>0, 시드면 failure_store 필요)과 기본값을 계획에 담는다 |
| 문항 읽기 | `components/link_question_reader.py` | QuestionSetQuery | QuestionSetFetch | I1 계약 클라이언트로 문항 세트·검수 결과·변경 분류를 읽는다(보내는 쪽) |
| 문항 세트 판정 | `components/question_set_admit.py` | QuestionSetAdmitInput | QuestionSetAdmission | 검수 승인·QuestionBank 해시·문진 스키마·REGENERATE_SAMPLES를 보고 쓸지(ADMITTED), 건너뛸지, 거부할지 낸다 |
| 실패 사례 읽기 | `components/link_failure_reader.py` | FailureReadRequest | ConfirmedCases | I7 계약 클라이언트로 CONFIRMED의 최신 버전을 쪽 단위로 모두 읽는다(보내는 쪽) |
| 시드 수집 | `components/seed_collect.py` | SeedCollectInput | SeedCollection | 비식별 사례만 받아(입력 스키마가 거부) 쓸 수 있는 시드를 고르고 건너뛴 사유와 모르는 필드 메모를 낸다 |
| 시드 개인정보 관문 | `components/seed_pii_gate.py` | SeedPiiGateInput | SeedPiiGateResult | 의심 패턴이 있는 시드 수가 허용치를 넘으면 거부한다(기본 0건) |
| 시드 짝짓기 | `components/seed_pairing.py` | SeedPairingInput | SeedPairing | 시드를 학습 풀 문항 세트에 짝짓는다(1.1은 참조, 1.0은 설정의 문항 세트) |
| 시드 샘플 조립 | `components/seed_assemble.py` | SeedAssembleInput | SeedAssembly | 시드를 FAILURE_CASE_SEED 샘플 레코드로 만들고 문항 세트에 없는 문항의 시드를 건너뛴다 |
| 품질 검사 | `components/sample_quality.py` | QualityInput | QualityVerdict | 샘플이 계약 샘플 스키마를 통과하는지 본다(의미 검사는 미수행, CR-006) |
| 중복 정리 | `components/sample_dedupe.py` | DedupeInput | DedupeResult | 같은 입력의 중복을 정리한다(사람이 확정한 정답이 이기고 정답이 갈리면 전부 뺀다) |
| 분할 | `components/split_assign.py` | SplitInput | SplitResult | 시나리오 단위로 TRAIN/VALIDATION/EVAL을 정한다(보지 못한 문항 세트는 전부 EVAL) |
| 감수 샘플링 | `components/review_sample.py` | ReviewSampleInput | ReviewSample | (역할, 종류)마다 해시 순으로 per_kind개를 뽑아 사람 감수용 목록을 만든다 |
| 패키징(시드 잡) | `components/run_package.py` | RunPackageInput | PackagedDataset | 샘플을 파일(역할·분할, 보지 못한 문항 세트는 eval_unseen)로 묶고 DatasetManifest를 만든다 |
| 보고서(시드 잡) | `components/run_report.py` | RunReportInput | ReportDocument | 계약 SyntheticRunReport를 조립한다(counts는 샘플에서 센다) |

## 두 잡이 같이 쓰는 것

| 컴포넌트 | 파일 | 입력 타입 | 출력 타입 | 하는 일 |
|---|---|---|---|---|
| 게시 판정 | `components/publish_decision.py` | PublishDecisionInput | PublishOutcome | 같은 (dataset_id, version)에 digest가 같으면 ALREADY_PUBLISHED, 아니면 게시한다(저장소는 주입) |
| 잡 출력 | `components/job_output.py` | JobOutputInput | JobOutputLine | 표준 출력의 결과 한 줄과 표준 오류의 설정 오류 한 줄을 계약(SyntheticJobResult/Error)으로 검사해 만든다 |

## 저장소와 통신

| 컴포넌트 | 파일 | 입력 타입 | 출력 타입 | 하는 일 |
|---|---|---|---|---|
| 데이터셋 저장소 | `components/dataset_store.py` | PublishRequest, ManifestRequest, VersionsRequest, FileRequest | 계약 DatasetManifest / 버전 목록 / 파일 바이트 | I2의 파일·메모리 구현. 게시 검증(해시·줄 수·분할·시나리오 겹침·멱등/충돌)과 불변 저장 |
| 게시 보내기 | `components/link_dataset_publish.py` | HttpStoreSpec | 계약 DatasetStore 클라이언트 | dataset-store 서버로 게시·조회하는 계약 클라이언트(보내는 쪽). 쓰기 토큰은 파일로 받는다(D84) |
| dataset-store 받기 | `components/link_dataset_store_server.py` | 계약 I2 요청(HTTP.md) | 계약 DatasetManifest 응답 | I2 서버 면(받는 쪽). openit_link.App/Route 위에 경로 표와 처리 함수, 인증 실패 제한·동시 상한·디스크 여유·종료 절차 |

## 컴포넌트가 아닌 것

| 위치 | 하는 일 |
|---|---|
| `synthetic_data/__main__.py`, `service/__main__.py` | 진입점 |
| `synthetic_data/config.py` | 설정 파일 읽기, 환경 변수에서 값 가져오기 |
| `synthetic_data/adapters/__init__.py` | 공개 진입점(`synthetic_data.adapters:http_question_reader`가 배포 설정에 있다, ADR 0022). 로직 없음 |
| `synthetic_data/wiring/` | 컴포넌트 연결(`import_job.py`, `run_job.py`), 주입(`stores.py`, `survey.py`, `publishing.py`), 설정→계획(`plans.py`), 서비스 기동(`service.py`) |
| `synthetic_data/types/` | `schemas/`에서 생성(손으로 고치지 않는다) |
