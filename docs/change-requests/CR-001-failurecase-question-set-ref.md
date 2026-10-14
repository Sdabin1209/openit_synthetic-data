# CR-001 FailureCase에 문항 세트 참조와 expected 종류가 없다

- 상태: 헤드에게 요청 (2026-10-15, synthetic-data)
- 대상 계약: `FailureCase` (boundary-contracts, I7)

## 부족한 점
시드 사례를 `ParserSample`/`GeneratorSample`로 만들려면 `question_set`(ArtifactRef)이 필요한데, `FailureCase`에도 비식별 trace에도(`TurnTrace`에는 문항 세트 참조가 없고 `source_release_id`만 있다) 그것이 없다. `source_release_id`로 릴리스를 열어 보려면 I4가 필요한데 이 영역은 I4를 소비하지 않는다. `expected`가 ParserOutput인지 GeneratorOutput인지도 필드로 알 수 없다.

## 현재 우회 (확인한 것)
- 설정 `seeds.question_set_id`로 사람이 문항 세트를 지정하고, 시드 trace의 문항 ID가 그 문항 세트에 모두 있을 때만 쓴다. 아니면 건너뛰고 보고서에 남긴다.
- `expected`가 `ParserOutput` 스키마를 통과하고 trace에 `parser_input`이 있으면 파서 시드, `GeneratorOutput`이고 `generator_input`이 있으면 생성기 시드로 판별한다. 둘 다 아니면 건너뛴다.

## 제안 (미정, 헤드 판단)
`FailureCase`에 선택 필드 추가(MINOR): `question_set: ArtifactRef`, `expected_kind: "PARSER" | "GENERATOR"`.
