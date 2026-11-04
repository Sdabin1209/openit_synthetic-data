# ADR 0025: dataset-store 데이터를 restic으로 백업·복구하는 잡 둘(dataset-backup, dataset-restore)

상태: 채택 (2026-11-05). 계약 boundary-contracts v3.4.16(`JobsDeclaration.needs`, `CommonEnv` OPENIT_BACKUP_*, `BackupJobResult`, `Exposure.egress external:backup`), RUNTIME R10.1·R1.8·R9.2, DATA_OWNERSHIP 백업 행.

## 맥락
dataset-store의 데이터(볼륨 `datasets-data`, 컨테이너 경로 `DATASET_STORE_ROOT` 기본 `/data`)는 불변 파일이다. DATA_OWNERSHIP은 백업 묶음의 내용·암호·보존·복구를 그 데이터의 주인 영역이 맡게 한다. 이 영역에는 백업·복구 잡이 없었다.

## 결정
- 잡 둘을 dataset-store 이미지의 `io.openit.jobs`로 낸다(ADR 0019와 같은 방식): `dataset-backup`(`python -m synthetic_data backup`), `dataset-restore`(`... restore`). 둘 다 `needs: ["datasets-data"]`, `secret_files: [OPENIT_BACKUP_CREDENTIALS_FILE, OPENIT_BACKUP_REPO_PASSWORD_FILE]`, `env: [OPENIT_BACKUP_URL, OPENIT_EGRESS_PROXY]`, 설정 파일 없음. 노출 선언 `egress`에 `external:backup`을 더한다.
- 도구는 restic이다. 저장소는 `rest:` + `OPENIT_BACKUP_URL`(restic REST). 자격은 환경 변수 `RESTIC_REST_USERNAME/PASSWORD`로 자식 프로세스에만 준다(URL에 넣으면 오류 메시지에 섞인다). 암호는 값이 아니라 `RESTIC_PASSWORD_FILE`(파일 경로)로 restic이 직접 읽는다. 영역 밖 호출은 `HTTPS_PROXY=OPENIT_EGRESS_PROXY`(자기 게이트웨이 CONNECT, R1.8), 신뢰 루트는 `SSL_CERT_FILE`(IN-ROOT).
- 백업은 `DATASET_STORE_ROOT`를 담고 요청 임시 폴더 `.tmp`는 뺀다(서비스가 시작할 때 지우는 값). 첫 백업이 저장소를 만든다(`restic init`). 복구는 이 경로의 최신 스냅숏을 `--target /`로 풀어 원래 자리로 돌린다. 백업에 없던 파일은 지우지 않는다.
- 결과는 표준 출력 마지막 줄 `BackupJobResult`(내보내기 전에 계약으로 자기 검사). 종료 코드: 0 ok, 75 재시도 가능(저장소에 닿지 못함·잠금·일부 파일 읽기 실패), 1 그 밖의 실패(암호 틀림 PERMISSION_DENIED, 복구할 스냅숏 없음 NOT_FOUND, restic 없음), 2 설정 오류. 오류 메시지는 고정 문장이고 restic의 stderr(주소·자격이 섞일 수 있다)는 버린다.
- restic은 이미지에 Debian 공식 패키지(`apt`, 버전 `0.18.0-1+b4` 고정, Dockerfile `RESTIC_DEB_VERSION`)로 설치한다.

## 왜
- restic REST와 환경 변수 이름은 계약이 정했다(CommonEnv, R10.1). 데이터가 파일 트리라 DB 덤프가 없고, 파일 단위 중복 제거·암호화·스냅숏이 있는 restic이 계약의 "restic 저장소 암호"와 맞다.
- 시간 상한: 잡 선언 `timeout_seconds`는 **1800초**다. 이 값은 **측정하지 않았다**. 근거는 (1) 기본 상한 3600초(R9.3, 이것도 시작값)보다 짧게 해 주기보다 길어지지 않게 하는 것, (2) 이 영역의 다른 두 잡이 같은 1800초라는 것뿐이다. 데이터 크기가 자라면 측정으로 바꾼다.
- 저장소 확인 상한 `PROBE_TIMEOUT_SECONDS = 30`도 측정하지 않은 시작값이다. 왜 있나: restic은 저장소에 닿지 못하면 약 15분 동안 내부에서 다시 시도하고(0.18에는 이를 줄이는 옵션이 없다) 그동안 아무것도 내지 않는다. 그러면 deploy가 1800초 상한으로 멈출 때까지 "75(재시도 가능)"가 아니라 시간 초과 실패로 보인다. 첫 확인(저장소 설정 하나를 읽는 `cat config`, 복구는 `snapshots`)에만 상한을 두고 넘기면 75를 낸다. 이후 단계(실제 전송)에는 상한을 두지 않는다. 그 구간의 상한은 잡 선언이 정본이다.
- 잡 선언에 `config`가 없는 이유: 입력이 전부 CommonEnv 이름이라 deploy가 값을 주면 끝난다(설정 파일 모양을 deploy가 알지 않게).

## 검토한 대안
- 서비스를 멈추고 볼륨을 복사: 계약이 정한 저장소(restic REST)와 암호화·중복 제거가 없다. 버린다.
- 파이썬으로 tar를 만들어 REST에 직접 올리기: restic 저장소 형식을 다시 만들게 된다. 버린다.
- 복구가 백업에 없는 파일을 지우기(동기화): 복구 실수가 데이터를 더 잃게 한다. 데이터가 불변 파일이라 남는 파일은 해롭지 않다. 버린다.
- restic 전체를 시간 상한 없이 두기: 닿지 못함이 시간 초과로 보인다. 위 이유로 첫 확인에만 상한을 둔다.

## 결과
얻는 것: deploy가 라벨만 읽고 백업·복구를 주기로 돌릴 수 있다. 백업→복구 왕복과 변이(파일 변경·삭제·폴더 삭제, 백업 뒤 생긴 파일)를 실제 restic·restic-rest-server로 시험한다(`tests/test_backup_job.py`, 두 도구는 `scripts/fetch-test-tools.sh`가 Debian 공식 패키지에서 받는다. 없으면 왕복 시험은 건너뛴다).
감수하는 것: 이미지가 restic 때문에 커진다. 시험 서버는 `--no-auth`라 HTTP 기본 인증 경로는 실제 서버로 시험하지 않았다(자격을 환경 변수로 넘기는 연결만 단위로 본다). TLS·게이트웨이 CONNECT·실제 platform 백업 저장소와의 연동은 이 영역에서 돌리지 않았다(서비스끼리 도는 시험은 deploy). 보존 기간·정리(`forget`)는 정하지 않았다: 계약 R10.1이 보존을 그 영역의 ADR로 맡겼지만 이 결정에 포함하지 않았고 미정이다.

## 되돌리는 조건
데이터 크기·전송 시간을 측정해 두 상한이 맞지 않으면 값을 바꾼다. 백업 저장소 프로토콜이 계약에서 바뀌면 새 ADR로 대체한다.
