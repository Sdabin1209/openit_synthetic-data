# CR-005 DatasetManifest의 created_at이 content_hash에 들어가 재실행마다 해시가 달라진다

- 상태: 헤드에게 요청
- 대상: `DatasetManifest` 해시 규칙, `version` 형식

## 부족한 점
1. 규약상 `content_hash`는 자기 자신을 뺀 전체 객체의 해시라서 `created_at`이 들어간다. 같은 입력과 시드로 다시 돌려도 시각이 다르면 해시가 달라지고, 같은 `(dataset_id, version)`이면 `CONFLICT`가 된다.
2. `version`은 `minLength: 1` 문자열뿐이라 파일 경로로 쓸 때 안전한지 알 수 없다.

## 현재 처리
- 잡은 내용 해시 `dataset_digest`(created_at·version·ext 제외)를 계산해 `ext`에 넣고, `version`을 생략하면 `v<digest 앞 12자>`로 정한다. 같은 digest의 버전이 저장소에 이미 있으면 다시 게시하지 않고 `ALREADY_PUBLISHED`로 끝난다. 설정으로 `created_at`을 고정하면 매니페스트 `content_hash`까지 같다.
- 저장소 구현은 `dataset_id`와 `version`에 Id 규칙(`[A-Za-z0-9][A-Za-z0-9._:-]*`, 128자)을 강제한다(위반은 `INVALID_RECORD`).

## 제안
`version` 형식을 Id 규칙으로 정한다. 재현성 기준(어떤 해시가 같아야 하는가)을 `dataset_digest`와 같은 방식으로 계약에 올릴지 판단해 달라.
