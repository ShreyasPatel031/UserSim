"""My own re-implementation of full18c's re-page closure (paging_v2.py lines ~140-200), to estimate the miss rate.
Per pass each visible account is served unless 'missed' (prob m_i); served rows = N (missed slots filled by duplicates).
Chain phase gives the starting union (a pass not counted in seen_in). Rules as in full18c: MAX_PASSES 8/attempt,
TOTAL_PASSES 24, stall (3 passes each < max(2, 0.2% header) new and not (zero & full depth)), short_end n/a (full depth),
close iff full_depth and (union >= 98% header or zero_full >= need) and chao1 < 0.5. Attempts resume (state kept)."""
import numpy as np, sys
rng = np.random.default_rng(int(sys.argv[1]) if len(sys.argv) > 1 else 0)

def chao1(c):
    f1 = int((c == 1).sum()); f2 = int((c == 2).sum())
    return f1 * f1 / (2 * f2) if f2 else f1 * (f1 - 1) / 2

def run(N, hidden, miss, arrivals=0):
    H = N + hidden
    inu = rng.random(N) > np.maximum(miss, 0.24)          # chain phase: ~76% (or worse)
    cnt = np.zeros(N, int); new_hist = []; total = 0; attempts = 0
    while True:
        attempts += 1; p_att = 0
        while True:
            if total >= 24: return "exhausted", inu, total
            if p_att >= 8: break                               # repage_max_passes -> next attempt resumes
            if arrivals:                                       # new followers arrive during a pass (moving target)
                k = rng.poisson(arrivals); N2 = len(cnt) + k
                inu = np.r_[inu, np.zeros(k, bool)]; cnt = np.r_[cnt, np.zeros(k, int)]; miss = np.r_[miss, np.full(k, miss.mean())]
            got = rng.random(len(cnt)) > miss
            nw = int((got & ~inu).sum()); inu |= got; cnt += got; total += 1; p_att += 1; new_hist.append(nw)
            u = int(inu.sum()); need = 3 if (H > 1000 or u < 0.98 * H) else 2
            zf = 0
            for x in reversed(new_hist):
                if x == 0: zf += 1
                else: break
            if (u >= 0.98 * H or zf >= need) and chao1(cnt[cnt > 0]) < 0.5:
                return "closed", inu, total
            l3 = new_hist[-3:]
            if len(l3) == 3 and all(x < max(2, 0.002 * H) for x in l3) and nw != 0:
                break                                          # repage_stalled -> not whole, next attempt resumes

scen = []
for N in (300, 3000, 20000):
    for hid in (0, int(0.1 * N)):
        for name, mk in (("m=0.02", lambda n: np.full(n, .02)), ("m=0.10", lambda n: np.full(n, .10)), ("m=0.25", lambda n: np.full(n, .25)),
                         ("hetero: 1% at 0.9, rest 0.05", lambda n: np.where(rng.random(n) < .01, .9, .05)),
                         ("hetero: 0.2% at 0.97, rest 0.05", lambda n: np.where(rng.random(n) < .002, .97, .05))):
            scen.append((N, hid, name, mk, 0))
for N in (3000, 20000):
    scen.append((N, 0, "m=0.10 + arrivals 1/pass", lambda n: np.full(n, .10), 1))
    scen.append((N, 0, "m=0.10 + arrivals 5/pass", lambda n: np.full(n, .10), 5))
R = 200
print("N\thidden\tscenario\tclosed%\tclosed runs w/ >=1 miss\tmissed accts per closed run\tmean passes\texhausted%")
for N, hid, name, mk, arr in scen:
    out = [run(N, hid, mk(N), arr) for _ in range(R if N < 20000 else 60)]
    cl = [(inu, t) for e, inu, t in out if e == "closed"]; n = len(out)
    miss_runs = sum((~inu).sum() > 0 for inu, _ in cl)
    print(f"{N}\t{hid}\t{name}\t{100*len(cl)/n:.0f}\t{miss_runs}/{len(cl)}\t{np.mean([(~inu).sum() for inu,_ in cl]) if cl else float('nan'):.3f}\t"
          f"{np.mean([t for _,_,t in out]):.1f}\t{100*sum(e=='exhausted' for e,_,_ in out)/n:.0f}", flush=True)
