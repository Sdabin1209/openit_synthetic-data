from __future__ import annotations

import copy
import random

import pytest

import doubles
from conftest import make_cfg_raw, needs_generator_v2
from synthetic_data import josa
from synthetic_data.config import parse_config
from synthetic_data.generators import (ResponseGenerator, RuleResponseGenerator, RuleUtteranceGenerator,
                                       UtteranceGenerator)
from synthetic_data.labeler import LabelError, build_parser_expected
from synthetic_data.noise import apply_noise
from synthetic_data.pipeline import build_generator_samples, build_parser_samples
from synthetic_data.plans import FactPlan, FactSurface, UtteranceDraft
from synthetic_data.quality import check_lora_a_sample, check_lora_b_sample
from synthetic_data.scenario import QuestionSetContext, design_generator_plans, design_parser_plans
from synthetic_data.split import assign_split


@pytest.fixture(scope="module")
def ctx():
    r = doubles.make_question_reader()
    ref = r.latest("qs-main")
    return QuestionSetContext(ref, r.get_question_bank(ref), "TRAIN_POOL")


@pytest.fixture(scope="module")
def cfg(tmp_path_factory):
    return parse_config(make_cfg_raw(tmp_path_factory.mktemp("c")), __import__("pathlib").Path("."))


@pytest.fixture(scope="module")
def parser_samples(ctx, cfg):
    plans, _ = design_parser_plans(ctx, variants=3, seed=1)
    return build_parser_samples(plans, RuleUtteranceGenerator(), cfg, 1)[0]


def test_protocols():
    assert isinstance(RuleUtteranceGenerator(), UtteranceGenerator)
    assert isinstance(RuleResponseGenerator(), ResponseGenerator)


def test_josa():
    assert josa.eul_reul("흡연") == "흡연을" and josa.eul_reul("수면") == "수면을" and josa.eul_reul("커피") == "커피를"
    assert josa.euro("7시간") == "7시간으로" and josa.euro("서울") == "서울로"


@needs_generator_v2
def test_all_parser_kinds_covered(parser_samples):
    kinds = {s["ext"]["synthetic-data"]["kind"] for s in parser_samples}
    assert {"ANSWER_NUMERIC", "ANSWER_CHOICE", "ANSWER_YESNO", "SAYS_UNKNOWN", "SAYS_REFUSAL", "PROGRESS_LATER",
            "GUIDE_REQUEST", "CONFIRM_YES", "CONFIRM_NO", "CONFIRM_NO_WITH_VALUE", "CORRECTION_MARKED", "SELF_CORRECT",
            "MULTI_SLOT", "STAFF_REQUEST", "RESTART_REQUEST", "OUT_OF_SCOPE", "RISK_SIGNAL", "UNRECOGNIZED",
            "EMPTY_UTTERANCE"} <= kinds


@needs_generator_v2
def test_all_parser_samples_pass_quality(parser_samples, ctx, validators):
    assert parser_samples
    for s in parser_samples:
        assert check_parser_sample(s, ctx.bank, validators) == [], (s["input"]["utterance"], s["expected"])


