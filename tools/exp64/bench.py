"""bench.py <dir> <out.json> [profile]: time load/build/analyze of the drive, dump storage JSON."""
import hashlib, resource, sqlite3, sys, time
from pathlib import Path
t00 = time.perf_counter()
from vibesensor.history.history_db import HistoryDB
from vibesensor.analysis.post_analysis_loader import load_post_analysis_run
from vibesensor.analysis.post_analysis_input import build_post_analysis_input
from vibesensor.analysis.post_analysis_summary import build_post_analysis_summary
from vibesensor.common.json_utils import safe_json_dumps
from vibesensor.summary.persisted_analysis import PersistedAnalysis
from vibesensor.summary.persisted_codec import persisted_analysis_to_storage_json_object as tostore
t_imp = time.perf_counter() - t00
import vibesensor.dsp.window_spectrum as _ws
_orig_lr = _ws.line_reads
LR = [0.0, 0.0]
def _timed_lr(*a, **k):
    t = time.perf_counter()
    try:
        return _orig_lr(*a, **k)
    finally:
        dt = time.perf_counter() - t; LR[0] += dt; LR[1] = LR[1] or dt
for _m in list(sys.modules.values()):
    if getattr(_m, "line_reads", None) is _orig_lr:
        _m.line_reads = _timed_lr
d = Path(sys.argv[1]); out = Path(sys.argv[2])
rid = sqlite3.connect(d / "history.db").execute("select run_id from runs").fetchone()[0]
db = HistoryDB(d / "history.db")
def rss(): return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss // 1024
T = {}
t = time.perf_counter(); lr = load_post_analysis_run(run_id=rid, db=db); T["load"] = time.perf_counter() - t
t = time.perf_counter(); ri = build_post_analysis_input(lr); del lr; T["build"] = time.perf_counter() - t
rss_build = rss()
prof = None
if len(sys.argv) > 3:
    import cProfile; prof = cProfile.Profile(); prof.enable()
t = time.perf_counter(); s = build_post_analysis_summary(ri); T["analyze"] = time.perf_counter() - t
if prof:
    prof.disable(); prof.dump_stats(sys.argv[3])
if not isinstance(s, PersistedAnalysis): s = PersistedAnalysis.from_json_object(s)
t = time.perf_counter(); o = tostore(s); o["report_date"] = None; o["case_id"] = None; txt = safe_json_dumps(o); T["encode"] = time.perf_counter() - t
out.write_text(txt)
print("import %.1fs" % t_imp, " ".join(f"{k} {v:.1f}s" for k, v in T.items()), "total %.1fs" % sum(T.values()), "line_reads %.2fs (first call %.2fs)" % tuple(LR),
      "rss_after_build", rss_build, "peak_rss_MB", rss(), "sha", hashlib.sha256(txt.encode()).hexdigest()[:16], flush=True)
db.close()
