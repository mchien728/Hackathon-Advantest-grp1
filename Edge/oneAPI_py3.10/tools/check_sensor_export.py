import argparse
import json
import os
import sys
import time
import warnings

import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "bin"))
sys.path.insert(0, os.path.join(ROOT, "tools"))
from predictor import SensorPredictor  # noqa: E402

FIXTURE = os.path.join(ROOT, "tests", "fixtures", "sensor_reference.json")
FIXTURE_DEVICES = ((1, 0), (1, 19), (5, 0), (10, 19), (14, 40), (25, 79))


def predict_bundle(b, get):
    """sklearn reference prediction for a bundle; get(name) -> vector of raw values (one per die) for a feature name stored in the bundle."""
    X = np.stack([get(f) for f in b["features"]], 1)
    if not np.all(np.isfinite(X)):
        raise ValueError("NaN in inputs")
    m = b["model"]
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", UserWarning)
        if hasattr(m, "steps"):
            y = m.predict(pd.DataFrame(X, columns=b["features"]))
        else:
            if "scaler" in b:
                X = b["scaler"].transform(X)
            y = m.predict(X)
    if str(b.get("prediction_mode", "")).startswith("delta_from"):
        y = y + get(b["reference_sensor"])
    return y


def main():
    ap = argparse.ArgumentParser(description="Compare the numpy predictor with the original sklearn bundles on every training device")
    ap.add_argument("--data", required=True)
    ap.add_argument("--models", default=os.path.join(ROOT, "bin", "final_models"))
    ap.add_argument("--sensors-dir", default=None, help="exported numpy models to check (default: bin/model/sensors)")
    ap.add_argument("--override", action="append", default=[], metavar="SENSOR=FILE")
    ap.add_argument("--fixture", default=FIXTURE)
    ap.add_argument("--write-fixture", action="store_true", help="store sklearn reference predictions for a few devices (used by tests without sklearn)")
    a = ap.parse_args()
    import joblib
    pred = SensorPredictor.load(a.sensors_dir)
    if pred.load_error:
        sys.exit("predictor load failed: " + pred.load_error)
    override = {int(x.split("=")[0]): x.split("=", 1)[1] for x in a.override}
    bundles = {s: joblib.load(override.get(s, os.path.join(a.models, f"sensor{s}.joblib"))) for s in range(1, 7)}
    wafers = {n: pd.read_csv(os.path.join(a.data, f"A12345_W{n:02d}_RawResult.csv"), skiprows=[1, 2, 3, 4]) for n in range(1, 26)}
    print(f"{'sensor':>6s} {'model':22s} {'devices':>7s} {'max |numpy - sklearn|':>22s} {'tol':>8s} {'ok':>4s} {'numpy ms/pred':>14s}")
    ok_all = True
    fixture = {}
    for s, b in bundles.items():
        orig = list(b["features"])
        allrows = pd.concat(list(wafers.values()), ignore_index=True)
        get = lambda f: allrows[f].to_numpy(dtype=np.float64)
        X = np.stack([get(f) for f in orig], 1)
        ref = predict_bundle(b, get)
        refv = get(b["reference_sensor"]) if str(b.get("prediction_mode", "")).startswith("delta_from") else None
        t0 = time.perf_counter()
        mine = np.array([pred.predict(s, X[i], None if refv is None else refv[i]) for i in range(len(X))])
        ms = (time.perf_counter() - t0) / len(X) * 1000.0
        diff = float(np.max(np.abs(mine - ref)))
        tol = 1e-6 if b["model_name"] == "HistGradientBoosting" else 1e-9
        ok = diff <= tol
        ok_all &= ok
        print(f"{s:>6d} {b['model_name']:22s} {len(X):>7d} {diff:>22.3e} {tol:>8.0e} {'PASS' if ok else 'FAIL':>4s} {ms:>14.3f}")
        for w, d in FIXTURE_DEVICES:
            row = wafers[w].iloc[[d]]
            fixture.setdefault(f"W{w:02d}_d{d + 1}", {})[str(s)] = float(predict_bundle(b, lambda f: row[f].to_numpy(dtype=np.float64))[0])
    if a.write_fixture:
        json.dump({"note": "sklearn 1.6.1 reference predictions for tests/test_sensor_predictor.py", "devices": fixture}, open(a.fixture, "w"), indent=1)
        print("wrote", os.path.relpath(a.fixture, ROOT))
    print("OVERALL:", "PASS" if ok_all else "FAIL")
    sys.exit(0 if ok_all else 1)


if __name__ == "__main__":
    main()
