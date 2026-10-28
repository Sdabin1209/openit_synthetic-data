"""valid 예시 중 '코드가 낸 값'을 실제로 돌려 만든다(재현용). 사용(worktree 루트에서):
  PYTHONPATH=tests .venv/bin/python docs/change-requests/contract-ready/make_examples.py
설정 두 개는 configs/의 실제 파일을 복사하고, 결과(stdout, report.json, import_report.json, stderr)는 이 영역 코드를 임시 폴더에서 돌려 얻는다.
입력 행은 tests/test_import.py의 가짜 행이다(실제 학습 데이터가 아니다)."""
import contextlib
import io
import json
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
OUT = Path(__file__).resolve().parent / "examples" / "valid"
sys.path[:0] = [str(ROOT), str(ROOT / "tests")]

import doubles                                                         # noqa: E402
from boundary_contracts.errors import BoundaryError                    # noqa: E402
from conftest import SURVEY_DIR                                        # noqa: E402
from synthetic_data.__main__ import main                               # noqa: E402
from synthetic_data.importer import run_import                         # noqa: E402
from synthetic_data.job import run_job                                 # noqa: E402
from synthetic_data.config import parse_config                         # noqa: E402
from synthetic_data.store import MemoryDatasetStore                    # noqa: E402
from synthetic_data.schemas import Validators                          # noqa: E402
from test_import import cfg_for, write_input, QS, row, set_utt         # noqa: E402