@needs_generator_v2
def test_label_rules(parser_samples):
    """utterance_parser.md 4절 1~8의 대상·값 규칙이 생성 라벨에 지켜졌다."""
    by = {}
    for s in parser_samples:
        by.setdefault(s["ext"]["synthetic-data"]["kind"], []).append(s)
    for s in by["SAYS_UNKNOWN"] + by["SAYS_REFUSAL"]:
        q = s["input"]["awaiting_questions"][0]
        t = s["expected"]["items"][0]["target"]
        assert ("slot_id" in t) == (len(q["slots"]) == 1)                 # 규칙 1
        assert s["expected"]["items"][0]["value"] is None
    assert any("whole_question" in s["expected"]["items"][0]["target"] for s in by["SAYS_UNKNOWN"])   # 다중 슬롯 문항
    for s in by["PROGRESS_LATER"] + by["GUIDE_REQUEST"]:
        assert s["expected"]["items"][0]["target"].get("whole_question") is True
    for s in by["CONFIRM_YES"] + by["CONFIRM_NO"]:
        it = s["expected"]["items"][0]
        assert it["target"] is None and it["value"] is None                # 규칙 1
        assert s["input"]["last_directive"]["action"] == "ASK_CONFIRM"
    for s in by["SELF_CORRECT"]:                                           # 규칙 8: 마지막 값 하나
        items = s["expected"]["items"]
        assert len(items) == 1 and items[0]["intent"] == "ANSWERED_INTENT"
        assert items[0]["value"] in s["input"]["utterance"].split("아니")[-1]
    for s in by["CORRECTION_MARKED"]:                                      # 규칙 2: 표지가 있을 때만
        assert any(m in s["input"]["utterance"] for m in ("아니", "사실", "아 잠깐", "틀렸"))
    for s in by["ANSWER_NUMERIC"] + by["ANSWER_CHOICE"] + by["ANSWER_YESNO"]:
        assert not any(m in s["input"]["utterance"] for m in ("사실", "아 잠깐", "틀렸"))
    for s in by["EMPTY_UTTERANCE"]:
        assert s["input"]["utterance"] == "" and s["expected"]["items"] == []
    for s in by["MULTI_SLOT"]:
        assert len(s["expected"]["items"]) == 2
    for s in by["RISK_SIGNAL"] + by["STAFF_REQUEST"] + by["OUT_OF_SCOPE"]:
        assert s["expected"]["items"][0]["target"] is None
    for s in by["OUT_OF_SCOPE"]:                                            # 문항 목록에 없는 것을 가리킨다
        texts = " ".join(q["name"] + q["question_sentence"] for q in s["input"]["awaiting_questions"])
        assert s["expected"]["items"][0]["source_text"] not in texts


@needs_generator_v2
def test_evidence_offsets(parser_samples):
    n = 0
    for s in parser_samples:
        for it in s["expected"]["items"]:
            for ev in it.get("evidence", []):
                assert s["input"]["utterance"][ev["start"]:ev["end"]] == ev["text"] == it["value"]
                n += 1
    assert n > 20


@needs_generator_v2
def test_noise_keeps_labels_consistent(parser_samples):
    noisy = [s for s in parser_samples if s.get("noise_types")]
    assert noisy
    types = {t for s in noisy for t in s["noise_types"]}
    assert len(types) >= 2
    for s in noisy:
        for it in s["expected"]["items"]:
            assert it["source_text"] in s["input"]["utterance"]


def test_numeral_noise_updates_label():
    d = UtteranceDraft("저는 7시간 잤어요", [FactSurface("7시간 잤어요", "7시간")])
    nd, applied = apply_noise(d, ["STT_NUMERAL"], random.Random(1))
    assert applied == ["STT_NUMERAL"] and nd.facts[0].value == "일곱 시간"
    assert nd.facts[0].value in nd.facts[0].source and nd.facts[0].source in nd.utterance
    back, ap2 = apply_noise(nd, ["STT_NUMERAL"], random.Random(1))
    assert back.facts[0].value == "7시간"


def test_noise_leaves_protected_span_and_reports_only_applied():
    d = UtteranceDraft("아 그러니까 모르겠어요", [FactSurface("모르겠어요", None)])
    nd, applied = apply_noise(d, ["STT_SPACING", "STT_HOMOPHONE", "STT_NUMERAL"], random.Random(0))
    assert nd.utterance.endswith("모르겠어요") and "STT_NUMERAL" not in applied
    assert apply_noise(UtteranceDraft("", []), ["STT_FILLER"], random.Random(0)) == (UtteranceDraft("", []), [])


