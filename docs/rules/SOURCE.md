# 업무 규칙 문서

출처: Sdabin1209/HealthCheckSchema의 work/rules/ (헤드가 영역 시작 때 전달, 2026-10-15). 이 영역에 필요한 문서만 담았다.

- 사례 ID(A3, G1, J7 등)와 `../contracts/` 경로는 원본 저장소의 요구사항 케이스와 계약 원본을 가리키며, 이 워크스페이스에는 없다. ID는 규칙의 근거를 구분하는 이름으로만 읽는다.
- 필드의 실제 구조는 `../survey-service/schema/schemas/`(문진 스키마)가 정한다.
- 이 문서는 요구의 원본이다. 이 영역이 구현을 이유로 임의로 바꾸지 않는다. 틀렸거나 부족하면 `docs/change-requests/`에 쓴다.
- 2026-10-28(D99): v1 구조(Parser/Normalizer/Judge/Record Writer/Planner/Generator)를 설명하는 `utterance_parser.md`, `answer_normalizer.md`, `answer_judge.md`, `record_writer.md`, `dialogue_planner.md`, `response_generator.md`, `mapping.md`는 첫 줄에 '보관(v1)'을 표시하고 `manifest.yaml`에서 뺐다(turn-engine과 같은 방식). 이 파일들은 삭제했다(git 이력에 남음, D99 후속).
