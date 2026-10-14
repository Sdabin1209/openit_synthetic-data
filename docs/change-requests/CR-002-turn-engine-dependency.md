# CR-002 turn-engine(I8)을 이 환경에서 쓸 수 없다

- 상태: 헤드에게 요청
- 대상: I8 turn-engine, `DatasetManifest.turn_engine_version`

## 부족한 점
브리프는 정답 구성에 turn-engine의 규칙이 필요하다고 하지만, 설치 방법(Git 태그)과 `ENGINE_VERSION`이 아직 없다. 이 영역은 읽을 수 있는 곳이 정해져 있어 라이브러리를 확인하지 못했다.

## 현재 처리 (확인한 것)
- 파서 라벨은 `docs/rules/utterance_parser.md` 4절 기준을 직접 구현해 만든다(turn-engine 호출 없음).
- 생성기 샘플의 `Directive`는 `docs/rules/dialogue_planner.md`의 형태에 맞춰 손으로 짓는다. 실제 `plan()`이 낸 Directive와 어긋날 수 있다. 샘플 `ext["synthetic-data"].directive_source = "hand-built"`로 표시한다.
- 잡은 `import turn_engine`이 되면 `ENGINE_VERSION`을 매니페스트에 쓰고, 안 되면 설정 `turn_engine_version` 값을 쓴다(필수).

## 요청
(1) turn-engine의 설치 방법과 버전 확정 시점. (2) 생성기 샘플의 Directive를 `plan()` 출력으로 만들 때 필요한 입력(`DialoguePlannerInput`)을 합성해도 되는지, 그 입력의 예시.

## 결정 (헤드)
turn-engine 연동은 원격이 생긴 뒤 다음 구간. 그때까지 파서 라벨은 규칙 4절 직접 구현, Directive는 hand-built 표시 유지. plan() 출력 사용과 DialoguePlannerInput 합성은 승인.