def test_noise_is_deterministic():
    d = UtteranceDraft("아 그러니까 7시간이에요", [FactSurface("7시간이에요", "7시간")])
    a = apply_noise(d, ["STT_FILLER", "STT_SPACING"], random.Random(5))
    b = apply_noise(d, ["STT_FILLER", "STT_SPACING"], random.Random(5))
    assert a == b


def test_labeler_errors():
    with pytest.raises(LabelError):
        build_parser_expected([FactPlan("SAYS_UNKNOWN")], "모르겠어요", [FactSurface("몰라요", None)])
    with pytest.raises(LabelError):
        build_parser_expected([FactPlan("SAYS_UNKNOWN")], "x", [])


@needs_generator_v2
def test_quality_rejects_bad_labels(parser_samples, ctx, validators):
    base = next(s for s in parser_samples if s["ext"]["synthetic-data"]["kind"] == "ANSWER_CHOICE")

    def reasons(mut):
        s = copy.deepcopy(base)
        mut(s)
        return check_parser_sample(s, ctx.bank, validators)

    assert "source_not_in_utterance" in reasons(lambda s: s["expected"]["items"][0].update(source_text="없는말"))
    assert "value_contradicts_definition" in reasons(
        lambda s: s["expected"]["items"][0].update(value="전혀다른값", source_text=s["input"]["utterance"]) or s["input"].update(utterance=s["input"]["utterance"]))
    assert "target_slot_unknown" in reasons(lambda s: s["expected"]["items"][0]["target"].update(slot_id="zzz"))
    assert "answer_target_not_slot" in reasons(lambda s: s["expected"]["items"][0].update(target={"question_id": "Q1", "whole_question": True}))
    assert "empty_utterance_items_mismatch" in reasons(lambda s: s["expected"].update(items=[]))
    assert "schema_expected" in reasons(lambda s: s["expected"].update(extra=1))
    assert reasons(lambda s: None) == []


@needs_generator_v2
def test_quality_rejects_bad_generator_samples(ctx, cfg, validators):
    plans, _ = design_generator_plans(ctx, variants=1, seed=1)
    samples, st = build_generator_samples(plans, RuleResponseGenerator(), cfg, 1)
    assert samples and st["generator_returned_none"] == 0
    for s in samples:
        assert check_generator_sample(s, ctx.bank, validators) == [], s["expected"]
    risk = next(s for s in samples if s["ext"]["synthetic-data"]["kind"] == "GEN_RISK_NOTICE")
    assert risk["expected"]["response_text"] == "위험할 수 있어 직원이 곧 도와드리겠습니다."      # 규칙 4: 재료 그대로
    bad = copy.deepcopy(risk)
    bad["expected"]["response_text"] = "괜찮을 거예요. " + bad["expected"]["response_text"]
    assert "fixed_sentence_not_verbatim" in check_generator_sample(bad, ctx.bank, validators)
    ask = next(s for s in samples if s["ext"]["synthetic-data"]["kind"] == "GEN_ASK_NEXT")
    bad = copy.deepcopy(ask)
    bad["expected"]["response_text"] += " 약 3알을 드세요."
    assert "value_not_in_directive" in check_generator_sample(bad, ctx.bank, validators)
    bad = copy.deepcopy(ask)
    bad["expected"]["is_fallback"] = True
    assert "synthetic_fallback" in check_generator_sample(bad, ctx.bank, validators)


def test_scenario_ids_independent_of_version_and_deterministic(ctx):
    p1, _ = design_parser_plans(ctx, variants=2, seed=1)
    ctx2 = QuestionSetContext(dict(ctx.ref, version="2", content_hash="sha256:" + "2" * 64), ctx.bank, "TRAIN_POOL")
    p2, _ = design_parser_plans(ctx2, variants=2, seed=1)
    assert [p.scenario_id for p in p1] == [p.scenario_id for p in p2]
    assert len({p.scenario_id for p in p1}) == len(p1)


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
