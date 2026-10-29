"""영역 빌드 진입점 scripts/build-image.sh (계약 v2.5.0 BuildImageRequest/BuildImageResult, U42).

도커는 DOCKER 환경 변수로 바꿀 수 있다는 계약 규칙을 이용해 가짜 도커로 배선(요청 검증, 라벨 값이 요청에서 오는지, 결과 형식)을 시험한다.
실제 도커 빌드는 scripts/smoke_build_image.sh가 한다(이미지·컨테이너 이름에 리포 이름을 넣고 끝나면 지운다)."""
from __future__ import annotations

import json
import os
import stat
import subprocess
import sys
from pathlib import Path

import pytest

from boundary_contracts import validator

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "build-image.sh"

FAKE_DOCKER = f"""#!{sys.executable}
import json, sys, pathlib
state = pathlib.Path(__file__).with_suffix(".state")
a = sys.argv[1:]
if a[0] == "build":
    args = {{a[i + 1].split("=", 1)[0]: a[i + 1].split("=", 1)[1] for i, x in enumerate(a) if x == "--build-arg"}}
    ctx = {{a[i + 1].split("=", 1)[0]: a[i + 1].split("=", 1)[1] for i, x in enumerate(a) if x == "--build-context"}}
    labels = {{a[i + 1].split("=", 1)[0]: a[i + 1].split("=", 1)[1] for i, x in enumerate(a) if x == "--label"}}
    state.write_text(json.dumps({{"args": args, "ctx": ctx, "labels": labels, "tag": a[a.index("-t") + 1], "src": a[-1]}}))
    print("sha256:" + "ab" * 32)
elif a[0] == "image":
    st = json.loads(state.read_text())
    if "{{{{.Id}}}}" in a[-2]:
        print("sha256:" + "ab" * 32)
    else:
        g = st["args"]
        print(json.dumps({{"io.openit.service": "dataset-store", "io.openit.revision": g["REVISION"],
            "io.openit.contracts.boundary": g["BC_VERSION"], "io.openit.contracts.survey-schema": g["SURVEY_SCHEMA_VERSION"],
            "io.openit.turn-engine": "n/a", "io.openit.model-runtime": "n/a", "org.opencontainers.x": "ignored", **st["labels"]}}))
"""


@pytest.fixture
def env(tmp_path):
    bc = tmp_path / "bc-src"
    bc.mkdir()
    (bc / "pyproject.toml").write_text('[build-system]\nrequires=["setuptools"]\nbuild-backend="setuptools.build_meta"\n[project]\nname="boundary-contracts"\nversion="9.9.9"\n')
    (bc / "boundary_contracts").mkdir()
    (bc / "boundary_contracts" / "__init__.py").write_text("")
    ss = tmp_path / "ss-src"
    (ss / "schemas").mkdir(parents=True)
    (ss / "CONTRACT_VERSION").write_text("1\n")
    src = tmp_path / "src"
    src.mkdir()
    (src / "Dockerfile").write_text("FROM scratch\n")
    (src / "jobs.json").write_text((ROOT / "jobs.json").read_text(encoding="utf-8"))
    (src / "deploy-exposure.json").write_text((ROOT / "deploy-exposure.json").read_text(encoding="utf-8"))
    fake = tmp_path / "fake-docker"
    fake.write_text(FAKE_DOCKER)
    fake.chmod(fake.stat().st_mode | stat.S_IEXEC)
    req = {"source_dir": str(src), "revision": "abc1234", "versions": {"boundary": "v2.6.0", "survey_schema": "v1.1.0", "turn_engine": "v0.4.3", "model_runtime": "v0.9.0"},
           "dependency_sources": {"boundary": str(bc), "survey_schema": str(ss)}, "image_tag": "synthetic-data-dataset-store:test"}
    return tmp_path, fake, req


def run(tmp_path, fake, req):
    p = tmp_path / "req.json"
    p.write_text(json.dumps(req))
    return subprocess.run(["bash", str(SCRIPT), str(p)], capture_output=True, text=True, timeout=300,
                          env={**os.environ, "DOCKER": str(fake), "PYTHON": sys.executable})


def test_success_last_line_is_build_image_result_with_labels_from_request(env):
    tmp, fake, req = env
    r = run(tmp, fake, req)
    assert r.returncode == 0, r.stderr
    res = json.loads(r.stdout.strip().splitlines()[-1])
    validator("BuildImageResult").validate(res)
    assert res["image"] == req["image_tag"] and res["image_id"].startswith("sha256:")
    res["labels"].pop("io.openit.exposure")
    jobs = res["labels"].pop("io.openit.jobs")
    assert json.loads(jobs) == json.loads((ROOT / "jobs.json").read_text(encoding="utf-8"))
    assert res["labels"] == {"io.openit.service": "dataset-store", "io.openit.revision": "abc1234", "io.openit.contracts.boundary": "v2.6.0",
                             "io.openit.contracts.survey-schema": "1", "io.openit.turn-engine": "n/a", "io.openit.model-runtime": "n/a"}
    validator("ImageLabels").validate(res["labels"])


def test_build_uses_only_dependency_sources_and_source_dir(env):
    tmp, fake, req = env
    assert run(tmp, fake, req).returncode == 0
    st = json.loads((tmp / "fake-docker.state").read_text())
    assert st["src"] == req["source_dir"] and st["ctx"]["survey_schema"] == req["dependency_sources"]["survey_schema"]
    assert st["args"]["BC_SPEC"].startswith("/wheels/boundary_contracts-")


