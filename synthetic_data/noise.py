"""STT 노이즈 주입기. 음성 인식이 낼 법한 흔한 표면 오류를 발화에 더한다.

라벨이 흔들리지 않게 '보호 구간'(각 사실의 source 글자)은 건드리지 않고 그 사이 글자(리드·꼬리)에만 적용한다.
예외는 STT_NUMERAL로, 보호 구간 안의 수 표기(7시간 <-> 일곱 시간)를 바꾸되 source와 value를 함께 바꿔 라벨과 일치시킨다.
실제로 글자가 바뀐 종류만 돌려준다."""
from __future__ import annotations

import random
import re
from typing import Optional

from .plans import FactSurface, UtteranceDraft

NOISE_TYPES = ["STT_FILLER", "STT_SPACING", "STT_HOMOPHONE", "STT_NUMERAL"]
_HOMOPHONE = {"그러니까": "그러니가", "저는": "저넌", "그냥": "그낭", "아 ": "아~ ", "음": "으음"}
_FILLERS = ["음 ", "어 ", "저기 "]
_NATIVE = {1: "한", 2: "두", 3: "세", 4: "네", 5: "다섯", 6: "여섯", 7: "일곱", 8: "여덟", 9: "아홉", 10: "열"}
_COUNTERS = "시간|번|잔|병|개|캔|갑|명"
_DIGIT_RE = re.compile(rf"(\d+)(\s?)({_COUNTERS})")
_NATIVE_RE = re.compile(rf"({'|'.join(sorted(_NATIVE.values(), key=len, reverse=True))})(\s?)({_COUNTERS})")
_NATIVE_REV = {v: k for k, v in _NATIVE.items()}


def _numeral(text: str) -> str:
    def to_native(m):
        n = int(m.group(1))
        return f"{_NATIVE[n]} {m.group(3)}" if n in _NATIVE else m.group(0)
    new = _DIGIT_RE.sub(to_native, text)
    if new != text:
        return new
    return _NATIVE_RE.sub(lambda m: f"{_NATIVE_REV[m.group(1)]}{m.group(3)}", text)


def _locate(draft: UtteranceDraft) -> Optional[list]:
    pos, spans = 0, []
    for f in draft.facts:
        i = draft.utterance.find(f.source, pos)
        if i < 0 or not f.source:
            return None
        spans.append((i, i + len(f.source)))
        pos = i + len(f.source)
    return spans


def apply_noise(draft: UtteranceDraft, types: list, rng: random.Random) -> tuple[UtteranceDraft, list]:
    spans = _locate(draft)
    if not spans:
        return draft, []
    utt = draft.utterance
    gaps, prev = [], 0
    for a, b in spans:
        gaps.append(utt[prev:a])
        prev = b
    gaps.append(utt[prev:])
    srcs = [f.source for f in draft.facts]
    vals = [f.value for f in draft.facts]
    applied = []
    for t in types:
        before = (list(gaps), list(srcs))
        if t == "STT_FILLER":
            gaps[0] = rng.choice(_FILLERS) + gaps[0]
        elif t == "STT_SPACING":
            gaps = [g.replace(" ", "") for g in gaps]
        elif t == "STT_HOMOPHONE":
            gaps = [_replace_all(g, _HOMOPHONE) for g in gaps]
        elif t == "STT_NUMERAL":
            for i, s in enumerate(srcs):
                ns = _numeral(s)
                if ns != s:
                    if vals[i] is not None:
                        nv = _numeral(vals[i])
                        if nv == vals[i] or nv not in ns:
                            continue
                        vals[i] = nv
                    srcs[i] = ns
        if (gaps, srcs) != before:
            applied.append(t)
    out = gaps[0]
    for i, s in enumerate(srcs):
        out += s + gaps[i + 1]
    facts = [FactSurface(s, v) for s, v in zip(srcs, vals)]
    return UtteranceDraft(out, facts), sorted(set(applied))


def _replace_all(text: str, table: dict) -> str:
    for k, v in table.items():
        text = text.replace(k, v)
    return text


def choose_types(enabled: list, rng: random.Random) -> list:
    k = rng.choice([1, 2]) if len(enabled) > 1 else 1
    return rng.sample(enabled, min(k, len(enabled)))
