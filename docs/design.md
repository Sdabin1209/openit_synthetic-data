# synthetic-data 내부 설계

상태: 첫 구간 구현 완료. 확인한 것은 코드와 시험으로 확인했고, 제안·미정은 따로 표시한다. 브리프의 컴포넌트 표는 참고 시드였고, 경계(I1, I2, I7, I8)만 지켰다.

## 1. 전체 흐름

```
run:    설정(JSON) ─▶ 문항 읽기(I1) ─▶ 시드 수집(I7) ─▶ 시드 샘플 ─▶ 품질 검사 ─▶ 중복 제거 ─▶ 분할(시나리오 단위) ─▶ 패키징 ─▶ 게시(I2)
import: 설정(JSON) + jsonl 6개 ─▶ 행 검증 ─▶ 허용치 판정 ─▶ 패키징 ─▶ 게시(I2)   (부록 A)
```

코드 위치(`synthetic_data/`): `seeds.py`, `seed_samples.py`(시드 샘플 조립), `quality.py`, `split.py`, `package.py`, `context.py`, `job.py`(`run` 잡), `importer.py`(`import` 모드), `store/`(I2 구현), `schemas.py`(검증), `config.py`.

> 2026-10-28(ADR 0010): v1 생성 경로(시나리오 설계, 정답 구성, 발화·문장 생성기, STT 노이즈)를 제거했다. 아래 2, 4, 5, 6절은 제거한 설계의 요약만 남긴 역사 기록이다. 코드는 git 기록(제거 직전 커밋)에 있다.

## 2. 시나리오 설계 (제거됨)

문항 세트마다 시나리오 계획(파서 21종, 생성기 시나리오)을 만들고 시나리오 ID를 문항 세트 버전과 생성기에 무관하게 해시로 정했다. 분할이 시나리오 단위인 이유는 7절 이하에 남아 있다. 제거 사유는 ADR 0010.

## 3. 시드 수집 (`seeds.py`)

I7 `FailureStore`로만 읽는다. `review_status=CONFIRMED`이고 `expected`가 있는 사례만 쓴다(소비자 규칙). `deidentified`가 true가 아니면 `BoundaryError(INVALID_RECORD)`로 **전체 실행을 거부**한다(브리프 5절). 그 밖의 건너뜀(trace 스키마 위반, 계약 버전 불일치, 종류 판별 불가, 문항이 지정 문항 세트에 없음)은 사유와 함께 보고서 `skipped_seeds`에 남는다. FailureCase 1.1의 `question_set`과 `expected_kind`가 있으면 그것을 쓴다(그 문항 세트가 이번 실행의 학습 풀에 있어야 함). 없는 1.0 레코드는 설정 `seeds.question_set_id`와 expected 형태 판별로 폴백한다(CR-001 결정).
시드 샘플은 `origin=FAILURE_CASE_SEED`, `seed_case_id`를 갖고, 원문 정답을 그대로 쓴다. 시드는 사람이 확정한 정답이라 품질 검사에서 문진 스키마 통과만 확인한다.

## 4. 정답 구성 (제거됨)

v1 `ParserOutput` 라벨 기준 구현이었다. v2 정답은 데이터셋 담당의 최종 데이터가 정본이다(ADR 0001).

## 5. 발화·문장 생성기 (제거됨)

교체 가능한 `Protocol` 두 개와 규칙 기반 구현이었다. 제거 사유는 ADR 0010.

## 6. STT 노이즈 주입기 (제거됨)

제거 사유는 ADR 0010. 시드 샘플은 노이즈 변형을 만들지 않는다(원문 위치가 v2 출력에 없다).

## 7. 품질 검사기 (`quality.py`)와 중복 제거

