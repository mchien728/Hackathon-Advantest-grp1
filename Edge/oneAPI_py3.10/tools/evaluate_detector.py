import argparse
import json
import math
import os
import random
import statistics
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "bin"))
sys.path.insert(0, os.path.join(ROOT, "tools"))
from detector import Detector  # noqa: E402
from inject_anomalies import Scenario, generate  # noqa: E402
from fit_baseline import read_tests, DEFAULT_CSV  # noqa: E402

BASELINE = os.path.join(ROOT, "bin", "model", "baseline.json")
OFF = {"z_out": 1e9, "cusum_h": 1e9, "ewma_L": 1e9, "drift_thr": 1e9, "site_thr": 1e9}
ONE = {"t#p": {"mu": 0.0, "sigma": 1.0, "monitor": True}}
SITES = 4
START = 25
# Provisional targets (spec 6.2): false verdicts per DUT, recall, and max delay in DUTs.
TARGET_FPR_PER_DUT = 1.0 / 5000
KINDS = {
    "mean_shift": {"param": "cusum_h", "grid": [5, 6, 7, 8, 9, 10], "scen": lambda: Scenario("mean_shift", 3.0, START),
                   "desc": "+3 sigma level shift", "recall": 0.95, "delay": 20},
    "variance_change": {"param": "ewma_L", "grid": [2, 3, 4, 5, 6, 7], "extra": ("ewma_lambda", [0.1, 0.05, 0.02]),
                        "scen": lambda: Scenario("variance_change", 2.0, START), "desc": "std x2", "recall": 0.90, "delay": 30},
    "mean_drift": {"param": "drift_thr", "grid": [3.0, 3.5, 4.0, 4.5, 5.0], "scen": lambda: Scenario("mean_drift", 0.2, START),
                   "desc": "drift 0.2 sigma/touchdown", "recall": 0.90, "delay": 80},
    "site_imbalance": {"param": "site_thr", "grid": [3.0, 3.5, 4.0, 4.5, 5.0, 5.5], "scen": lambda: Scenario("site_imbalance", 3.0, START, site=2),
                       "desc": "one site +3 sigma", "recall": 0.95, "delay": 40},
}


def poisson_tail(lam, k):
    term = math.exp(-lam)
    cdf = 0.0
    for i in range(k):
        cdf += term
        term *= lam / (i + 1)
    return 1.0 - cdf


def per_kind_budget(n_tests, k, fpr_td, n_kinds=4):
    lo, hi = 0.0, 50.0
    for _ in range(60):
        mid = 0.5 * (lo + hi)
        lo, hi = (mid, hi) if poisson_tail(mid, k) <= fpr_td else (lo, mid)
    return lo / n_tests / n_kinds


def make_detector(over, tests=None):
    p = dict(OFF)
    p.update(over)
    return Detector(tests or ONE, p)


def h0_run(over, n_td, seed=0):
    det = make_detector(over)
    rng = random.Random(seed)
    active = onsets = 0
    prev = False
    for td in range(n_td):
        for s in range(1, SITES + 1):
            det.update("t#p", s, rng.gauss(0.0, 1.0), td)
        on = det.end_touchdown()["n_alerts"] > 0
        active += on
        onsets += on and not prev
        prev = on
    return active, onsets


def h1_run(over, factory, reps, horizon=150, seed=100):
    delays = []
    pre = 0
    for r in range(reps):
        det = make_detector(over)
        rng = random.Random(seed + r)
        scen = factory()
        found = None
        for td in range(horizon):
            for s in range(1, SITES + 1):
                x = scen.apply(td, "t#p", s, rng.gauss(0.0, 1.0), 0.0, 1.0)
                det.update("t#p", s, x, td)
            if det.end_touchdown()["n_alerts"] > 0:
                if td >= START:
                    found = (td - START + 1) * SITES
                    break
                pre += 1
        if found is not None:
            delays.append(found)
    return len(delays) / reps, (statistics.median(delays) if delays else None), pre


def tail_fit(points, target):
    pts = [(x, math.log(f)) for x, f, ev in points if f > 0 and ev >= 3]
    if len(pts) < 2:
        return None
    mx = sum(p[0] for p in pts) / len(pts)
    my = sum(p[1] for p in pts) / len(pts)
    sxx = sum((p[0] - mx) ** 2 for p in pts)
    if sxx == 0:
        return None
    slope = sum((p[0] - mx) * (p[1] - my) for p in pts) / sxx
    if slope >= 0:
        return None
    return (math.log(target) - (my - slope * mx)) / slope


