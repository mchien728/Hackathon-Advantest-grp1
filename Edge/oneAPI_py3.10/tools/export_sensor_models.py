import argparse
import hashlib
import json
import os
import re
import sys

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_IN = os.path.join(ROOT, "bin", "final_models")
DEFAULT_OUT = os.path.join(ROOT, "bin", "model", "sensors")
PREFIX = re.compile(r"^\d+_")


def export_linear(bundle):
    model = bundle["model"]
    steps = dict(model.steps) if hasattr(model, "steps") else {"model": model}
    unknown = set(steps) - {"imputer", "scaler", "model"}
    if unknown:
        raise ValueError(f"unsupported pipeline steps: {sorted(unknown)}")
    est = steps["model"]
    if not hasattr(est, "coef_"):
        raise ValueError(f"unsupported estimator {type(est).__name__}")
    coef = np.asarray(est.coef_, dtype=np.float64).ravel()
    icpt = float(np.ravel(est.intercept_)[0])
    sc = steps.get("scaler", bundle.get("scaler") if not hasattr(model, "steps") else None)
    if sc is not None:
        mean = sc.mean_ if sc.with_mean else np.zeros_like(coef)
        scale = sc.scale_ if sc.with_std else np.ones_like(coef)
        w = coef / scale
        icpt = icpt - float(np.dot(mean, w))
        coef = w
    imp = steps.get("imputer")
    if imp is not None and (imp.strategy != "median" or imp.add_indicator):
        raise ValueError("unsupported imputer configuration")
    return {"kind": np.array("ridge"), "w": coef, "b": np.array(icpt)}


def export_hgb(model):
    steps = dict(model.steps) if hasattr(model, "steps") else {"model": model}
    if set(steps) - {"imputer", "model"}:
        raise ValueError(f"unsupported pipeline steps: {sorted(set(steps) - {'imputer', 'model'})}")
    hgb = steps["model"]
    if hgb.loss != "squared_error" or (hgb.is_categorical_ is not None and np.any(hgb.is_categorical_)):
        raise ValueError("unsupported HGB configuration (loss or categorical features)")
    feat, thr, left, right, val, leaf, miss, roots = [], [], [], [], [], [], [], []
    off = 0
    for it in hgb._predictors:
        if len(it) != 1:
            raise ValueError("multi-output HGB not supported")
        n = it[0].nodes
        roots.append(off)
        feat.append(n["feature_idx"].astype(np.int32))
        thr.append(n["num_threshold"].astype(np.float64))
        left.append(n["left"].astype(np.int32) + off)
        right.append(n["right"].astype(np.int32) + off)
        val.append(n["value"].astype(np.float64))
        leaf.append(n["is_leaf"].astype(bool))
        miss.append(n["missing_go_to_left"].astype(bool))
        off += len(n)
    return {"kind": np.array("hgb"), "baseline": np.array(float(np.ravel(hgb._baseline_prediction)[0])), "roots": np.array(roots, dtype=np.int32),
            "feature": np.concatenate(feat), "threshold": np.concatenate(thr), "left": np.concatenate(left), "right": np.concatenate(right),
            "value": np.concatenate(val), "is_leaf": np.concatenate(leaf), "missing_left": np.concatenate(miss)}


def main():
    ap = argparse.ArgumentParser(description="Export the Scenario 2 sklearn models to plain numpy (.npz) so the Edge container needs only numpy")
    ap.add_argument("--models", default=DEFAULT_IN)
    ap.add_argument("--out", default=DEFAULT_OUT)
    ap.add_argument("--override", action="append", default=[], metavar="SENSOR=FILE", help="use another joblib for one sensor, e.g. 5=bin/model/sensors/sensor5_delta.joblib")
    a = ap.parse_args()
    override = {int(x.split("=")[0]): x.split("=", 1)[1] for x in a.override}
    import joblib
    import sklearn
    os.makedirs(a.out, exist_ok=True)
    src_manifest = json.load(open(os.path.join(a.models, "manifest.json")))
    out = {"source": {"sklearn": sklearn.__version__, "numpy": np.__version__}, "sensors": {}}
    pending = {}
    for s in range(1, 7):
        path = override.get(s, os.path.join(a.models, f"sensor{s}.joblib"))
        b = joblib.load(path)
        arrays = export_hgb(b["model"]) if b["model_name"] == "HistGradientBoosting" else export_linear(b)
        mode = str(b.get("prediction_mode", "direct"))
        ref = PREFIX.sub("", b["reference_sensor"], count=1) if mode.startswith("delta_from") else None
        feats = [PREFIX.sub("", f, count=1) for f in b["features"]]
        if len(set(feats)) != len(feats):
            raise ValueError(f"sensor {s}: feature names collide after removing the test-number prefix")
        pending[s] = arrays
        out["sensors"][str(s)] = {"file": f"sensor{s}.npz", "target": PREFIX.sub("", b["target"], count=1), "target_original": b["target"],
                                  "model": b["model_name"], "features": feats, "features_original": list(b["features"]),
                                  "source_sha256": hashlib.sha256(open(path, "rb").read()).hexdigest(), "source_file": os.path.basename(path),
                                  "mode": mode, "reference": ref,
                                  "cv_mae": b.get("cv_mae", b.get("cv_mean_mae")), "cv_r2": b.get("cv_r2", b.get("cv_mean_r2"))}
        print(f"sensor {s}: {b['model_name'][:22]:22s} mode={mode:22s} features={len(feats):4d}")
    for s, arrays in pending.items():
        np.savez_compressed(os.path.join(a.out, f"sensor{s}.npz"), **arrays)
    json.dump(out, open(os.path.join(a.out, "manifest.json"), "w"), separators=(",", ":"))
    print("wrote", os.path.normpath(a.out))


if __name__ == "__main__":
    main()
