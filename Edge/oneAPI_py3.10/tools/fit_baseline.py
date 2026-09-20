import argparse
import csv
import json
import math
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "bin"))
from detector import robust_stats  # noqa: E402

DEFAULT_CSV = os.path.join(ROOT, "..", "..", "SmarTest", "Case_Smt870", "src", "TestCase1", "TestCase1_OfflineData.csv")
DEFAULT_OUT = os.path.join(ROOT, "bin", "model", "baseline.json")
MAX_ABS_SKEW = 1.0
MAX_ABS_KURT = 2.0
TRIM_Z = 4.5
MAX_TRIM_FRAC = 0.15


def shape(vals):
    n = len(vals)
    mean = sum(vals) / n
    m2 = sum((v - mean) ** 2 for v in vals) / n
    if m2 < 1e-24:
        return 0.0, 0.0
    m3 = sum((v - mean) ** 3 for v in vals) / n
    m4 = sum((v - mean) ** 4 for v in vals) / n
    return m3 / m2 ** 1.5, m4 / m2 ** 2 - 3.0


def read_tests(path):
    with open(path, newline="") as f:
        rows = list(csv.reader(f))
    for r in rows[1:]:
        if not r[1] or r[2] or r[3]:
            continue
        try:
            yield f"{r[0]}#{r[1]}", [float(v) for v in r[4:] if v != ""]
        except ValueError:
            continue


def fit_values(vals):
    mu, sigma = robust_stats(vals)
    n_out = 0
    skew = kurt = 0.0
    reason = None
    if sigma >= 1e-12:
        core = [v for v in vals if abs(v - mu) <= TRIM_Z * sigma]
        n_out = len(vals) - len(core)
        skew, kurt = shape(core)
    if sigma < 1e-12:
        reason = "constant"
    elif n_out > MAX_TRIM_FRAC * len(vals):
        reason = "too_many_outliers"
    elif abs(skew) > MAX_ABS_SKEW:
        reason = "skewed"
    elif abs(kurt) > MAX_ABS_KURT:
        reason = "heavy_tail"
    return {"mu": round(mu, 9), "sigma": round(sigma, 9), "n": len(vals), "n_out": n_out, "monitor": reason is None}, reason


def fit(path):
    tests = {}
    reasons = {"duplicate": 0, "too_few": 0, "constant": 0, "too_many_outliers": 0, "skewed": 0, "heavy_tail": 0}
    for key, vals in read_tests(path):
        if key in tests:
            reasons["duplicate"] += 1
            continue
        if len(vals) < 20:
            reasons["too_few"] += 1
            continue
        tests[key], reason = fit_values(vals)
        if reason:
            reasons[reason] += 1
    return tests, reasons


def main():
    ap = argparse.ArgumentParser(description="Fit per-test baseline (median / MAD) from the offline CSV")
    ap.add_argument("--csv", default=DEFAULT_CSV)
    ap.add_argument("--out", default=DEFAULT_OUT)
    args = ap.parse_args()
    tests, reasons = fit(args.csv)
    params = {}
    if os.path.exists(args.out):
        with open(args.out) as f:
            params = json.load(f).get("params", {})
    monitored = sum(1 for t in tests.values() if t["monitor"])
    meta = {"source": os.path.basename(args.csv), "n_tests": len(tests), "n_monitored": monitored, "excluded": reasons}
    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, "w") as f:
        json.dump({"version": 1, "meta": meta, "tests": tests, "params": params}, f, separators=(",", ":"))
    pct = 100.0 * (len(tests) - monitored) / max(len(tests), 1)
    print(f"tests={len(tests)} monitored={monitored} unmonitored={len(tests) - monitored} ({pct:.2f}%)")
    print("excluded:", reasons)
    print("wrote", os.path.normpath(args.out), f"({os.path.getsize(args.out) / 1024:.0f} KB)")


if __name__ == "__main__":
    main()
