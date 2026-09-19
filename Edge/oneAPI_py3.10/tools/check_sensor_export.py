import argparse
import json
import os
import sys
import time

import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "bin"))
from predictor import SensorPredictor  # noqa: E402

FIXTURE = os.path.join(ROOT, "tests", "fixtures", "sensor_reference.json")
FIXTURE_DEVICES = ((1, 0), (1, 19), (5, 0), (10, 19), (14, 40), (25, 79))


def main():
    ap = argparse.ArgumentParser(description="Compare the numpy predictor with the original sklearn bundles on every training device")
    ap.add_argument("--data", required=True)
    ap.add_argument("--models", default=os.path.join(ROOT, "bin", "final_models"))
    ap.add_argument("--write-fixture", action="store_true", help="store sklearn reference predictions for a few devices (used by tests without sklearn)")
    a = ap.parse_args()
    import joblib
    pred = SensorPredictor.load()
    if pred.load_error:
        sys.exit("predictor load failed: " + pred.load_error)
    bundles = {s: joblib.load(os.path.join(a.models, f"sensor{s}.joblib")) for s in range(1, 7)}
    wafers = {n: pd.read_csv(os.path.join(a.data, f"A12345_W{n:02d}_RawResult.csv"), skiprows=[1, 2, 3, 4]) for n in range(1, 26)}
    print(f"{'sensor':>6s} {'model':22s} {'devices':>7s} {'max |numpy - sklearn|':>22s} {'tol':>8s} {'ok':>4s} {'numpy ms/pred':>14s}")
    ok_all = True
    fixture = {}
    for s, b in bundles.items():
        orig = list(b["features"])
        X = np.concatenate([w[orig].to_numpy(dtype=np.float64) for w in wafers.values()])
        ref = b["model"].predict(pd.DataFrame(X, columns=orig))
        t0 = time.perf_counter()
        mine = np.array([pred.predict(s, row) for row in X])
        ms = (time.perf_counter() - t0) / len(X) * 1000.0
        diff = float(np.max(np.abs(mine - ref)))
        tol = 1e-6 if b["model_name"] == "HistGradientBoosting" else 1e-9
        ok = diff <= tol
        ok_all &= ok
        print(f"{s:>6d} {b['model_name']:22s} {len(X):>7d} {diff:>22.3e} {tol:>8.0e} {'PASS' if ok else 'FAIL':>4s} {ms:>14.3f}")
        for w, d in FIXTURE_DEVICES:
            fixture.setdefault(f"W{w:02d}_d{d + 1}", {})[str(s)] = float(b["model"].predict(pd.DataFrame(wafers[w].iloc[[d]][orig].to_numpy(), columns=orig))[0])
    if a.write_fixture:
        json.dump({"note": "sklearn 1.6.1 reference predictions for tests/test_sensor_predictor.py", "devices": fixture}, open(FIXTURE, "w"), indent=1)
        print("wrote", os.path.relpath(FIXTURE, ROOT))
    print("OVERALL:", "PASS" if ok_all else "FAIL")
    sys.exit(0 if ok_all else 1)


if __name__ == "__main__":
    main()
