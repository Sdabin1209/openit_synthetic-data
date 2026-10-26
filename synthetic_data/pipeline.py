"""샘플 조립: 계획 -> 초안(생성기) -> 노이즈 -> 정답 구성 -> 샘플 레코드. 난수는 시나리오마다 (시드, 시나리오 ID, 용도)로 파생한다."""
from __future__ import annotations

import copy
from collections import Counter
from typing import Optional

from . import PIPELINE_SCHEMA_VERSION
from .config import JobConfig
from .generators.base import ResponseGenerator, UtteranceGenerator
from .labeler import LabelError, build_parser_expected
from .noise import apply_noise, choose_types
from .plans import FactSurface, GeneratorPlan, ParserPlan, UtteranceDraft
from .rng import rng_for, short_hash
from .scenario import QuestionSetContext
from .seeds import Seed

EXT = "synthetic-data"


def _record(role: str, sample_id: str, scenario_id: str, ref: dict, contract: int, origin: str, inp: dict,
            expected, ext: dict, *, seed_case_id: Optional[str] = None, noise: Optional[list] = None,
            style_guide_version: Optional[str] = None) -> dict:
    """샘플 봉투(2.0.0): ActionExtractionSample/ResponseSample에는 runtime_contract_version, style_guide_version, noise_types가 없다.
    contract·style_guide_version은 호출부 시그니처를 유지하려고 받기만 하고 쓰지 않는다. 노이즈 종류는 ext에 남긴다.
    주의: 내용(inp, expected)은 아직 v1 생성기가 만든 v1 형식이라 v2 스키마를 통과하지 못한다(품질 검사에서 걸러진다, 생성기 이전은 미정)."""
    if noise:
        ext = {**ext, "noise_types": sorted(noise)}
    rec = {"pipeline_schema_version": PIPELINE_SCHEMA_VERSION, "sample_id": sample_id, "scenario_id": scenario_id,
           "question_set": copy.deepcopy(ref), "split": "TRAIN",
           "origin": origin, "input": inp, "expected": expected, "ext": {EXT: ext}}
    if seed_case_id:
        rec["seed_case_id"] = seed_case_id
    return rec


def build_parser_samples(plans: list[ParserPlan], ugen: UtteranceGenerator, cfg: JobConfig, contract: int) -> tuple[list, Counter]:
    out, stats = [], Counter()
    for plan in plans:
        rng = rng_for(cfg.seed, "utt", plan.scenario_id)
        draft = ugen.generate(plan, rng)
        if draft is None or len(draft.facts) != len(plan.facts):
            stats["generator_returned_none"] += 1
            continue
        variants = [("clean", draft, [])]
        for i in range(cfg.noise_variants):
            nrng = rng_for(cfg.seed, "noise", plan.scenario_id, i)
            nd, applied = apply_noise(draft, choose_types(cfg.noise_types, nrng), nrng)
            if applied:
                variants.append((f"n{i}", nd, applied))
            else:
                stats["noise_not_applicable"] += 1
        for tag, d, applied in variants:
            try:
                expected = build_parser_expected(plan.facts, d.utterance, d.facts)
            except LabelError:
                stats["label_error"] += 1
                continue
            inp = copy.deepcopy(plan.base_input)
            inp["utterance"] = d.utterance
            sid = "as-" + short_hash(plan.scenario_id, plan.question_set["version"], tag)
            out.append(_record("LORA_A", sid, plan.scenario_id, plan.question_set, contract, "SYNTHETIC", inp, expected,
                               {"kind": plan.kind, "utterance_generator": f"{ugen.name}@{ugen.version}"}, noise=applied))
    return out, stats


def build_generator_samples(plans: list[GeneratorPlan], rgen: ResponseGenerator, cfg: JobConfig, contract: int) -> tuple[list, Counter]:
    out, stats = [], Counter()
    for plan in plans:
        text = rgen.generate(plan, rng_for(cfg.seed, "resp", plan.scenario_id))
        if not text:
            stats["generator_returned_none"] += 1
            continue
        sid = "rs-" + short_hash(plan.scenario_id, plan.question_set["version"])
        inp = {"directive": plan.directive, "utterance": plan.utterance}
        out.append(_record("LORA_B", sid, plan.scenario_id, plan.question_set, contract, "SYNTHETIC", inp,
                           text,
                           {"kind": plan.kind, "response_generator": f"{rgen.name}@{rgen.version}",
                            "directive_source": "hand-built"},
                           style_guide_version=cfg.style_guide_version))
    return out, stats


def build_seed_samples(pairs: list, cfg: JobConfig, contract: int) -> tuple[list, list, Counter]:
    """시드 사례를 FAILURE_CASE_SEED 샘플로(2.0.0). 시드의 입력은 FailureCase.reviewed_input(LoRA-A는 ActionExtractionInput, LoRA-B는 ResponseRequest)이다.
    v1에 있던 노이즈 변형은 만들지 않는다(원문 위치 source_text가 v2 출력에 없다). 변형 방법은 미정이다."""
    out, skipped, stats = [], [], Counter()
    for s, ctx in pairs:
        qids = {q["question_id"] for q in ctx.bank["questions"]}
        scen = "sd-" + short_hash(s.case_id)
        if s.role == "LORA_A":
            used = {s.input["question_id"]}
        else:
            nxt = s.input.get("next")
            used = {nxt["question_id"]} if isinstance(nxt, dict) and "question_id" in nxt else set()
        if not used <= qids:
            skipped.append({"case_id": s.case_id, "reason": "시드의 문항이 지정한 문항 세트에 없음"})
            continue
        if s.role == "LORA_B":
            out.append(_record("LORA_B", "rs-" + short_hash(scen, ctx.ref["version"]), scen, ctx.ref, contract,
                               "FAILURE_CASE_SEED", copy.deepcopy(s.input), copy.deepcopy(s.expected),
                               {"kind": "SEED"}, seed_case_id=s.case_id))
            stats["seed_lora_b"] += 1
            continue
        out.append(_record("LORA_A", "as-" + short_hash(scen, ctx.ref["version"], "clean"), scen, ctx.ref, contract,
                           "FAILURE_CASE_SEED", copy.deepcopy(s.input), copy.deepcopy(s.expected), {"kind": "SEED"},
                           seed_case_id=s.case_id))
        stats["seed_lora_a"] += 1
    return out, skipped, stats
