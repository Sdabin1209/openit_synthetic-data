from __future__ import annotations

import copy

import pytest

import doubles
from synthetic_data.context import QuestionSetContext
from synthetic_data.quality import check_lora_a_sample, check_lora_b_sample
from synthetic_data.split import assign_split


@pytest.fixture(scope="module")
def ctx():
    r = doubles.make_question_reader()
    ref = r.latest("qs-main")
    return QuestionSetContext(ref, r.get_question_bank(ref), "TRAIN_POOL")


def test_split_assign():
    ratios = {"TRAIN": 0.6, "VALIDATION": 0.2, "EVAL": 0.2}
    assert assign_split("sc-1", "HELD_OUT_EVAL", ratios, 1) == "EVAL"
    got = [assign_split(f"sc-{i}", "TRAIN_POOL", ratios, 1) for i in range(2000)]
    assert {x: got.count(x) / 2000 for x in set(got)} == pytest.approx({"TRAIN": 0.6, "VALIDATION": 0.2, "EVAL": 0.2}, abs=0.05)
    assert got == [assign_split(f"sc-{i}", "TRAIN_POOL", ratios, 1) for i in range(2000)]
    assert assign_split("sc-1", "TRAIN_POOL", {"TRAIN": 0, "VALIDATION": 0, "EVAL": 1}, 3) == "EVAL"


def test_quality_accepts_v2_samples_and_rejects_v1_shapes(ctx, validators):
    from conftest import v2_sample
    for role in ("LORA_A", "LORA_B"):
        s = v2_sample(role, 1, "TRAIN", ctx.ref)
        check = check_lora_a_sample if role == "LORA_A" else check_lora_b_sample
        assert check(s, ctx.bank, validators) == []
        bad = copy.deepcopy(s)
        bad["expected"] = {"items": []} if role == "LORA_A" else {"response_text": "x", "is_fallback": False}   # v1 형태
        assert check(bad, ctx.bank, validators) == ["schema_sample"]
        bad2 = copy.deepcopy(s)
        bad2["runtime_contract_version"] = 1                                                                    # v1 샘플 필드
        assert check(bad2, ctx.bank, validators) == ["schema_sample"]


def test_quality_rejects_a_output_that_breaks_the_save_rule(ctx, validators):
    """형식 검사 한 가지: ActionExtraction의 status와 save 규칙(ANSWERED면 save true)은 스키마가 잡는다. 의미 검사(targets, next_item 등)는 turn-engine 몫(미정)."""
    from conftest import v2_sample
    s = v2_sample("LORA_A", 1, "TRAIN", ctx.ref)
    s["expected"]["values"][0]["save"] = False
    assert check_lora_a_sample(s, ctx.bank, validators) == ["schema_sample"]
