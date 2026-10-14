# CR-004 샘플 종류·합성 출처 정보를 정식 필드로 올릴지

- 상태: 정보 공유 및 판단 요청
- 대상: `ParserSample`, `GeneratorSample`, `DatasetManifest`

## 내용
이 영역은 부가 정보를 `ext["synthetic-data"]`에 넣는다: 샘플의 `kind`(시나리오 종류, 예 ANSWER_NUMERIC), `utterance_generator`/`response_generator`(이름@버전), `directive_source`; 매니페스트의 `dataset_digest`(created_at·version을 뺀 내용 해시), `unseen_eval_files`. 규약상 읽는 영역은 판단에 쓰지 않는다.
model-lab이 종류별 지표를 내거나 평가 파일의 '보지 못한 문항' 여부를 판단에 써야 하면 정식 필드가 필요하다. 지금은 `files[].question_sets`와 파일 경로 규칙(`eval_unseen.jsonl`)으로만 알 수 있다.

## 요청
model-lab의 필요를 확인해 정식 필드(MINOR) 승격 여부를 정해 달라.

## 결정 (헤드)
지금은 ext에 둔다. model-lab이 시작해 필요가 확인되면 승격.
