# CR-007: v1 생성 경로와 보류 시험 15건의 제거 제안

상태: 헤드에게 제안. 결정은 헤드 몫이며 이 영역은 코드를 지우지 않았다.

사유: G02 방향(데이터셋 담당의 최종 학습 데이터를 그대로 가져와 게시)에서 이 영역은 데이터를 생성하지 않는다. `run` 잡의 생성 경로는 v1 내용을 만들어 합성 샘플이 전부 v2 스키마 위반으로 빠지고(`tests/conftest.py`의 `needs_generator_v2`로 보류한 시험 15건: tests/test_job.py 8, tests/test_units.py 7) 운영에서 쓰이지 않는다.

제안: 다음을 제거하고 `run` 명령은 `import`로 대체한다.
- 코드: `scenario.py`, `plans.py`, `directives.py`, `generators/`, `noise.py`, `labeler.py`, `seeds.py`, `split.py`, `pipeline.py`, `job.py`(의 생성 부분), `bank.py`/`josa.py`/`rng.py`(생성 전용이면), `configs/dev.job.json`, I1·I7 어댑터(`adapters.py`)와 그 통합 시험.
- 시험: 보류 15건, 생성 경로 시험.
- 유지: `store/`(I2), `schemas.py`, `package.py`의 `dumps_line`, `importer.py`.
- 의존: 제거하면 이 영역은 문항 읽기(I1)·실패 사례(I7)를 소비하지 않게 되어 `docs/brief.md`·`boundary.md`의 소비 목록도 바꿔야 한다. 영역 역할 변경이므로 헤드가 브리프를 고쳐 주어야 한다.
- 위험: 시드(실패 사례) 샘플 경로(FAILURE_CASE_SEED)도 함께 사라진다. 이 경로가 계속 필요한지 확인이 필요하다.
