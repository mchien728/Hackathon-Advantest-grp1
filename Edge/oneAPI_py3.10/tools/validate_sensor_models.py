import argparse
import glob
import hashlib
import json
import os
import sys
import warnings

import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_DIR = os.path.join(ROOT, "bin", "final_models")
EXPECTED = {1: ("100_Main.sensor1#CP", 40, 29), 2: ("120_Main.sensor2#DS0", 541, 400), 3: ("140_Main.sensor3#IO4", 1042, 20),
            4: ("160_Main.sensor4#IO1", 1543, 600), 5: ("180_Main.sensor5#IO2", 2044, 400), 6: ("200_Main.sensor6#IO3", 2545, 800)}
REQUIRED_KEYS = ("sensor_number", "target", "model_name", "feature_count", "features", "model")
SMOKE = ((1, 0), (1, 19), (5, 0), (10, 19), (25, 79))
RESULTS = []


def check(sensor, name, ok, detail=""):
    RESULTS.append((sensor, name, bool(ok), detail))
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f"  {detail}" if detail else ""))
    return ok


def describe(model):
    steps = getattr(model, "steps", None)
    if steps:
        return " -> ".join(f"{n}:{type(s).__name__}" for n, s in steps)
    return type(model).__name__


def final_estimator(model):
    steps = getattr(model, "steps", None)
    return steps[-1][1] if steps else model


