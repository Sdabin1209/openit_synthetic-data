"""CR-008 스키마 초안을 예시 문서에 대해 검증한다. 사용: .venv/bin/python docs/change-requests/schemas/validate_examples.py
유효해야 할 예시는 통과, 거부되어야 할 예시는 거부되어야 한다. 하나라도 기대와 다르면 종료 코드 1."""
import copy
import json
import sys
from pathlib import Path

from jsonschema import Draft202012Validator, RefResolver

HERE = Path(__file__).resolve().parent
EX = HERE / "examples"
schemas = {p.name: json.loads(p.read_text(encoding="utf-8")) for p in HERE.glob("*.schema.json")}
for n, s in schemas.items():
    Draft202012Validator.check_schema(s)
store = {s["$id"]: s for s in schemas.values()}


def check(schema_name, doc):
    s = schemas[schema_name]
    v = Draft202012Validator(s, resolver=RefResolver(s["$id"], s, store=store))
    return [f"{'/'.join(map(str, e.absolute_path)) or '(root)'}: {e.message[:90]}" for e in v.iter_errors(doc)]


def load(name):
    return json.loads((EX / name).read_text(encoding="utf-8"))


run_cfg, imp_cfg = load("run-config.dev.json"), load("import-config.example.json")
run_http = copy.deepcopy(run_cfg)
run_http["adapters"]["question_reader"] = {"kind": "http", "base_url": "http://question-authoring:8080", "token_env": "QUESTION_READER_TOKEN", "timeout": 10}
run_http["output"]["store"] = {"kind": "http", "base_url": "http://dataset-store:8080", "token_env": "DATASET_STORE_WRITE_TOKEN"}


def mut(doc, fn):
    d = copy.deepcopy(doc)
    fn(d)
    return d


cases = [  # (스키마, 문서 이름, 문서, 유효해야 하는가)
    ("job-config-run.schema.json", "run-config.dev.json (실제 설정)", run_cfg, True),
    ("job-config-run.schema.json", "run adapters kind:http (제안 형식)", run_http, True),
    ("job-config-run.schema.json", "run 오타 최상위 키 regneration", mut(run_cfg, lambda d: d.__setitem__("regneration", {"mode": "full"})), False),
    ("job-config-run.schema.json", "run v1 키 generators", mut(run_cfg, lambda d: d.__setitem__("generators", {})), False),
    ("job-config-run.schema.json", "run 어댑터에 factory와 kind 동시", mut(run_cfg, lambda d: d["adapters"]["question_reader"].update(kind="http", base_url="http://x", token_env="T")), False),
    ("job-config-run.schema.json", "run 저장소 설정에 token 값", mut(run_http, lambda d: d["output"]["store"].update(token="secret")), False),
    ("job-config-import.schema.json", "import-config.example.json (실제 설정)", imp_cfg, True),
    ("job-config-import.schema.json", "import 오타 키 pending_polcy", mut(imp_cfg, lambda d: d.__setitem__("pending_polcy", "report")), False),
    ("job-config-import.schema.json", "import tolerance 오타 키", mut(imp_cfg, lambda d: d["tolerance"].__setitem__("max_invalid_row", 1)), False),
    ("job-config-import.schema.json", "import question_sets content_hash 형식 위반", mut(imp_cfg, lambda d: d["question_sets"][0].__setitem__("content_hash", "abc")), False),
    ("training-data-row.schema.json", "row-lora-a.json", load("row-lora-a.json"), True),
    ("training-data-row.schema.json", "row-lora-b.json", load("row-lora-b.json"), True),
    ("training-data-row.schema.json", "row messages 2개", load("row-invalid-two-messages.json"), False),
    ("training-data-row.schema.json", "row human_review 열거 밖 값", mut(load("row-lora-a.json"), lambda d: d.__setitem__("human_review", "maybe")), False),
    ("job-result.schema.json", "stdout run PUBLISHED/ALREADY", load("stdout-run-published.json"), True),
    ("job-result.schema.json", "stdout run NOTHING_TO_DO", load("stdout-run-nothing-to-do.json"), True),
    ("job-result.schema.json", "stdout import PUBLISHED", load("stdout-import-published.json"), True),
    ("job-result.schema.json", "stdout import REJECTED", load("stdout-import-rejected.json"), True),
    ("job-result.schema.json", "stdout PUBLISHED인데 version null", mut(load("stdout-run-published.json"), lambda d: d.__setitem__("version", None)), False),
    ("job-result.schema.json", "stdout REJECTED인데 사유 없음", mut(load("stdout-import-rejected.json"), lambda d: d.__setitem__("rejected_reasons", [])), False),
    ("job-error.schema.json", "stderr 설정 오류", load("stderr-config-error.json"), True),
    ("job-error.schema.json", "stderr 설정 오류 형식 위반", {"error": "CONFIG"}, False),
    ("import-report.schema.json", "import 보고서 게시", load("import-report.published.json"), True),
    ("import-report.schema.json", "import 보고서 거부", load("import-report.rejected.json"), True),
    ("import-report.schema.json", "import 보고서 deid_attested true", mut(load("import-report.published.json"), lambda d: d.__setitem__("deid_attested", True)), False),
    ("import-report.schema.json", "import 보고서 result와 error 동시", mut(load("import-report.published.json"), lambda d: d.__setitem__("error", {})), False),
    ("run-report.schema.json", "run 보고서", load("run-report.json"), True),
    ("run-report.schema.json", "run 보고서 result만 있고 digest 없음", mut(load("run-report.json"), lambda d: d.pop("dataset_digest")), False),
]
bad = 0
for sname, label, doc, want_valid in cases:
    errs = check(sname, doc)
    ok = (not errs) == want_valid
    bad += not ok
    print(f"{'OK  ' if ok else 'FAIL'} {sname:34s} {'유효 기대' if want_valid else '거부 기대'} -> {'통과' if not errs else '거부'}  {label}" + (f"  [{errs[0]}]" if errs and not want_valid else ""))
    if not ok and errs:
        print("     ", errs[:3])
print(f"합계 {len(cases)}건, 기대와 다름 {bad}건")
sys.exit(1 if bad else 0)
