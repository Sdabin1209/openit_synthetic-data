# ADR 0006: 매니페스트는 불변이고 digest로 멱등하게 게시한다

상태: 채택 (2026-10-28)

근거 출처 요약: 근거: 계약(DatasetManifest, I2의 멱등 규칙)과 canonical 해시(boundary_contracts.canonical)다. 이 영역이 새로 정한 부분은 digest에 무엇을 넣느냐다.

## 맥락
같은 입력을 다시 게시하면 같은 결과이어야 하고(D39 멱등), 한 번 게시한 (dataset_id, version)은 바뀌면 안 된다. created_at이 매번 달라지면 content_hash도 달라져 재실행이 CONFLICT가 난다(점검 지적 SD-4).

## 결정
dataset_digest = 입력 파일 sha256들, 쓴 파일들의 해시, 문항 세트, 계약 버전, 출처 표시(generator_version), turn-engine 버전, pending 정책의 canonical 해시. 지정하지 않은 version은 `v` + digest 앞 12자리다. 이미 같은 version이 있고 digest가 같으면 created_at이 달라도 ALREADY_PUBLISHED로 끝낸다. digest가 다르면 CONFLICT(I2의 규칙).

## 왜 (따른 표준과 근거)
- 내용으로 주소를 정하면 같은 입력이 같은 버전이 된다. 해시는 계약 패키지의 canonical만 쓴다(워크스페이스 규칙, 시험 `test_hashes_only_via_canonical`이 확인).
- 입력 파일을 digest에 넣은 것은 같은 결과를 내는 다른 입력을 구분하기 위해서다.
- 'digest 앞 12자리'의 길이는 근거 기록 없음(기존 생성 경로의 `package.py`가 같은 규칙을 썼고 이유 기록이 없다). 충돌 확률은 계산하지 않았다.

## 검토한 대안과 버리는 이유
- created_at을 digest 입력으로 고정(결정적 시각): 버린다. 의미 없는 시각이 매니페스트에 남는다.
- 항상 새 version(시각 기반): 버린다. 재실행마다 중복 버전이 쌓인다.

## 결과
얻는 것: 재실행이 안전하다. 감수하는 것: 입력이 같고 created_at만 다른 재게시는 첫 게시의 created_at이 남는다.

## 되돌리는 조건
digest 입력 항목이 부족해 다른 내용이 같은 digest가 되는 사례가 나오면 항목을 추가하는 새 ADR을 쓴다.

## 보강 (2026-10-29, 표준성 점검 A10)
`ALREADY_PUBLISHED` 판정이 `import`(version을 지정해도 판정)와 `run`(version을 비웠을 때만 판정)에서 달라, version을 고정하고 created_at만 다른 `run` 재실행이 CONFLICT가 났다. `synthetic_data/publishing.py`의 `publish_idempotent` 한 함수로 통일했다. 기대값의 출처: 계약 I2의 멱등 규칙과 CR-005 결정(digest가 같으면 이미 게시됨). 재현 시험: `tests/test_already_published_unified.py`. digest가 다르면 여전히 저장소가 CONFLICT를 낸다.

## 보강 (2026-10-29, 표준성 점검 A7)
버전 이름을 `v` + digest 앞 12자리(48비트)에서 앞 32자리(128비트)로 바꿨다(헤드 결정표 D106). 12자리는 근거가 없었다(위 '근거 기록 없음'). 기대값의 출처: 생일 한계(n비트 해시는 약 2^(n/2)개에서 충돌이 현실적이다). 이 값은 결정표의 지시이며 이 영역이 측정한 것은 아니다. 감수하는 것: 이미 12자리 이름으로 게시된 버전(예: design.md 부록 B의 `v1309e4c9bea3`)은 그대로 남고, 같은 입력을 지금 다시 게시하면 32자리 이름의 새 버전이 하나 더 생긴다(이름으로 멱등을 판정하므로 옛 12자리 버전을 '이미 게시됨'으로 찾지 못한다). 재현 시험: `tests/test_version_name.py`.

## 갱신 기록
- 3.0.0: 매니페스트와 digest 입력의 `turn_engine_version`은 `action_rules_version`(계약 규칙 데이터의 rules_version)으로 바뀌었다(U300).