샘플마다 사유 코드를 낸다. 하나라도 있으면 그 샘플을 빼고 `report.json`의 `dropped`에 센다.
- 공통(2.0.0): 경계 스키마(ActionExtractionSample/ResponseSample)만 검사한다. v1의 의미 검사(아래 파서·생성기 항목)는 v1 필드에 묶여 있어 빠졌고, v2 의미 검사는 turn-engine `validate_extraction`(D75) 몫으로 **미정**이다. 아래 파서·생성기 항목은 v1 시점의 설계 기록이다.
- (제거됨, 역사) 파서(합성): 원문이 발화 안에 있다, 값이 원문 안에 있다, 대상 문항·슬롯이 정의에 있다, 의도별 대상·값 규칙(4절 표), 값이 슬롯 정의(선택지·단위·예/아니요)와 모순되지 않는다, 같은 슬롯에 값과 모름·거절이 함께 없다, 빈 발화는 빈 목록.
- (제거됨, 역사) 생성기(합성): 응답 문장의 수가 응답 지시에 있는 것뿐이다, 고정 문장 행동은 재료 그대로, 질문 문장이 포함된다, `is_fallback=false`.
- 중복 제거: (역할, 입력)이 같은 샘플은 하나만 남긴다. 같은 입력에 다른 정답이면(라벨 잡음) 합성끼리는 모두 빼고, 시드가 있으면 시드를 남긴다. 분할 **전에** 하므로 같은 입력이 학습과 평가에 걸치지 않는다.
- **감수 샘플링**: (역할, 종류)마다 해시 순으로 `review.per_kind`개를 `review_sample.jsonl`에 쓴다(사람 감수용, 게시 대상 아님).

## 8. 분할 (`split.py`)

- 분할 단위는 **시나리오**다. 같은 `scenario_id`(노이즈 변형, 같은 시나리오의 문항 세트 버전들)는 같은 쪽에 간다.
- `HELD_OUT_EVAL`로 지정한 문항 세트의 시나리오는 모두 EVAL이다. 이들은 `*/eval_unseen.jsonl`로 따로 쓰고 모든 파일의 `files[].question_sets`에 그 파일의 문항 세트를 적는다(D32 보지 못한 문항 평가). 같은 문항 세트를 학습 풀과 보류에 함께 지정하면 설정 오류.
- 나머지는 해시(시드, 시나리오 ID)를 비율 구간에 대응시킨다. 입력이 늘거나 줄어도 남은 시나리오의 소속은 안 바뀐다.
- **O11 미결정**: 평가셋의 구성과 합성·실제 비율, 지표, 임계치는 정하지 않았다. `split.ratios`는 설정에 반드시 적어야 하며 코드 기본값이 없다. 저장소의 예시 설정 값(0.8/0.1/0.1)은 동작 확인용이다.
- 게시 때 저장소가 한 번 더 확인한다: EVAL의 `scenario_id`가 TRAIN·VALIDATION과 겹치면 `INVALID_RECORD`.

## 9. 패키징 (`package.py`)

`<role>/<split>.jsonl`(lora_a/lora_b, train/validation/eval/eval_unseen). 줄은 키 정렬·구분자 고정 JSON, 샘플 ID 순이라 같은 샘플 집합은 같은 바이트다. 파일 해시는 `canonical.file_hash`, 매니페스트 해시는 `canonical.content_hash`. 매니페스트는 계약 버전, 문항 세트 ArtifactRef 목록, 생성기 버전, 시드 사례 ID, 분할별 파일과 개수, turn-engine 버전을 담는다. 샘플은 쓰기 전에 경계 스키마와 문진 스키마로 검증한다(품질 검사 단계).

## 10. 재현성

