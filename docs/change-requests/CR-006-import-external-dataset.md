# CR-006: 외부(학습 서버) 데이터 게시에 필요한 계약 쪽 보완

상태: 헤드에게 제출. 이 영역이 제안하는 것이며 결정은 헤드 몫이다.

배경: G02 방향(데이터셋 담당이 만든 최종 학습 데이터를 그대로 가져와 검증 후 게시)에 따라 게시기 모드를 만들었다(docs/design.md 부록 A). 아래는 구현 중 계약에 닿아 이 영역이 임의로 정하지 않은 것이다.

1. **`DatasetManifest.question_sets`가 minItems 1인데 외부 데이터에는 문항 세트 출처가 없다.** 학습 서버 행에는 `question_set`이 없다(확인: 계약의 V2_DRAFT 기록과 `ActionExtractionSample`에서 `question_set`이 선택). 현재는 설정에 `ArtifactRef` 하나 이상을 적게 해 두었고, 예시 설정의 값은 자리 표시다. 제안: (a) 외부 데이터용으로 빈 배열을 허용하거나, (b) 데이터셋 담당이 쓴 문항 세트 버전을 알려 주어 설정에 적게 한다. 어느 쪽인지 미정.
2. **v2 의미 검사(targets, next_item, 건너뛰기 순서, save)가 패키지에 없다.** `boundary-contracts/tools/validate_dataset_v2.py`에만 있고 패키지(`boundary_contracts`)로 설치되지 않아 이 영역은 가져다 쓸 수 없고 복사도 하지 않았다. 지금 게시기는 스키마 검증만 한다. 제안: 의미 검사를 패키지 함수로 노출하거나 turn-engine `validate_extraction`으로 제공.
3. **`generator_version`, `turn_engine_version`의 외부 데이터 값.** 현재 `external-import:<source_label>@importer-<버전>`과 설정값을 쓴다. 의미 합의 필요.
4. **`human_review: pending`(미검수) 행의 게시 여부.** 지금은 그대로 싣고 걸러내지 않는다. 걸러야 하면 정책을 알려 달라.
