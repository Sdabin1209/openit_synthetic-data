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
            expected: dict, ext: dict, *, seed_case_id: Optional[str] = None, noise: Optional[list] = None,
            style_guide_version: Optional[str] = None) -> dict:
    rec = {"pipeline_schema_version": PIPELINE_SCHEMA_VERSION, "sample_id": sample_id, "scenario_id": scenario_id,
           "question_set": copy.deepcopy(ref), "runtime_contract_version": contract, "split": "TRAIN",
           "origin": origin, "input": inp, "expected": expected, "ext": {EXT: ext}}
    if role == "GENERATOR":
        rec["style_guide_version"] = style_guide_version
    if seed_case_id:
        rec["seed_case_id"] = seed_case_id
    if noise:
        rec["noise_types"] = sorted(noise)
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
            sid = "ps-" + short_hash(plan.scenario_id, plan.question_set["version"], tag)
            out.append(_record("PARSER", sid, plan.scenario_id, plan.question_set, contract, "SYNTHETIC", inp, expected,
                               {"kind": plan.kind, "utterance_generator": f"{ugen.name}@{ugen.version}"}, noise=applied))
    return out, stats


def build_generator_samples(plans: list[GeneratorPlan], rgen: ResponseGenerator, cfg: JobConfig, contract: int) -> tuple[list, Counter]:
    out, stats = [], Counter()
    for plan in plans:
        text = rgen.generate(plan, rng_for(cfg.seed, "resp", plan.scenario_id))
        if not text:
            stats["generator_returned_none"] += 1
            continue
        sid = "gs-" + short_hash(plan.scenario_id, plan.question_set["version"])
        inp = {"directive": plan.directive, "utterance": plan.utterance}
        out.append(_record("GENERATOR", sid, plan.scenario_id, plan.question_set, contract, "SYNTHETIC", inp,
                           {"response_text": text, "is_fallback": False},
                           {"kind": plan.kind, "response_generator": f"{rgen.name}@{rgen.version}",
                            "directive_source": "hand-built"},
                           style_guide_version=cfg.style_guide_version))
    return out, stats


def build_seed_samples(seeds: list[Seed], ctx: QuestionSetContext, cfg: JobConfig, contract: int) -> tuple[list, list, Counter]:
    """시드 사례를 FAILURE_CASE_SEED 샘플로. 파서 시드는 노이즈 변형도 만든다(원문이 발화에서 순서대로 찾아질 때만)."""
    out, skipped, stats = [], [], Counter()
    qids = {q["question_id"] for q in ctx.bank["questions"]}
    for s in seeds:
        scen = "sd-" + short_hash(s.case_id)
        if s.role == "PARSER":
            used = {q["question_id"] for q in s.input["awaiting_questions"]}
        else:
            used = {t["question_id"] for t in s.input["directive"]["targets"]}
        if not used <= qids:
            skipped.append({"case_id": s.case_id, "reason": "시드의 문항이 지정한 문항 세트에 없음"})
            continue
        if s.role == "GENERATOR":
            out.append(_record("GENERATOR", "gs-" + short_hash(scen, ctx.ref["version"]), scen, ctx.ref, contract,
                               "FAILURE_CASE_SEED", copy.deepcopy(s.input), copy.deepcopy(s.expected),
                               {"kind": "SEED"}, seed_case_id=s.case_id, style_guide_version=cfg.style_guide_version))
            stats["seed_generator"] += 1
            continue
        out.append(_record("PARSER", "ps-" + short_hash(scen, ctx.ref["version"], "clean"), scen, ctx.ref, contract,
                           "FAILURE_CASE_SEED", copy.deepcopy(s.input), copy.deepcopy(s.expected), {"kind": "SEED"},
                           seed_case_id=s.case_id))
        stats["seed_parser"] += 1
        items = s.expected["items"]
        if not items or not all(it.get("source_text") for it in items):
            continue
        base = UtteranceDraft(s.input["utterance"], [FactSurface(it["source_text"], it["value"] if isinstance(it["value"], str) else None) for it in items])
        for i in range(cfg.noise_variants):
            nrng = rng_for(cfg.seed, "seednoise", s.case_id, i)
            nd, applied = apply_noise(base, choose_types(cfg.noise_types, nrng), nrng)
            if not applied or any(f.value is not None and f.value not in f.source for f in nd.facts):
                continue
            exp = copy.deepcopy(s.expected)
            ok = True
            for it, f in zip(exp["items"], nd.facts):
                it["source_text"] = f.source
                if f.value is not None:
                    it["value"] = f.value
                if "evidence" in it:
                    del it["evidence"]            # 위치가 바뀌므로 지운다(선택 필드)
            inp = copy.deepcopy(s.input)
            inp["utterance"] = nd.utterance
            if ok:
                out.append(_record("PARSER", "ps-" + short_hash(scen, ctx.ref["version"], f"n{i}"), scen, ctx.ref, contract,
                                   "FAILURE_CASE_SEED", inp, exp, {"kind": "SEED"}, seed_case_id=s.case_id, noise=applied))
                stats["seed_parser_noise"] += 1
    return out, skipped, stats
