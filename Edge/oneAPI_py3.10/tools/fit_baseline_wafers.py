import argparse
import json
import os
import sys
import time

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "bin"))
sys.path.insert(0, os.path.join(ROOT, "tools"))
from fit_baseline import fit_values  # noqa: E402
from wafer_data import load_all, load_labels  # noqa: E402

DEFAULT_OUT = os.path.join(ROOT, "bin", "model", "baseline.json")


def pooled_center_scale(cube):
    flat = cube.reshape(-1, cube.shape[2])
    mu = np.median(flat, 0)
    sd = 1.4826 * np.median(np.abs(flat - mu), 0)
    return mu, np.where(sd < 1e-12, flat.std(0) + 1e-12, sd)


def wafer_offsets(cube, mu, sd):
    return np.array([np.median((w - mu) / sd) for w in cube])


def fit_from_wafers(wafers, keys):
    cube = np.stack([w["values"] for w in wafers])
    mu0, sd0 = pooled_center_scale(cube)
    off = wafer_offsets(cube, mu0, sd0)
    scale = np.array([np.median(np.abs((w - mu0) / sd0 - o)) / 0.6745 for w, o in zip(cube, off)])
    ref = float(np.median(scale))
    resid = mu0[None, None, :] + (cube - mu0[None, None, :] - off[:, None, None] * sd0[None, None, :]) * (ref / scale)[:, None, None]
    tests, reasons = {}, {}
    for j, key in enumerate(keys):
        tests[key], reason = fit_values(resid[:, :, j].ravel().tolist())
        if reason:
            reasons[reason] = reasons.get(reason, 0) + 1
    zw = np.stack([((w - mu0) / sd0 - o) / s for w, o, s in zip(cube, off, scale)])
    between = zw.mean(1).std(0)
    return tests, reasons, off, float(np.median(between)), scale


def main():
    ap = argparse.ArgumentParser(description="Fit per-test baseline from the labeled Normal wafers (removes each wafer's common offset)")
    ap.add_argument("--data", required=True, help="folder with A12345_Wxx_RawResult.csv")
    ap.add_argument("--labels", required=True, help="TrainDataInfo.txt")
    ap.add_argument("--out", default=DEFAULT_OUT)
    ap.add_argument("--exclude", default="", help="comma list of wafer numbers to leave out (for leave-one-out)")
    a = ap.parse_args()
    t0 = time.perf_counter()
    labels = load_labels(a.labels)
    skip = {int(x) for x in a.exclude.split(",") if x}
    wafers = load_all(a.data)
    t_load = time.perf_counter() - t0
    normal = [n for n, lab in labels.items() if lab == "Normal" and n not in skip]
    keys = wafers[normal[0]]["keys"]
    t1 = time.perf_counter()
    tests, reasons, off, between, scale = fit_from_wafers([wafers[n] for n in normal], keys)
    t_fit = time.perf_counter() - t1
    params = {}
    if os.path.exists(a.out):
        params = json.load(open(a.out)).get("params", {})
    monitored = sum(1 for t in tests.values() if t["monitor"])
    meta = {"source": f"{len(normal)} Normal wafers", "wafers": normal, "n_tests": len(tests), "n_monitored": monitored,
            "excluded": reasons, "wafer_offset_sd": round(float(off.std()), 3), "residual_between_wafer_sd": round(between, 3)}
    os.makedirs(os.path.dirname(a.out), exist_ok=True)
    with open(a.out, "w") as f:
        json.dump({"version": 2, "meta": meta, "tests": tests, "params": params}, f, separators=(",", ":"))
    print(f"wafers={len(normal)} tests={len(tests)} monitored={monitored} excluded={reasons}")
    print(f"wafer noise scale range {scale.min():.3f}-{scale.max():.3f} (median {np.median(scale):.3f})")
    print(f"wafer offset sd={off.std():.3f} sigma; residual between-wafer sd of test mean={between:.3f} sigma (pure sampling noise would be ~0.09)")
    print(f"load {t_load:.1f}s  fit {t_fit:.1f}s  wrote {os.path.normpath(a.out)} ({os.path.getsize(a.out) / 1024:.0f} KB)")


if __name__ == "__main__":
    main()
