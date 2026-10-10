import resource, time, sys, os
def rss():
    for l in open("/proc/self/status"):
        if l.startswith(("VmRSS", "RssAnon", "RssFile")): print("   ", l.strip())
t = time.perf_counter(); import numpy as np; print("numpy import %.2fs" % (time.perf_counter() - t)); rss()
t = time.perf_counter(); import numba; print("numba import %.2fs" % (time.perf_counter() - t)); rss()
@numba.njit(cache=True)
def k(a):
    s = 0.0
    for i in range(a.shape[0]):
        s += a[i] * 2.0 + 1.0
    return s
t = time.perf_counter(); k(np.ones(10)); print("first call (compile or cache load) %.2fs" % (time.perf_counter() - t)); rss()
print("maxrss", resource.getrusage(resource.RUSAGE_SELF).ru_maxrss // 1024)
