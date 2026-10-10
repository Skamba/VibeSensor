"""jdiff.py a.json b.json: list differing leaf paths (first N) and count; numeric max abs/rel diff."""
import json, sys, math
a = json.load(open(sys.argv[1])); b = json.load(open(sys.argv[2]))
N = int(sys.argv[3]) if len(sys.argv) > 3 else 15
diffs = []; num = []
def walk(x, y, p):
    if type(x) != type(y) and not (isinstance(x, (int, float)) and isinstance(y, (int, float))):
        diffs.append((p, repr(x)[:80], repr(y)[:80])); return
    if isinstance(x, dict):
        for k in x.keys() | y.keys():
            if k not in x or k not in y: diffs.append((p + "/" + k, "missing" if k not in x else "", "missing" if k not in y else "")); continue
            walk(x[k], y[k], p + "/" + k)
    elif isinstance(x, list):
        if len(x) != len(y): diffs.append((p, f"len {len(x)}", f"len {len(y)}"))
        for i, (u, v) in enumerate(zip(x, y)): walk(u, v, f"{p}[{i}]")
    elif x != y:
        diffs.append((p, repr(x)[:80], repr(y)[:80]))
        if isinstance(x, (int, float)) and isinstance(y, (int, float)) and not isinstance(x, bool):
            num.append((abs(x - y), abs(x - y) / max(abs(x), abs(y), 1e-300), p))
walk(a, b, "")
print("differing leaves:", len(diffs))
for d in diffs[:N]: print("  ", *d)
if num:
    print("max abs diff", max(num)[0], max(num)[2]); print("max rel diff", max(num, key=lambda t: t[1])[1], max(num, key=lambda t: t[1])[2])
