"""줄별 판정을 파일마다·전체로 집계한다. ImportTallyInput -> ImportTally.

집계는 건수와 사유 코드뿐이고 입력 값은 담지 않는다. 행의 split 필드는 값을 적지 않고 개수만 센다(값 형식 미확인)."""
from __future__ import annotations

from collections import Counter

from ..types.schema_registry import check


def run(inp: dict) -> dict:
    check("ImportTallyInput", inp)
    inputs, reasons_by_file, first_at, valid = {}, {}, {}, {}
    total = bad = 0
    row_splits = {}
    hr, pending_n, pii_rows, pii_kind_rows = Counter(), {}, Counter(), Counter()
    for f in inp["files"]:
        name, recs, reasons, sp = f["name"], [], Counter(), []
        for i, row in enumerate(f["rows"], 1):
            v = row["verdict"]
            sp.append(v["row_split"])
            if v["sample"] is None:
                for w in v["reasons"]:
                    reasons[w] += 1
                    first_at.setdefault((name, w), i)
                continue
            recs.append(v["sample"])
            hr[v["sample"].get("human_review", "(없음)")] += 1
            if v["sample"].get("human_review") == "pending":
                pending_n[name] = pending_n.get(name, 0) + 1
            if row["pii_kinds"]:
                pii_rows[name] += 1
                pii_kind_rows.update(row["pii_kinds"])
        n = len(f["rows"])
        row_splits[name] = {"absent": sum(1 for x in sp if x is None), "distinct_values": len({x for x in sp if x is not None})}
        inputs[name] = {"sha256": f["sha256"], "rows": n, "valid": len(recs), "invalid": n - len(recs)}
        reasons_by_file[name] = dict(sorted(reasons.items()))
        valid[name] = recs
        total += n
        bad += n - len(recs)
    agg = Counter()
    for rs in reasons_by_file.values():
        agg.update(rs)
    out = {"summary": {
        "inputs": inputs, "total_rows": total, "valid_rows": total - bad, "invalid_rows": bad,
        "invalid_reasons_by_file": reasons_by_file, "invalid_reasons_total": dict(sorted(agg.items())),
        "first_invalid_line": {f"{k[0]} | {k[1]}": ln for k, ln in sorted(first_at.items())},
        "row_split_field": row_splits, "human_review_counts": dict(sorted(hr.items())),
        "pending_by_file": dict(pending_n), "pii_rows_by_file": dict(sorted(pii_rows.items())),
        "pii_rows_by_kind": dict(sorted(pii_kind_rows.items())), "pii_rows_total": sum(pii_rows.values())},
        "valid_samples": valid}
    check("ImportTally", out)
    return out
