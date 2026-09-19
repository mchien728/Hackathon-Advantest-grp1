import argparse
import json
import os
import sys
import time

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "bin"))
sys.path.insert(0, os.path.join(ROOT, "tools"))
from scenario2 import Scenario2  # noqa: E402
from wafer_data import load_wafer, wafer_files  # noqa: E402


def main():
    ap = argparse.ArgumentParser(description="Replay one training wafer through Scenario2 in the real flow order and print what the tester would receive")
    ap.add_argument("--data", required=True)
    ap.add_argument("--wafer", type=int, default=14)
    ap.add_argument("--show", type=int, default=2, help="how many touchdowns to print in detail")
    a = ap.parse_args()
    w = load_wafer(wafer_files(a.data)[a.wafer])
    keys, vals = w["keys"], w["values"]
    s2 = Scenario2(wait_ms=200)
    if s2.pred.load_error:
        sys.exit(s2.pred.load_error)
    index = {k: i for i, k in enumerate(keys)}
    err = {s: [] for s in range(1, 7)}
    lat = []
    for td in range(len(vals) // 4):
        rows = list(range(td * 4, td * 4 + 4))
        s2.test_start(td + 1)
        p = 0
        for sensor in range(1, 7):
            ti = index[s2.pred.target(sensor)]
            for j in range(p, ti):
                suite, _, text = keys[j].partition("#")
                for site, r in enumerate(rows, start=1):
                    s2.observe(suite, text, site, vals[r, j])
            res = s2.predict(sensor, [1, 2, 3, 4])
            lat.append(res["latency_ms"])
            suite, _, text = keys[ti].partition("#")
            for site, r in enumerate(rows, start=1):
                s2.observe(suite, text, site, vals[r, ti])
            rec = s2.state()["predictions"][-1]
            for site in "1234":
                err[sensor].append(abs(rec["error"][site]))
            if td < a.show:
                print(f"TD{td + 1} predict{sensor} -> tester receives: {res['message']}")
                print("        actual:    " + " ".join(f"({s},{rec['actual'][str(s)]:.3f})" for s in range(1, 5)) + "   error: " + " ".join(f"{rec['error'][str(s)]:+.3f}" for s in range(1, 5)))
            p = ti + 1
    print(f"\nwafer W{a.wafer:02d}: {len(vals) // 4} touchdowns x 6 sensors x 4 sites = {sum(len(v) for v in err.values())} predictions, all made only from tests that came before the sensor")
    print(f"{'sensor':>6s} {'mean abs error (this wafer, in-sample)':>40s} {'cross-validation MAE':>22s}")
    man = json.load(open(os.path.join(ROOT, "bin", "model", "sensors", "manifest.json")))["sensors"]
    for s in range(1, 7):
        print(f"{s:>6d} {np.mean(err[s]):>40.4f} {man[str(s)]['cv_mae']:>22.4f}")
    print(f"prediction latency per request: mean {np.mean(lat):.2f} ms, max {np.max(lat):.2f} ms (limit about 1000 ms)")
    st = s2.state()
    print("state keys:", sorted(st), "| records kept:", len(st["predictions"]), "| json size KB:", round(len(json.dumps(st)) / 1024, 1))


if __name__ == "__main__":
    main()