def sweep_kind(kind, target, n_td, reps):
    spec = KINDS[kind]
    extras = spec.get("extra", (None, [None]))
    rows = []
    for ev_val in extras[1]:
        base = {} if extras[0] is None else {extras[0]: ev_val}
        pts = []
        for x in spec["grid"]:
            over = dict(base)
            over[spec["param"]] = x
            active, onsets = h0_run(over, n_td)
            recall, delay, pre = h1_run(over, spec["scen"], reps)
            pts.append((x, active / n_td, active))
            rows.append({"extra": ev_val, "x": x, "frac": active / n_td, "onsets": onsets, "recall": recall, "delay": delay, "pre": pre})
        need = tail_fit(pts, target)
        for r in rows:
            if r["extra"] == ev_val:
                r["need"] = need
    return rows


def print_sweep(kind, rows, target):
    spec = KINDS[kind]
    extra = spec.get("extra", (None,))[0]
    print(f"\n[{kind}] {spec['desc']} | sweep {spec['param']}" + (f" x {extra}" if extra else "") + f" | target active-fraction <= {target:.1e}")
    print(f"{'extra':>7} {spec['param']:>10} {'H0 active frac':>15} {'H0 onsets':>10} {'recall':>7} {'delay(DUT)':>11} {'extrapolated ' + spec['param'] + ' for target':>34}")
    seen = set()
    for r in rows:
        first = r["extra"] not in seen
        seen.add(r["extra"])
        need = "" if not first else ("n/a" if r["need"] is None else f"{r['need']:.2f}")
        d = "-" if r["delay"] is None else f"{r['delay']:.0f}"
        print(f"{'' if r['extra'] is None else r['extra']:>7} {r['x']:>10} {r['frac']:>15.2e} {r['onsets']:>10d} {r['recall']:>7.2f} {d:>11} {need:>34}")


def choose(rows, spec):
    best = None
    for extra in {r["extra"] for r in rows}:
        need = next(r["need"] for r in rows if r["extra"] == extra)
        if need is None:
            continue
        x = math.ceil(need * 10) / 10.0
        over = {} if extra is None else {spec.get("extra", (None,))[0]: extra}
        over[spec["param"]] = x
        recall, delay, _ = h1_run(over, spec["scen"], 100)
        score = (recall, -(delay if delay is not None else 1e9))
        if best is None or score > best[0]:
            best = (score, over, recall, delay)
    return best


def cmd_sweep(a, write=False):
    n_tests = a.n_tests
    target = per_kind_budget(n_tests, 3, TARGET_FPR_PER_DUT * SITES)
    print(f"budget: {n_tests} monitored tests, verdict needs >=3 active tests in a pin group, target <= 1 false verdict per {int(1 / TARGET_FPR_PER_DUT)} DUTs")
    print(f"=> per-detector steady-state active fraction per stream must be <= {target:.2e}  (H0 run: {a.h0_td} touchdowns, H1: {a.reps} replicates)")
    chosen = {}
    for kind in KINDS:
        rows = sweep_kind(kind, target, a.h0_td, a.reps)
        print_sweep(kind, rows, target)
        best = choose(rows, KINDS[kind])
        if best:
            chosen.update(best[1])
            print(f"  -> chosen {best[1]}  recall={best[2]:.2f}  median delay={best[3]} DUTs")
        else:
            print("  -> no threshold reaches the target with usable evidence; keep current default")
    if write:
        with open(BASELINE) as f:
            data = json.load(f)
        data.setdefault("params", {}).update(chosen)
        with open(BASELINE, "w") as f:
            json.dump(data, f, separators=(",", ":"))
        print("\nwrote params to", BASELINE, chosen)


def load_tests(limit=None):
    with open(BASELINE) as f:
        ts = json.load(f)["tests"]
    items = [(k, (v["mu"], v["sigma"])) for k, v in ts.items() if v["monitor"]]
    return dict(items[:limit] if limit else items)


def run_stream(det, stream, start=None):
    first = None
    false = 0
    t_total = 0.0
    n_td = 0
    for td, batch in stream:
        t0 = time.perf_counter()
        for key, site, x in batch:
            det.update(key, site, x, td)
        v = det.end_touchdown()
        t_total += time.perf_counter() - t0
        n_td += 1
        if v["anomaly"]:
            if start is None or td < start:
                false += 1
            elif first is None:
                first = td - start + 1
    return first, false, t_total / max(n_td, 1)