def dump(name, obj):
    (OUT / name).write_text(json.dumps(obj, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def cli(args):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = main(args)
    return code, out.getvalue(), err.getvalue()


OUT.mkdir(parents=True, exist_ok=True)
for src, dst in (("configs/dev.job.json", "SyntheticJobConfigRun.json"), ("configs/import.example.json", "SyntheticJobConfigImport.json")):
    shutil.copy(ROOT / src, OUT / dst)

tmp = Path(tempfile.mkdtemp(prefix="sd-contract-ready-"))
# run: configs/dev.job.json과 같되 경로만 임시 폴더. 이웃은 tests/doubles.py 대역(PYTHONPATH=tests)
cfg = json.loads((ROOT / "configs/dev.job.json").read_text(encoding="utf-8"))
cfg.update(survey_schema_dir=str(SURVEY_DIR))
cfg["output"] = {"work_dir": str(tmp / "work"), "store": {"kind": "file", "root": str(tmp / "store")}}
(tmp / "run.json").write_text(json.dumps(cfg), encoding="utf-8")
code, out, _ = cli(["run", "--config", str(tmp / "run.json")]); assert code == 0
dump("SyntheticJobResult.run-published.json", json.loads(out))
dump("SyntheticRunReport.json", json.loads((tmp / "work/report.json").read_text(encoding="utf-8")))
code, out, _ = cli(["run", "--config", str(tmp / "run.json"), "--created-at", "2026-10-29T00:00:00Z"]); assert code == 0
dump("SyntheticJobResult.run-already-published.json", json.loads(out))
nothing = dict(cfg, seeds={"enabled": False}); nothing["output"] = {"work_dir": str(tmp / "w2"), "store": {"kind": "memory"}}
(tmp / "nothing.json").write_text(json.dumps(nothing), encoding="utf-8")
code, out, _ = cli(["run", "--config", str(tmp / "nothing.json")]); assert code == 0
dump("SyntheticJobResult.run-nothing-to-do.json", json.loads(out))
# run 보고서의 error: 비식별되지 않은 시드 사례를 받으면 실행 거부(INVALID_RECORD)
bad_cfg = parse_config(dict(cfg, output={"work_dir": str(tmp / "w3"), "store": {"kind": "memory"}}), tmp)
fs = doubles.FakeFailureStore(); fs.add(doubles.failure_case("fc-x", "tr-x", doubles.a_expected(), expected_kind="LORA_A", reviewed_input=doubles.a_input(), deidentified=False))
try:
    run_job(bad_cfg, question_reader=doubles.make_question_reader(), failure_store=fs, store=MemoryDatasetStore(Validators(SURVEY_DIR)), validators=Validators(SURVEY_DIR))
except BoundaryError:
    pass
dump("SyntheticRunReport.boundary-error.json", json.loads((tmp / "w3/report.json").read_text(encoding="utf-8")))
# 설정 오류(종료 코드 2)의 stderr
(tmp / "badcfg.json").write_text(json.dumps(dict(cfg, regneration={"mode": "full"})), encoding="utf-8")
code, _, err = cli(["run", "--config", str(tmp / "badcfg.json")]); assert code == 2
dump("SyntheticJobError.json", json.loads(err))

# import: 가짜 행 6개 파일
imp = json.loads((ROOT / "configs/import.example.json").read_text(encoding="utf-8"))
imp.update(input_dir=str(tmp / "in"), survey_schema_dir=str(SURVEY_DIR), created_at="2026-10-29T00:00:00Z")
imp["output"] = {"work_dir": str(tmp / "iw"), "store": {"kind": "file", "root": str(tmp / "istore")}}
write_input(tmp / "in")
(tmp / "imp.json").write_text(json.dumps(imp), encoding="utf-8")
code, out, _ = cli(["import", "--config", str(tmp / "imp.json")]); assert code == 0
dump("SyntheticJobResult.import-published.json", json.loads(out))
dump("SyntheticImportReport.published.json", json.loads((tmp / "iw/import_report.json").read_text(encoding="utf-8")))
write_input(tmp / "in2", mutate=lambda n, ls: [set_utt(ls[0], "연락처는 010-1234-5678 입니다")] + ls[1:] if n == "lora_a_train.jsonl" else ls)
imp2 = dict(imp, input_dir=str(tmp / "in2")); imp2["output"] = {"work_dir": str(tmp / "iw2"), "store": {"kind": "memory"}}
(tmp / "imp2.json").write_text(json.dumps(imp2), encoding="utf-8")
code, out, _ = cli(["import", "--config", str(tmp / "imp2.json")]); assert code == 4
dump("SyntheticJobResult.import-rejected.json", json.loads(out))
dump("SyntheticImportReport.rejected.json", json.loads((tmp / "iw2/import_report.json").read_text(encoding="utf-8")))
# import 보고서의 error: 저장소가 게시를 못 받는 경우(UNAVAILABLE)
class Down(MemoryDatasetStore):
    def publish(self, manifest, files):
        raise BoundaryError("UNAVAILABLE", "저장소에 연결할 수 없다")
v = Validators(SURVEY_DIR)
try:
    run_import(cfg_for(tmp / "x", input_dir=str(tmp / "in"), created_at="2026-10-29T00:00:00Z", output={"work_dir": str(tmp / "iw3"), "store": {"kind": "memory"}}),
               store=Down(v), validators=v)
except BoundaryError:
    pass
dump("SyntheticImportReport.boundary-error.json", json.loads((tmp / "iw3/import_report.json").read_text(encoding="utf-8")))
# SyntheticDefs: 저장소·출력 정의 (configs/dev.job.json의 output, 운영 http 형식은 ADR 0013 설정 예)
dump("SyntheticDefs.Output.json", json.loads((ROOT / "configs/dev.job.json").read_text(encoding="utf-8"))["output"])
dump("SyntheticDefs.Store.file.json", {"kind": "file", "root": "../work/store"})
dump("SyntheticDefs.Store.memory.json", {"kind": "memory"})
dump("SyntheticDefs.Store.http.json", {"kind": "http", "base_url": "http://dataset-store:8080", "token_env": "DATASET_STORE_WRITE_TOKEN", "timeout": 60})
shutil.rmtree(tmp, ignore_errors=True)

# 거부되어야 하는 예시: 유효 예시를 한 군데만 깨뜨려 만든다(깨뜨린 곳은 파일 이름에 적는다)
BAD = OUT.parent / "invalid"
BAD.mkdir(parents=True, exist_ok=True)


def ld(n):
    return json.loads((OUT / n).read_text(encoding="utf-8"))


def bad(name, doc):
    (BAD / name).write_text(json.dumps(doc, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def mut(n, fn):
    d = ld(n)
    fn(d)
    return d


bad("SyntheticJobConfigRun.unknown-top-key.json", mut("SyntheticJobConfigRun.json", lambda d: d.__setitem__("regneration", {"mode": "full"})))
bad("SyntheticJobConfigRun.v1-key-generators.json", mut("SyntheticJobConfigRun.json", lambda d: d.__setitem__("generators", {})))
bad("SyntheticJobConfigRun.seed-is-bool.json", mut("SyntheticJobConfigRun.json", lambda d: d.__setitem__("seed", True)))
bad("SyntheticJobConfigRun.store-token-value.json", mut("SyntheticJobConfigRun.json", lambda d: d["output"].__setitem__("store", {"kind": "http", "base_url": "http://x", "token": "secret"})))
bad("SyntheticJobConfigRun.negative-ratio.json", mut("SyntheticJobConfigRun.json", lambda d: d["split"]["ratios"].__setitem__("TRAIN", -1)))
bad("SyntheticJobConfigImport.unknown-top-key.json", mut("SyntheticJobConfigImport.json", lambda d: d.__setitem__("pending_polcy", "report")))
bad("SyntheticJobConfigImport.tolerance-typo.json", mut("SyntheticJobConfigImport.json", lambda d: d["tolerance"].__setitem__("max_invalid_row", 1)))
bad("SyntheticJobConfigImport.question-set-hash-format.json", mut("SyntheticJobConfigImport.json", lambda d: d["question_sets"][0].__setitem__("content_hash", "abc")))
bad("SyntheticJobConfigImport.origin-not-synthetic.json", mut("SyntheticJobConfigImport.json", lambda d: d.__setitem__("origin", "FAILURE_CASE_SEED")))
bad("SyntheticJobResult.published-without-version.json", mut("SyntheticJobResult.run-published.json", lambda d: d.__setitem__("version", None)))
bad("SyntheticJobResult.rejected-without-reasons.json", mut("SyntheticJobResult.import-rejected.json", lambda d: d.__setitem__("rejected_reasons", [])))
bad("SyntheticJobResult.unknown-status.json", mut("SyntheticJobResult.run-published.json", lambda d: d.__setitem__("status", "DONE")))
bad("SyntheticJobError.missing-message.json", {"error": "CONFIG"})
bad("SyntheticImportReport.deid-attested-true.json", mut("SyntheticImportReport.published.json", lambda d: d.__setitem__("deid_attested", True)))
bad("SyntheticImportReport.result-and-error.json", mut("SyntheticImportReport.published.json", lambda d: d.__setitem__("error", ld("SyntheticImportReport.boundary-error.json")["error"])))
bad("SyntheticImportReport.error-not-boundary-error.json", mut("SyntheticImportReport.boundary-error.json", lambda d: d["error"].__setitem__("code", "OOPS")))
bad("SyntheticRunReport.result-without-digest.json", mut("SyntheticRunReport.json", lambda d: d.pop("dataset_digest")))
bad("SyntheticRunReport.missing-dropped.json", mut("SyntheticRunReport.json", lambda d: d.pop("dropped")))
bad("SyntheticDefs.Store.file-without-root.json", {"kind": "file"})
bad("SyntheticDefs.Store.http-token-value.json", {"kind": "http", "base_url": "http://x", "token": "secret"})
bad("SyntheticDefs.Output.missing-store.json", {"work_dir": "w"})
print("written", len(list(OUT.glob("*.json"))))
