# CR-009: `survey_schema_dir`을 잡 설정 스키마에서 선택 키로 (SyntheticJobConfigRun / SyntheticJobConfigImport)

상태: 제안 (2026-10-30). 헤드에게.

## 부족한 것
두 설정 스키마가 `survey_schema_dir`를 필수로 요구한다. 그런데 이 값은 이미지 안의 위치로, 잡 선언(`io.openit.jobs`)으로 이미지를 돌리는 deploy가 알면 구조 규칙 1을 어긴다.

## 바꿀 것
- 두 스키마의 `required`에서 `survey_schema_dir`를 뺀다. 생략하면 영역이 이미지의 기본 위치를 쓴다.
- 이 영역의 임시 처리: 환경 변수 `SYNTHETIC_SURVEY_SCHEMA_DIR`(이미지 ENV)가 있으면 설정값보다 우선한다(ADR 0019). 받아들여지면 "설정이 없을 때의 기본값"으로 바꾼다.
- 하위 호환: 키를 계속 받는다. 영향받는 쪽은 설정을 만드는 deploy뿐이고 키를 빼도 통과한다.
