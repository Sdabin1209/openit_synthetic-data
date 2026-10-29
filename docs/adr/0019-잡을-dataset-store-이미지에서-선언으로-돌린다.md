# ADR 0019: 잡(`run`, `import`)을 dataset-store 이미지에서 선언(`io.openit.jobs`)으로 돌린다

상태: 채택 (2026-10-30). 계약 boundary-contracts v2.6.0(`JobsDeclaration`, `SetupEnvReport`), OPEN_GAPS U43.

## 맥락
deploy가 잡을 영역 소스 사본 + 호스트 venv + 영역 폴더 cwd로 실행하고 설정 파일 모양과 패키지 이름을 알고 있었다(구조 규칙 1 위반). 이미지에는 잡을 돌릴 코드(`synthetic_data`)와 의존이 이미 들어 있다(서버와 같은 패키지).

## 결정
- 잡은 dataset-store 이미지에서 돈다. 새 잡 이미지를 만들지 않는다.
- 리포 루트 `jobs.json`이 잡 선언의 정본이고, `scripts/build-image.sh`가 계약 `JobsDeclaration`으로 검증해 라벨 `io.openit.jobs`에 싣는다. 잡 둘: `synthetic-run`, `synthetic-import`. argv는 `python -m synthetic_data <run|import> --config /config/<run|import>.json`. 설정 파일은 deploy가 `config.container_path`에 마운트하고 모양은 계약 스키마(`SyntheticJobConfigRun/Import`)다.
- 비밀 파일: `QUESTION_READER_TOKEN_FILE`, `FAILURE_STORE_TOKEN_FILE`, `DATASET_STORE_WRITE_TOKEN_FILE`(D84). 설정의 `token_env`가 이 이름에서 `_FILE`을 뺀 것이어야 한다(`DATASET_STORE_WRITE_TOKEN`은 http 저장소의 기본값이다).
- 문진 스키마 위치: 이미지가 ENV `SYNTHETIC_SURVEY_SCHEMA_DIR=/app/survey_schema`를 정하고, 이 환경 변수가 있으면 설정의 `survey_schema_dir`보다 우선한다. 왜: 계약 스키마가 `survey_schema_dir`를 필수로 요구하지만 그 값은 이미지의 내부 사항이라 deploy가 알면 안 된다. 설정 쪽을 생략 가능하게 하는 것은 변경 요청이다(`docs/change-requests/CR-009-survey-schema-dir-optional.md`). 그때까지 deploy는 아무 문자열을 적어도 된다(무시된다).
- 잡 선언에 `env`는 싣지 않는다: 잡이 읽는 비밀 아닌 환경 변수를 deploy가 정해 줄 것이 없다(설정은 파일).
- `scripts/setup-env.sh`는 표준 출력 마지막 줄에 `SetupEnvReport`를 낸다(진행은 표준 오류). 실패해도 EXIT 트랩이 `status: fail` 보고를 마지막 줄로 낸다.

## 왜
- 계약이 잡 선언을 라벨로 정했다. deploy가 라벨만 읽으면 영역의 모듈 이름·cwd를 몰라도 된다.
- 같은 이미지: 서버와 잡이 같은 코드·같은 계약 버전이라 버전이 어긋날 수 없다. 이미지를 둘로 나누면 빌드·게시·라벨 검증이 둘이 된다.
- 선언 정본을 파일(`jobs.json`)로 둔 이유: Dockerfile LABEL에 JSON을 적으면 따옴표 이스케이프로 깨지기 쉽고, 빌드 진입점이 계약으로 검증할 수 있다.

## 검토한 대안
- 잡 전용 이미지: 위 이유로 버린다. 이미지 크기 차이는 없다(같은 의존).
- 환경 변수만으로 설정: `question_sets` 같은 구조 값이 환경 변수에 맞지 않고 계약이 설정 파일 스키마를 이미 정했다.

## 결과
얻는 것: `docker run` + 설정 파일 마운트 + 비밀 파일로 deploy가 영역 내부를 모르고 잡을 돌린다. 이 변경으로 실제 이미지에서 `import` 잡이 작은 입력을 게시하는 것을 확인했다(작업 로그 `~/openit-logs/sd43-*`). 감수하는 것: 환경 변수 우선 규칙은 암묵적이다(CR-009로 풀 예정). `run` 잡을 이웃 서비스와 함께 이미지에서 돌려 보지는 않았다.

## 되돌리는 조건
CR-009가 받아들여지면 `SYNTHETIC_SURVEY_SCHEMA_DIR` 우선 규칙을 "설정이 없을 때의 기본값"으로 바꾼다.