- 난수: 전역 `random`을 쓰지 않고 `rng.derive_int(seed, 용도, ...)`로만 파생. 시각·프로세스 상태를 내용에 쓰지 않는다. 딕셔너리는 정렬해서 직렬화한다.
- `dataset_digest`: 파일 해시 목록, 문항 세트, 계약 버전, `generator_version`(게시 도구 식별자), 시드 사례 ID, turn-engine 버전의 `canonical` 해시. `created_at`·`version`·`ext`는 뺀다. 같은 입력과 시드는 같은 digest다(시험: `test_reproducible_*`, 메모리/파일 저장소와 작업 디렉터리가 달라도 같음).
- 매니페스트 `content_hash`에는 `created_at`이 들어간다. 설정에서 고정하면 `content_hash`도 같다. 지정하지 않으면 실행 시각이다. 이 때문에 같은 digest의 버전이 저장소에 이미 있으면 잡이 다시 게시하지 않고 `ALREADY_PUBLISHED`로 끝난다(CR-005).
- `version`을 생략하면 `v<digest 앞 32자>`다.

## 11. 생성 잡과 REGENERATE_SAMPLES

- `python -m synthetic_data run --config <파일>`: 설정 하나로 끝까지 돌고 종료한다(run-once). 새 문항 세트 버전이나 실패 사례가 생길 때 스케줄러가 같은 설정으로 부르면 된다(D39). 어댑터(문항 읽기, 실패 사례 읽기)는 설정의 `factory`(`module:function`)가 만든다. 이웃 영역의 메모리 구현이 나오면 설정만 바꾼다.
- `reviewed_only`(기본 true): 버전을 지정하지 않으면 `latest(..., reviewed_only=True)`, 지정하면 `get_reviews`에서 APPROVED + `clinical_basis_approved`를 확인한다.
- `regeneration.mode = affected_only`: 문항 세트마다 `get_change(ref)`를 읽어 `REGENERATE_SAMPLES`가 있으면 `affected_slots`의 문항으로 제한해 새 데이터셋 버전을 만든다. 없으면 그 문항 세트는 제외하고 모두 제외되면 `NOTHING_TO_DO`. `affected_slots`는 `<question_id>.<slot_id>`이고 마지막 `.`에서 나눈다(CR-003 결정, CONVENTIONS 10절).
- 출력: 작업 디렉터리의 `report.json`(건수, 건너뜀·버린 사유, 결과)과 `review_sample.jsonl`.

## 12. 데이터셋 저장소 (I2, `store/`)

- 파일 구현(`FileDatasetStore`): `<root>/<dataset_id>/<version>/{manifest.json, meta.json, files/}`. 임시 디렉터리에 다 쓰고 디렉터리 이름 바꾸기(rename)로 확정하므로 중간 실패가 보이지 않는다. 게시 순서는 `meta.json`의 seq. O10(저장소의 실제 기술)은 이번 구간에서 "파일 기반, 가볍게"로 정했고 DB 전환은 열려 있다(제안: 규모가 커지면 객체 저장소).
- 메모리 구현(`MemoryDatasetStore`): 같은 베이스 클래스(`store/base.py`)를 쓰므로 검증·오류·멱등성이 같다. 적합성 시험(`tests/test_store_conformance.py`)을 둘 다 통과한다.
- 게시 검증 순서: 매니페스트 스키마 -> pipeline 버전 -> content_hash -> (이미 있으면 멱등/CONFLICT) -> 문진 스키마 정수 버전 -> files 키 일치 -> 파일 복사 후 해시 -> 줄마다 스키마·분할·문항 세트·시드 ID -> sample_count -> 분할 간 시나리오 분리. 어느 하나라도 실패하면 아무것도 저장되지 않는다.
- 읽기: `get_manifest`는 content_hash를 다시 확인하고, `open_file`은 파일 해시를 다시 확인한다(`INTEGRITY_ERROR`).

## 부록 A. 게시기(import) 모드 (G02 방향, 코드: `synthetic_data/importer.py`)

사용자 결정: 데이터셋 담당이 서버에서 만든 최종 학습 데이터를 재생성 없이 가져와 검증하고 게시한다. 정본은 데이터셋 담당의 파이프라인이다. 아래 1~12절의 생성 파이프라인(v1 내용)은 이 모드와 무관하며 쓰지 않는다.