@pytest.mark.parametrize("mutate", [
    lambda r: r.update(unknown=1),
    lambda r: r.pop("revision"),
    lambda r: r.update(revision="unknown"),
    lambda r: r["versions"].pop("boundary"),
    lambda r: r["versions"].pop("survey_schema"),
    lambda r: r.pop("dependency_sources"),
    lambda r: r["dependency_sources"].pop("boundary"),
    lambda r: r["dependency_sources"].pop("survey_schema"),
    lambda r: r.update(variant="gpu"),
    lambda r: r.update(image_tag="NoTag"),
], ids=["unknown-key", "no-revision", "revision-unknown", "no-boundary", "no-survey-schema", "no-dep-sources", "no-bc-src", "no-ss-src", "variant", "bad-tag"])
def test_invalid_or_incomplete_request_fails_before_docker(env, mutate):
    tmp, fake, req = env
    mutate(req)
    r = run(tmp, fake, req)
    assert r.returncode != 0
    assert not (tmp / "fake-docker.state").exists()          # 도커를 부르기 전에 실패했다


def test_missing_request_file_fails(env):
    tmp, fake, _ = env
    r = subprocess.run(["bash", str(SCRIPT), str(tmp / "none.json")], capture_output=True, text=True,
                       env={**os.environ, "DOCKER": str(fake), "PYTHON": sys.executable})
    assert r.returncode != 0


def test_script_has_no_neighbor_paths_or_version_defaults():
    text = SCRIPT.read_text(encoding="utf-8") + (ROOT / "scripts" / "build_image_request.py").read_text(encoding="utf-8")
    assert "../" not in text.replace("../..", "")            # 이웃 리포 경로 없음
    assert "git@" not in text and "ssh://" not in text        # 빌드 중 네트워크(SSH) 없음


def test_jobs_label_is_in_result_and_valid_against_contract(env):
    tmp, fake, req = env
    r = run(tmp, fake, req)
    res = json.loads(r.stdout.strip().splitlines()[-1])
    validator("ImageLabels").validate(res["labels"])                      # io.openit.jobs의 contentSchema(JobsDeclaration)까지 확인된다
    validator("JobsDeclaration").validate(json.loads(res["labels"]["io.openit.jobs"]))


def test_invalid_jobs_json_fails_before_docker(env):
    tmp, fake, req = env
    (Path(req["source_dir"]) / "jobs.json").write_text(json.dumps({"jobs": [{"name": "x", "argv": ["a"], "idempotent": False}]}))
    r = run(tmp, fake, req)
    assert r.returncode != 0 and not (tmp / "fake-docker.state").exists()


def test_repo_jobs_json_matches_contract_and_code():
    decl = json.loads((ROOT / "jobs.json").read_text(encoding="utf-8"))
    validator("JobsDeclaration").validate(decl)
    jobs = {j["name"]: j for j in decl["jobs"]}
    assert set(jobs) == {"synthetic-run", "synthetic-import"}
    for name, sub, schema in (("synthetic-run", "run", "SyntheticJobConfigRun"), ("synthetic-import", "import", "SyntheticJobConfigImport")):
        j = jobs[name]
        assert j["argv"][:4] == ["python", "-m", "synthetic_data", sub] and j["config"]["schema"] == schema
        assert j["argv"][-1] == j["config"]["container_path"] and j["idempotent"] is True
        validator(schema)                                                   # 선언한 설정 스키마가 계약에 있다
    # 비밀 파일 이름은 설정의 token_env 기본·예시와 맞는다(NAME_FILE = NAME + _FILE, D84)
    from synthetic_data.store.spec import DEFAULT_TOKEN_ENV
    assert DEFAULT_TOKEN_ENV + "_FILE" in jobs["synthetic-run"]["secret_files"]
    assert DEFAULT_TOKEN_ENV + "_FILE" in jobs["synthetic-import"]["secret_files"]


def test_exposure_label_is_in_result_and_valid_against_contract(env):
    tmp, fake, req = env
    res = json.loads(run(tmp, fake, req).stdout.strip().splitlines()[-1])
    validator("ImageLabels").validate(res["labels"])
    exp = json.loads(res["labels"]["io.openit.exposure"])
    validator("Exposure").validate(exp)
    assert exp == json.loads((ROOT / "deploy-exposure.json").read_text(encoding="utf-8"))


def test_invalid_exposure_fails_before_docker(env):
    tmp, fake, req = env
    (Path(req["source_dir"]) / "deploy-exposure.json").write_text(json.dumps({"service": "dataset-store", "routes": [{"paths": ["/x"], "auth": {"kind": "account"}}]}))
    r = run(tmp, fake, req)
    assert r.returncode != 0 and not (tmp / "fake-docker.state").exists()      # account는 roles가 필수


def test_exposure_table_matches_code_routes():
    """표(deploy-exposure.json)와 서버 코드의 라우트가 일치한다. 이 서비스는 게이트웨이 밖으로 내지 않는다(compose 네트워크 datasets는 internal, 게이트웨이 미연결):
    코드의 모든 경로는 표의 denied 경로에 들어가야 하고, 표에는 코드에 없는 경로가 없어야 한다."""
    import re
    exp = json.loads((ROOT / "deploy-exposure.json").read_text(encoding="utf-8"))
    assert all(r["auth"]["kind"] == "denied" for r in exp["routes"])
    table = {p for r in exp["routes"] for p in r["paths"]}
    src = (ROOT / "synthetic_data" / "service" / "app.py").read_text(encoding="utf-8")
    code = set(re.findall(r'path (?:==|!=) "(/[^"]*)"', src))                    # /healthz, /readyz, /v1/datasets
    if re.search(r'compile\(r"\^/v1/datasets/', src):                          # 데이터셋 하위 경로 정규식들
        code.add("/v1/datasets/*")
    assert code == {"/healthz", "/readyz", "/v1/datasets", "/v1/datasets/*"} == table
