"""contract-ready 스키마를 예시 문서로 검증한다. 사용(worktree 루트에서): .venv/bin/python docs/change-requests/contract-ready/validate.py
- 이웃과 겹치는 형식은 설치된 boundary_contracts 패키지의 _common.schema.json·BoundaryError.schema.json을 쓴다(중복 정의 없음).
- examples/valid는 모두 통과, examples/invalid는 모두 거부되어야 한다. 파일 이름 `<계약 이름>[.변형].json`; SyntheticDefs는 두 번째 조각이 $defs 이름이다.
- 하나라도 기대와 다르거나, 스키마에 예시가 하나도 없거나, MANIFEST와 파일이 어긋나면 종료 코드 1."""
import json
import sys
from pathlib import Path

import boundary_contracts
from jsonschema import Draft202012Validator, RefResolver

HERE = Path(__file__).resolve().parent
BASE = "https://openit.invalid/contract/"
contract_dir = Path(boundary_contracts.__file__).parent / "schemas"
store = {}
for d in (contract_dir, HERE / "schemas"):
    for p in d.glob("*.schema.json"):
        store[BASE + p.name] = json.loads(p.read_text(encoding="utf-8"))
own = {p.name[:-len(".schema.json")] for p in (HERE / "schemas").glob("*.schema.json")}
manifest = json.loads((HERE / "MANIFEST.json").read_text(encoding="utf-8"))
bad = 0


def fail(msg):
    global bad
    bad += 1
    print("FAIL", msg)


for n in own:
    Draft202012Validator.check_schema(store[BASE + n + ".schema.json"])
    s = store[BASE + n + ".schema.json"]
    if s.get("$id") != n + ".schema.json" or s.get("title") != n:
        fail(f"{n}: $id/title이 계약 이름과 다르다")
if {e["name"] for e in manifest["entries"]} != own:
    fail(f"MANIFEST 항목과 schemas/ 파일이 다르다: {sorted({e['name'] for e in manifest['entries']} ^ own)}")
for e in manifest["entries"]:
    for k in ("name", "source_draft", "producer", "consumers", "unknown_keys", "note"):
        if k not in e:
            fail(f"MANIFEST {e.get('name')}: {k} 없음")
    if e.get("unknown_keys") not in ("reject", "ignore"):
        fail(f"MANIFEST {e['name']}: unknown_keys 값")


def validate(name, defname, doc):
    s = store[BASE + name + ".schema.json"]
    target = {"$ref": f"#/$defs/{defname}", "$defs": s["$defs"]} if defname else s
    # 한 스키마 안의 $ref("#/...")와 다른 파일 $ref가 모두 풀리도록 기준 주소를 그 스키마 파일로 한다
    v = Draft202012Validator(target, resolver=RefResolver(BASE + name + ".schema.json", s, store=store))
    return [f"{'/'.join(map(str, e.absolute_path)) or '(root)'}: {e.message[:80]}" for e in v.iter_errors(doc)]


counts = {"valid": 0, "invalid": 0}
seen = {n: {"valid": 0, "invalid": 0} for n in own}
for kind in ("valid", "invalid"):
    for p in sorted((HERE / "examples" / kind).glob("*.json")):
        parts = p.name[:-5].split(".")
        name = parts[0]
        if name not in own:
            fail(f"{kind}/{p.name}: 계약 이름 {name}이 없다")
            continue
        defname = parts[1] if name == "SyntheticDefs" else None
        errs = validate(name, defname, json.loads(p.read_text(encoding="utf-8")))
        ok = (not errs) if kind == "valid" else bool(errs)
        seen[name][kind] += 1
        counts[kind] += ok
        print(f"{'OK  ' if ok else 'FAIL'} {kind:7s} {'통과' if not errs else '거부'} {p.name}" + (f"  [{errs[0]}]" if errs and kind == "invalid" else ""))
        if not ok:
            bad += 1
            print("     ", errs[:3] if errs else "거부되어야 하는데 통과함")
for n, c in sorted(seen.items()):
    if not c["valid"] or not c["invalid"]:
        fail(f"{n}: 유효 예시 {c['valid']}건, 거부 예시 {c['invalid']}건 (각각 1건 이상 필요)")
print(f"통과 {counts['valid']}건, 거부 {counts['invalid']}건, 기대와 다름 {bad}건")
sys.exit(1 if bad else 0)