**확인한 것(시험으로)**: 이 리포가 직접 만든 가짜 행으로 아래 동작이 돈다(`tests/test_import.py`).
**실제 데이터로 확인한 것(2026-10-28)**: 데이터셋 담당의 C1 최종 파일 6개(64,459행, 읽기 전용 참조 사본)로 게시기를 처음 돌렸다. 행 형식 추정은 맞았다(키는 human_review, messages, scenario_id, split뿐). 결과 표는 부록 B. **확인하지 못한 것**: 다른 빌드, 의미 검사, 운영 저장소 게시. 아래 '추정' 문장은 처음 근거를 남긴 기록이다. 처음 행 형식은 **추정**이었다. 근거는 `../boundary-contracts/V2_DRAFT.md`가 학습 서버 파일을 읽고 적은 기록(`{human_review, messages[system,user,assistant], scenario_id, split}`, user는 입력 JSON 문자열, assistant는 A는 출력 JSON 문자열/B는 응답 문장)뿐이며, 이 영역은 그 파일을 본 적이 없다. 실제 형식이 다르면 해당 행이 `record_*` 사유로 집계되고 허용치를 넘으면 게시되지 않는다.

흐름: 입력 디렉터리에서 `lora_{a,b}_{train,val,test}.jsonl` 6개를 읽는다(하나라도 없으면 종료 코드 2, 어느 파일인지 적음; train→TRAIN, val→VALIDATION, test→EVAL) -> 파일 바이트의 sha256 -> 행 검증 -> 건수·사유 집계 -> 허용치 판정 -> 통과 행만 `lora_a|b/{train,validation,eval}.jsonl`(샘플 스키마)로 쓰고 DatasetManifest 게시.

행 검증: JSON/구조(`record_blank`, `record_encoding`, `record_json`, `record_shape`, `record_user_json`, `record_assistant_json`) -> user를 `ActionExtractionInput`/`ResponseRequest`, assistant를 `ActionExtraction`/`ResponseText`로(`input_schema`, `output_schema`) -> 샘플로 조립해 `ActionExtractionSample`/`ResponseSample`로(`sample_schema`). `sample_id`는 `as|rs-<분할>-<줄 번호>`(입력이 같으면 같음). `human_review`는 값 그대로 싣는다. 행의 `split` 값 형식을 모르므로 파일 이름으로 분할을 정하고 행의 값은 집계만 한다(`row_split_field_values`).

허용치: 설정 `tolerance.max_invalid_rows`와 `max_invalid_rate`를 둘 다 지켜야 한다(예시 값 0 = 하나라도 틀리면 게시 안 함). 그 밖에 총 0행, 통과 행이 0건인 파일, 분할 사이 `scenario_id` 겹침도 게시 안 함. 게시하지 않으면 상태 `REJECTED`, 종료 코드 4, 보고서 `import_report.json`에 파일별·사유별 건수와 사유별 첫 줄 번호를 남긴다. 행 내용은 보고서에 넣지 않는다. 허용치 안에서 게시해도 버린 건수와 사유는 매니페스트 `ext["synthetic-data"].import`에 남는다.

멱등: 같은 입력 바이트와 설정이면 같은 `dataset_digest`와 `version`이고 이미 있으면 `ALREADY_PUBLISHED`(`created_at`을 고정하면 content_hash도 같음).

