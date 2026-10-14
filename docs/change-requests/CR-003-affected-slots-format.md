# CR-003 ChangeClassification.affected_slots의 문자열 형식이 정해지지 않았다

- 상태: 헤드에게 요청
- 대상 계약: `ChangeClassification.affected_slots` ("문진 스키마 SlotRef를 문자열로 직렬화한 값")

## 부족한 점
`SlotRef`는 `question_id`, `repeat_key`, `slot_id`로 이뤄지는데 직렬화 규칙(구분자, repeat_key가 빈 문자열일 때의 표기)이 없다. 예시 파일에는 `Q3b.frequency`가 있다.

## 현재 처리 (가정)
첫 `.`이나 `:` 앞부분을 문항 ID로 읽는다(`<문항ID>.<슬롯ID>` 또는 `<문항ID>:<repeat_key>.<슬롯ID>`). `REGENERATE_SAMPLES` 때 이 문항들의 샘플만 새로 만든다(설정 `regeneration.mode = affected_only`). 문항 ID에 `.`이나 `:`가 있으면 틀린다.

## 제안
형식을 정의한다. 예: `<question_id>/<repeat_key>/<slot_id>` 또는 JSON 객체 배열.