def cmd_verify(a):
    clean_tests = load_tests(a.clean_tests)
    print(f"clean replay uses {len(clean_tests)} tests, injection uses {a.n_tests} (from baseline.json, monitor=true)")
    _, false, per_td = run_stream(Detector.load(), generate(clean_tests, a.clean_td, SITES, (), seed=7))
    tests = load_tests(a.n_tests)
    keys = list(tests)
    dut = a.clean_td * SITES
    print(f"\nclean replay: {a.clean_td} touchdowns ({dut} DUTs) -> false verdicts={false} (target <= {dut * TARGET_FPR_PER_DUT:.2f}) | {per_td * 1000:.1f} ms per touchdown")
    inj = keys[:20]
    cases = [
        ("mean_shift", Scenario("mean_shift", 3.0, START, inj), 0.95, 20), ("mean_shift", Scenario("mean_shift", 5.0, START, inj), 0.95, 12),
        ("variance_change", Scenario("variance_change", 2.0, START, inj), 0.90, 30), ("mean_drift", Scenario("mean_drift", 0.2, START, inj), 0.90, 80),
        ("site_imbalance", Scenario("site_imbalance", 3.0, START, inj, site=2), 0.95, 40),
        ("outlier_burst", Scenario("outlier_burst", 9.0, START, inj, site=4), 0.95, 8),
    ]
    print(f"\ninjection into {len(inj)} tests of pin group '{keys[0].rpartition('#')[2]}' ({a.reps} replicates, horizon {a.horizon} touchdowns)")
    print(f"{'scenario':18s} {'magnitude':>9} {'recall':>7} {'median delay(DUT)':>18} {'pre-start false':>16} {'target recall/delay':>21}")
    for kind, scen, t_rec, t_del in cases:
        delays = []
        pre = 0
        for r in range(a.reps):
            first, false, _ = run_stream(Detector.load(), generate(tests, a.horizon, SITES, (scen,), seed=50 + r), start=START)
            pre += false
            if first is not None:
                delays.append(first * SITES)
        rec = len(delays) / a.reps
        med = statistics.median(delays) if delays else None
        ok = "PASS" if rec >= t_rec and med is not None and med <= t_del else "below"
        print(f"{kind:18s} {scen.mag:>9} {rec:>7.2f} {'-' if med is None else int(med):>18} {pre:>16d} {f'{t_rec:.2f} / <={t_del}':>21}  {ok}")
    det = Detector.load()
    lat = []
    for td, batch in generate(tests, 30, SITES, (), seed=3):
        for key, site, x in batch:
            t0 = time.perf_counter_ns()
            det.update(key, site, x, td)
            lat.append(time.perf_counter_ns() - t0)
        det.end_touchdown()
    lat.sort()
    print(f"\nupdate() latency: p50={lat[len(lat) // 2] / 1000:.1f} us  p99={lat[int(len(lat) * 0.99)] / 1000:.1f} us  max={lat[-1] / 1000:.0f} us  (n={len(lat)})")


def cmd_replay(_):
    det = Detector.load()
    data = list(read_tests(DEFAULT_CSV))
    n = len(data[0][1])
    print(f"replaying offline CSV: {len(data)} tests, {n} DUTs, {SITES} sites (site = DUT index % {SITES} + 1)")
    for td in range(n // SITES):
        for key, vals in data:
            for s in range(SITES):
                det.update(key, s + 1, vals[td * SITES + s], td)
        v = det.end_touchdown()
        kinds = {}
        for (_, kind, _), _al in det._active.items():
            kinds[kind] = kinds.get(kind, 0) + 1
        print(f"td {td:2d} (DUT {td * SITES + 1:2d}-{td * SITES + SITES:2d}) anomaly={str(v['anomaly']):5s} active={v['n_alerts']:4d} {kinds}")


def main():
    ap = argparse.ArgumentParser(description="Calibrate and evaluate the anomaly detector")
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("sweep", "calibrate"):
        sp = sub.add_parser(name)
        sp.add_argument("--n-tests", type=int, default=3029)
        sp.add_argument("--h0-td", type=int, default=30000)
        sp.add_argument("--reps", type=int, default=100)
    sp = sub.add_parser("verify")
    sp.add_argument("--n-tests", type=int, default=300)
    sp.add_argument("--clean-tests", type=int, default=3029)
    sp.add_argument("--clean-td", type=int, default=2500)
    sp.add_argument("--reps", type=int, default=10)
    sp.add_argument("--horizon", type=int, default=100)
    sub.add_parser("replay")
    a = ap.parse_args()
    if a.cmd == "sweep":
        cmd_sweep(a)
    elif a.cmd == "calibrate":
        cmd_sweep(a, write=True)
    elif a.cmd == "verify":
        cmd_verify(a)
    else:
        cmd_replay(a)


if __name__ == "__main__":
    main()
