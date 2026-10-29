"""build-image.sh의 요청 해석기. 요청 JSON을 계약 BuildImageRequest로 검증하고, 이 영역(dataset-store)이 쓰는 값만 한 줄에 하나씩 낸다.

왜 파이썬인가: 요청 검증은 계약 validator가 정본이고(boundary_contracts.validator), 쉘로 JSON을 파싱하면 경계 입력 검사가 흩어진다.
출력 순서: source_dir, revision, boundary, survey_schema, bc_src, ss_src, image_tag
이 영역이 쓰는 키(versions.boundary, versions.survey_schema, dependency_sources.boundary, dependency_sources.survey_schema)가 없으면 실패한다.
기본값을 영역 안에 두지 않는다(배포 기준표와 어긋나지 않게). model_runtime은 이 이미지가 쓰지 않으므로 무시한다(라벨 n/a). turn_engine은 계약 3.0.0에서 없어졌다."""
from __future__ import annotations

import json
import sys

from boundary_contracts import validator

IMAGE_VARIANTS = ()      # 이 리포는 이미지 하나(dataset-store)만 낸다. variant가 오면 모르는 값이다


def parse(path: str) -> list:
    try:
        with open(path, encoding="utf-8") as f:
            req = json.load(f)
    except (OSError, ValueError) as e:
        raise SystemExit(f"요청 파일을 읽을 수 없다: {type(e).__name__}")
    errs = sorted(f"{'.'.join(map(str, e.absolute_path)) or '(최상위)'}: {e.validator}" for e in validator("BuildImageRequest").iter_errors(req))
    if errs:
        raise SystemExit("요청이 BuildImageRequest를 어긴다: " + "; ".join(errs[:5]))
    if "variant" in req:
        raise SystemExit("이 영역은 variant를 모른다(이미지 하나: dataset-store)")
    v, d = req["versions"], req.get("dependency_sources", {})
    for grp, name, keys in ((v, "versions", ("boundary", "survey_schema")), (d, "dependency_sources", ("boundary", "survey_schema"))):
        missing = [k for k in keys if k not in grp]
        if missing:
            raise SystemExit(f"{name}에 이 영역이 쓰는 키가 없다: {missing}")
    return [req["source_dir"], req["revision"], v["boundary"], v["survey_schema"], d["boundary"], d["survey_schema"], req["image_tag"]]


def label_json(path: str, schema: str) -> str:
    """리포의 선언 파일(jobs.json, deploy-exposure.json)을 계약 스키마로 검증하고 이미지 라벨에 넣을 한 줄 JSON을 낸다."""
    with open(path, encoding="utf-8") as f:
        decl = json.load(f)
    errs = sorted(f"{'.'.join(map(str, e.absolute_path)) or '(최상위)'}: {e.validator}" for e in validator(schema).iter_errors(decl))
    if errs:
        raise SystemExit(f"{path.rsplit('/', 1)[-1]}이 {schema}를 어긴다: " + "; ".join(errs[:5]))
    return json.dumps(decl, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def jobs_label(path: str) -> str:
    return label_json(path, "JobsDeclaration")


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "--jobs":
        print(jobs_label(sys.argv[2]))
        raise SystemExit(0)
    if len(sys.argv) == 3 and sys.argv[1] == "--exposure":
        print(label_json(sys.argv[2], "Exposure"))
        raise SystemExit(0)
    if len(sys.argv) != 2:
        raise SystemExit("사용: build_image_request.py <요청 JSON 파일>")
    print("\n".join(parse(sys.argv[1])))