점검 반영(2026-10-28; 점검 문서 head/docs/audit/...는 이 영역 규칙상 읽지 않았고 코디네이터가 전한 항목 설명만 근거로 했다):
- 중복 발화(SD-3): 정규화한 발화(NFKC, 소문자, 공백·구두점·기호 제거)+맥락(A는 question_id, B는 action·다음 문항) 해시가 TRAIN/VALIDATION/EVAL 사이에 겹치면 건수를 세어 `tolerance.max_cross_split_duplicate_inputs`(기본 0)를 넘으면 거부. 발화 본문은 보고서에 없다.
- 값 비노출(SD-1): 거부 사유는 `<단계>: <경로>#<스키마 키워드>` 코드뿐. 보고서·매니페스트·결과·오류 레코드에 입력 값이 없다(행의 `split` 필드도 값 없이 개수만).
- 멱등(SD-4): version을 지정해도 입력 digest가 같으면 `created_at`이 달라도 ALREADY_PUBLISHED. digest가 다르면 CONFLICT.
- pending(SD-2): `pending_policy` = report(기본, 싣고 건수만 보고) / exclude / reject. **정책 값은 사용자 결정이며 기본값은 결정이 아니다.** `origin`은 SYNTHETIC 고정(입력에 정보 없음, 가정)이며 설정 `origin`은 SYNTHETIC만 받는다. 보고서·매니페스트에 `origin_assumed`, `deid_attested: false`(비식별 확인은 게시기가 하지 않음).
- 의심 패턴: 이메일·휴대전화·유선전화·주민번호 형태를 행 수로만 센다(`pii_suspect`). 수량자에 상한을 둔 정규식과 행당 20,000자 제한으로 ReDoS를 막았다(시험 있음). 기본은 경고, `tolerance.max_pii_suspect_rows`를 정하면 거부. 비식별 확인이 아니다.
- 의미 검사(SD-7): 수행하지 않음(`semantic_checks.performed=false`). 요청 CR-006. 생성 경로 제거 제안 CR-007.

미정/한계: 의미 검사 미수행, 문항 세트 출처 설정 의존, `pending` 행 처리 정책 -> `change-requests/CR-006-import-external-dataset.md`.

## 부록 B. 실제 데이터 첫 실행 결과 (실측(2026-10-28, C1 빌드 2026-10-27, 읽기 전용 참조 사본 6개 64,459행))

입력: `reference/openit-server/data/final/lora_{a,b}_{train,val,test}.jsonl`(읽기 전용, 리포 밖). 게시 결과 저장소와 보고서는 리포 밖 임시 폴더에 두고 지웠다. 설정의 `question_sets`는 자리 표시 해시를 썼다(CR-006 미해결).

| 항목 | 값 (분모) |
|---|---|
| 행 수 | A: train 25,700 / val 3,221 / test 3,249, B: train 25,794 / val 3,233 / test 3,262, 합 64,459 |
| 스키마 검증 통과/실패 | 64,459 / 0 (분모 64,459, 사유별 실패 없음) |
| 행 키 | 전 행이 human_review, messages, scenario_id, split 네 키뿐 |
| 행의 split 값 | 파일마다 단일 값(train/val/test)이고 파일 이름과 일치 |
| human_review 분포 | auto_only 64,459 (pending 0) |
| pii_suspect (이메일·전화·주민번호 형태) | 0행 |
| 같은 발화+문항 중복(참고) | A: EVAL~TRAIN 3, TRAIN~VALIDATION 5, EVAL~VALIDATION 0 / B: 0. 모두 state가 달라 입력·정답이 달랐다 |
| 같은 입력 중복(허용치 판정) | 세 쌍 모두 0 -> 기본 허용치 0으로 통과 |
| 게시 | PUBLISHED, version `v1309e4c9bea3`, dataset_digest `sha256:1309e4c9bea39ea0f4ef5c42bebc90fce1f7be7676e7e0cf0378144e52ba371b`, 매니페스트 content_hash `sha256:a41e16923ddc5e1fe4ac3a0101603c573ac2860d7dd762e765d29d13acde1d79` |
| 입력 sha256 | 보고서 `inputs`와 매니페스트 ext에 6개 기록(예: lora_a_train `sha256:94d96013...ca122c`) |
| 재실행(created_at만 다르게) | ALREADY_PUBLISHED, 같은 content_hash |
| 소요 | 약 30초(1회) |

처음 정의(발화+문항)의 중복 키로는 8건이 걸려 기본 허용치 0에서 REJECTED였고, 원인 확인 뒤 엄격 키로 바꿨다(ADR 0004). 의미 검사는 하지 않았다(`semantic_checks.performed=false`). 문항 세트는 자리 표시라 이 게시 결과는 운영용이 아니다.
