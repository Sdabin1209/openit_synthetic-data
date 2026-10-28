# ADR 0013: 잡은 `output.store.kind: http`로 dataset-store에 게시한다

상태: 채택 (2026-10-28, D100, deploy CR-D26)

## 맥락
dataset-store(I2 서버)는 deploy 스택에 올라갔지만 잡(`run`, `import`)은 `file`·`memory`에만 쓸 수 있어 서버의 쓰기 경로를 쓰지 못했다. 이웃 저장소 볼륨 공유는 금지다(D49).

## 결정
`output.store`에 `{"kind": "http", "base_url", "token_env", "timeout"}`을 더한다. 잡은 계약 클라이언트 `boundary_contracts.clients.HttpDatasetStore`로 게시한다(`store/spec.py`). 쓰기 토큰은 설정 파일에 넣지 않고 `token_env`(기본 `DATASET_STORE_WRITE_TOKEN`)로 `read_secret`(D84)이 읽는다: `<이름>_FILE`이 가리키는 파일의 토큰 값 하나(deploy의 `secrets/tokens/dataset-store-write-synthetic-data`), 없으면 환경 변수(개발용). `token`을 설정에 직접 쓰면 설정 오류. `file`·`memory`는 로컬 개발용으로 남긴다.

## 왜
- D49(영역 사이 호출은 HTTP)와 D84(비밀은 파일)를 따른다. 서버가 읽는 `DATASET_STORE_WRITE_TOKENS`(역할=토큰 목록)와 클라이언트가 읽는 토큰 하나는 형식이 달라 이름을 단수형으로 구분했다.
- 기본 timeout 60초: 게시는 수 MB tar 한 번이라는 추정에서 읽기 기본(10초)보다 넉넉하게 잡은 시작값이다. 측정 안 함.
- 잡의 멱등(같은 입력 → 같은 digest → `ALREADY_PUBLISHED`)은 서버의 멱등(같은 hash 200)과 `list_versions`·`get_manifest` 조회로 성립한다(통합 시험으로 확인).

## 검토한 대안과 버리는 이유
- 파일 저장소를 서버 볼륨에 직접 쓰기: D49 위반.
- 토큰을 설정 파일에 허용: D84 위반.

## 결과
얻는 것: 잡이 운영 서버로 게시한다. 감수하는 것: 게시 도중 네트워크 오류는 재시도 가능 오류(종료 코드 75)이고 다시 실행하면 멱등으로 이어진다. 잡 쪽 HTTPS 인증서 설정은 없다(내부망 `http://`, deploy ADR 0032).

## 되돌리는 조건
잡과 서버가 같은 호스트 볼륨을 쓰는 구성으로 바뀌면 불필요(D49를 바꾸는 결정이 먼저 필요).
