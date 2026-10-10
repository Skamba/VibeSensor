import json, sys
a = json.load(open(sys.argv[1])); b = json.load(open(sys.argv[2]))
F = ("finding_id", "finding_key", "order", "suspected_source", "strongest_location", "strongest_speed_band",
     "finding_kind", "confidence_level", "weak_spatial_separation", "diffuse_excitation", "peak_classification")
def v(d):
    out = {"findings": [{k: f.get(k) for k in F} | {"n_points": len(f.get("matched_points") or []),
            "conf": round(f.get("confidence") or 0, 4)} for f in d["findings"]],
           "top_causes": [{k: f.get(k) for k in F} for f in d["top_causes"]],
           "origin": {k: x for k, x in d["most_likely_origin"].items() if not isinstance(x, float)},
           "sensor_locations": d.get("sensor_locations"), "warnings": d.get("warnings"),
           "suitability": d.get("run_suitability")}
    return out
va, vb = v(a), v(b)
for k in va:
    print(k, "SAME" if va[k] == vb[k] else "DIFF")
    if va[k] != vb[k] and k == "findings":
        for x, y in zip(va[k], vb[k]):
            if x != y: print("  ", {kk: (x[kk], y[kk]) for kk in x if x[kk] != y[kk]})
lens = [0]
def walk(x, y):
    if isinstance(x, list):
        if len(x) != len(y): lens[0] += 1
        for u, w in zip(x, y): walk(u, w)
    elif isinstance(x, dict):
        for kk in x:
            if kk in y: walk(x[kk], y[kk])
walk(a, b); print("lists with different length:", lens[0])