def main():
    ap = argparse.ArgumentParser(description="Validate the Scenario 2 final_models folder (guide sections 11-20)")
    ap.add_argument("--models", default=DEFAULT_DIR)
    ap.add_argument("--data", required=True, help="folder with A12345_Wxx_RawResult.csv")
    a = ap.parse_args()

    import joblib
    import sklearn
    print(f"runtime: python {sys.version.split()[0]} sklearn {sklearn.__version__} joblib {joblib.__version__} numpy {np.__version__} pandas {pd.__version__}")
    print("training: scikit-learn 1.6.1, joblib 1.4.2, numpy 2.2.3, pandas 2.2.3")

    print("\n== 11. folder contents")
    files = ["manifest.json"] + [f"sensor{i}.joblib" for i in range(1, 7)]
    check(0, "all 7 files exist", all(os.path.exists(os.path.join(a.models, f)) for f in files),
          "missing: " + str([f for f in files if not os.path.exists(os.path.join(a.models, f))]))
    extra = sorted(set(os.listdir(a.models)) - set(files))
    if extra:
        print("  note: extra files:", extra)
    manifest = json.load(open(os.path.join(a.models, "manifest.json")))

    w1 = os.path.join(a.data, "A12345_W01_RawResult.csv")
    header = list(pd.read_csv(w1, nrows=0).columns)
    print(f"\ncsv header: {len(header)} columns")

    bundles = {}
    for s in range(1, 7):
        path = os.path.join(a.models, f"sensor{s}.joblib")
        print(f"\n===== sensor {s}  ({os.path.getsize(path) / 1024:.0f} KB, sha256 {hashlib.sha256(open(path, 'rb').read()).hexdigest()[:12]})")
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            try:
                b = joblib.load(path)
            except Exception as e:
                check(s, "12. joblib loads", False, repr(e)[:200])
                continue
        vw = [str(w.message)[:120] for w in caught]
        check(s, "12. joblib loads", True)
        check(s, "20. no version/serialization warning on load", not vw, "; ".join(vw))
        if not check(s, "12. required keys present", all(k in b for k in REQUIRED_KEYS), f"keys={sorted(b.keys()) if isinstance(b, dict) else type(b)}"):
            continue
        bundles[s] = b
        tgt, tidx, nfeat = EXPECTED[s]
        m = manifest[str(s)]
        check(s, "13. sensor_number matches", int(b["sensor_number"]) == s, str(b["sensor_number"]))
        check(s, "13. target matches manifest", b["target"] == m["target"] == tgt, f"{b['target']} / {m['target']}")
        check(s, "13. model_name matches manifest", b["model_name"] == m["model"], f"{b['model_name']} / {m['model']}")
        check(s, "13. feature_count == len(features) == manifest == expected",
              len(b["features"]) == b["feature_count"] == m["feature_count"] == nfeat, f"{len(b['features'])}/{b['feature_count']}/{m['feature_count']}/{nfeat}")
        feats = list(b["features"])
        check(s, "14. no duplicate features", len(feats) == len(set(feats)), f"{len(feats) - len(set(feats))} duplicates")
        missing = [f for f in feats if f not in header]
        check(s, "16. all features exist in CSV header", not missing, str(missing[:5]))
        check(s, "16. target exists and index matches expected", b["target"] in header and header.index(b["target"]) == tidx,
              f"index {header.index(b['target']) if b['target'] in header else None} vs {tidx}")
        if not missing and b["target"] in header:
            ti = header.index(b["target"])
            late = [f for f in feats if header.index(f) >= ti]
            latest = max(header.index(f) for f in feats)
            check(s, "16. every feature occurs before its target (no future data)", not late, f"latest feature idx {latest} < target {ti}; violations {late[:5]}")
        est = final_estimator(b["model"])
        n_in = getattr(b["model"], "n_features_in_", None) or getattr(est, "n_features_in_", None)
        check(s, "15. model n_features_in_ == len(features)", n_in == len(feats), f"n_features_in_={n_in}")
        info = f"structure: {describe(b['model'])}"
        if hasattr(est, "coef_"):
            info += f" | coef shape {np.shape(est.coef_)} alpha={getattr(est, 'alpha', None)}"
        if hasattr(est, "_predictors"):
            info += f" | HGB iterations={len(est._predictors)} max_iter={est.max_iter} lr={est.learning_rate} max_depth={est.max_depth} max_leaf_nodes={est.max_leaf_nodes}"
        print("  " + info)
        print("  cv:", {k: b[k] for k in ("cv_mae", "cv_rmse", "cv_r2") if k in b})

    print("\n== 17/18/19. prediction smoke tests")
    cache = {}

    def wafer(n):
        if n not in cache:
            cache[n] = pd.read_csv(os.path.join(a.data, f"A12345_W{n:02d}_RawResult.csv"), skiprows=[1, 2, 3, 4])
        return cache[n]

    for s, b in bundles.items():
        print(f"\n-- sensor {s}")
        errs, ok_all = [], True
        for w, d in SMOKE:
            df = wafer(w)
            X = pd.DataFrame([[df.iloc[d][f] for f in b["features"]]], columns=b["features"])
            nan = int(X.isna().sum().sum())
            if nan:
                ok_all = False
                print(f"   W{w:02d} d{d + 1}: {nan} NaN inputs: {list(X.columns[X.isna().any()])[:5]}")
                continue
            with warnings.catch_warnings(record=True) as caught:
                warnings.simplefilter("always")
                p = float(b["model"].predict(X)[0])
            act = float(df.iloc[d][b["target"]])
            err = abs(p - act)
            ok_all &= bool(np.isfinite(p) and np.isfinite(err) and not caught)
            errs.append(err)
            print(f"   W{w:02d} d{d + 1:<2d}: predicted {p:.6f}  actual {act:.6f}  abs err {err:.6f}" + (f"  WARN {caught[0].message}" if caught else ""))
        check(s, "17/18. smoke predictions finite, no NaN input, no warning", ok_all and len(errs) == len(SMOKE), f"mean abs err {np.mean(errs):.6f}" if errs else "")

    print("\n== extra: in-sample MAE over all 2000 devices (optimistic; trained on these wafers)")
    for s, b in bundles.items():
        X, y = [], []
        for w in range(1, 26):
            df = wafer(w)
            X.append(df[b["features"]])
            y.append(df[b["target"]])
        X, y = pd.concat(X), pd.concat(y)
        nan = int(X.isna().sum().sum())
        p = b["model"].predict(X)
        mae = float(np.mean(np.abs(p - y.values)))
        cv = b.get("cv_mae")
        print(f"   sensor {s}: NaN inputs {nan}, in-sample MAE {mae:.6f}" + (f"  (cv_mae in bundle {cv:.6f})" if cv else ""))

    print("\n== SUMMARY")
    fails = [(s, n, d) for s, n, ok, d in RESULTS if not ok]
    for s in range(0, 7):
        r = [x for x in RESULTS if x[0] == s]
        if r:
            print(f"   {'folder' if s == 0 else f'sensor {s}'}: {sum(1 for x in r if x[2])}/{len(r)} checks passed")
    print("   OVERALL:", "PASS" if not fails else f"FAIL ({len(fails)} failed)")
    for s, n, d in fails:
        print(f"     - sensor {s}: {n}  {d}")
    sys.exit(0 if not fails else 1)


if __name__ == "__main__":
    main()
