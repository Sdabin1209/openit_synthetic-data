"""schemas/training-data-row.schema.json은 영역이 소유한 형식이다(외부 데이터셋 담당과의 형식이라 계약으로 승격하지 않았다, U49).
이 영역에 남은 유일한 스키마 파일이므로 예시가 스키마와 어긋나지 않는지 본다."""
from __future__ import annotations

import json
from pathlib import Path

import jsonschema

S = Path(__file__).resolve().parent.parent / "schemas"


def v():
    schema = json.loads((S / "TrainingDataRow.schema.json").read_text(encoding="utf-8"))
    jsonschema.Draft202012Validator.check_schema(schema)
    return jsonschema.Draft202012Validator(schema)


def test_valid_examples_pass_and_invalid_example_is_rejected():
    for name in ("TrainingDataRow.valid1", "TrainingDataRow.valid2"):
        v().validate(json.loads((S / "examples" / f"{name}.json").read_text(encoding="utf-8")))
    bad = json.loads((S / "examples" / "TrainingDataRow.invalid1.json").read_text(encoding="utf-8"))
    assert list(v().iter_errors(bad))
