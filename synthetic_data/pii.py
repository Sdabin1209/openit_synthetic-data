"""개인정보 의심 패턴(경고·거부 판정용). import와 시드(run) 경로가 같은 검사를 쓴다(표준성 점검 C4). 비식별 확인이 아니다(ADR 0007)."""
from __future__ import annotations

import json
import re

# 왜/근거: docs/adr/0007. 형식 패턴이라 식별자 전부를 못 잡는다. 수량자 상한은 ReDoS 방지(OWASP 권고), 값은 형식 길이에서 온 것이며 측정 안 함.
# 의심 패턴(경고 전용, 비식별 확인이 아니다). 수량자는 모두 상한이 있고 중첩하지 않아 ReDoS에 안전하다. 행당 검사 길이도 제한한다.
PII_PATTERNS = {
    "email": re.compile(r"[A-Za-z0-9._%+-]{1,64}@[A-Za-z0-9-]{1,63}(?:\.[A-Za-z0-9-]{1,63}){1,4}"),
    "phone_mobile": re.compile(r"(?<!\d)01[016789][-. ]?\d{3,4}[-. ]?\d{4}(?!\d)"),
    "phone_landline": re.compile(r"(?<!\d)0(?:2|[3-6]\d)[-. ]\d{3,4}[-. ]\d{4}(?!\d)"),
    "rrn": re.compile(r"(?<!\d)\d{6}[- ]?[1-4]\d{6}(?!\d)"),
}
PII_SCAN_LIMIT = 20000   # 근거 기록 없음: 행당 상한. 실제 데이터의 최대 길이를 측정하지 않았다(docs/adr/0007)


def pii_kinds(rec: dict) -> list[str]:
    text = (json.dumps(rec["input"], ensure_ascii=False) + " " + (rec["expected"] if isinstance(rec["expected"], str)
            else json.dumps(rec["expected"], ensure_ascii=False)))[:PII_SCAN_LIMIT]
    return [k for k, rx in PII_PATTERNS.items() if rx.search(text)]
