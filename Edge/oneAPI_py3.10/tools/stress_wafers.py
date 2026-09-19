import argparse
import json
import multiprocessing as mp
import os
import sys

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "bin"))
sys.path.insert(0, os.path.join(ROOT, "tools"))
from eval_wafers import replay  # noqa: E402
from fit_baseline_wafers import fit_from_wafers  # noqa: E402
from wafer_data import load_all, load_labels  # noqa: E402

G = {}
SCALES = (0.0, 1.0, 0.5, 0.3, 0.2, 0.1, 0.05)
EXPECT = {"mean_up": "Mean Trend Up", "mean_down": "Mean Trend Down", "stdev_up": "Stdev Trend Up", "site": "Site unbalance"}
SITE_TDS = (1, 2, 4, 5, 7)


def group_cols(keys, name):
    return np.array([i for i, k in enumerate(keys) if k.startswith(name + ".")])


def ramp_template(w, cols, sigma, mu):
    z = (w["values"][:, cols] - mu[cols]) / sigma[cols]
    z = z - np.median((w["values"] - mu) / sigma)
    slope = np.array([np.polyfit(np.arange(80), z[:, j], 1)[0] for j in range(len(cols))])
    hit = np.argsort(-np.abs(slope))[:100]
    return cols[hit], z[:, hit].mean(1)


def inject(base, kind, s, tpl, sigma, mu):
    v = base["values"].copy()
    site = base["site"]
    keys = base["keys"]
    if kind in ("mean_up", "mean_down"):
        cols, curve = tpl[kind]
        v[:, cols] += (s * curve)[:, None] * sigma[cols][None, :]
    elif kind == "stdev_up":
        cols = tpl["stdev_cols"]
        f = np.ones(20)
        f[3:7] = 1.0 + s * np.array([0.9, 2.0, 3.4, 4.6])
        m = v[:, cols].mean(0)
        for td in range(20):
            idx = np.ix_(range(td * 4, td * 4 + 4), cols)
            v[idx] = m + (v[idx] - m) * f[td]
    elif kind == "site":
        cols = tpl["site_cols"]
        for td in SITE_TDS:
            r = td * 4 + 3
            if site[r] == 4:
                v[r, cols] += -8.5 * s * sigma[cols]
    out = dict(base)
    out["values"] = v
    return out


def work(bn):
    wafers, labels, params = G["wafers"], G["labels"], G["params"]
    normal = [m for m, lab in labels.items() if lab == "Normal"]
    keys = wafers[normal[0]]["keys"]
    tests, _, _, _, _ = fit_from_wafers([wafers[m] for m in normal if m != bn], keys)
    mu = np.array([tests[k]["mu"] for k in keys])
    sigma = np.array([tests[k]["sigma"] for k in keys])
    sigma = np.where(sigma < 1e-12, 1.0, sigma)
    tpl = {"mean_up": ramp_template(wafers[14], group_cols(keys, "Main.subflow2"), sigma, mu),
           "mean_down": ramp_template(wafers[18], group_cols(keys, "Main.subflow3"), sigma, mu)}
    tpl["stdev_cols"] = group_cols(keys, "Main.subflow6")[:100]
    tpl["site_cols"] = group_cols(keys, "Main.subflow1")[:44]
    rows = []
    for kind in EXPECT:
        for s in SCALES:
            if s == 0.0 and kind != "mean_up":
                continue
            w = inject(wafers[bn], kind, s, tpl, sigma, mu)
            f = replay(w, tests, params)
            rows.append((kind if s else "control", s, bn, f["label"], f["first_td"]))
    return rows


def main():
    ap = argparse.ArgumentParser(description="Inject scaled copies of the W14/W18/W23/W1 anomaly shapes into Normal wafers and check the classifier")
    ap.add_argument("--data", required=True)
    ap.add_argument("--labels", required=True)
    ap.add_argument("--bases", default="4,6,10,12,17,20")
    ap.add_argument("--procs", type=int, default=6)
    a = ap.parse_args()
    baseline = os.path.join(ROOT, "bin", "model", "baseline.json")
    G["wafers"], G["labels"] = load_all(a.data), load_labels(a.labels)
    G["params"] = json.load(open(baseline)).get("params", {})
    bases = [int(x) for x in a.bases.split(",")]
    with mp.get_context("fork").Pool(a.procs) as pool:
        rows = [r for part in pool.map(work, bases) for r in part]
    print(f"{'anomaly':10s} {'scale':>5s} {'detected':>9s} {'mean first td':>14s}   (base Normal wafers: {bases})")
    for kind in ("control", "mean_up", "mean_down", "stdev_up", "site"):
        for s in SCALES:
            sel = [r for r in rows if r[0] == kind and r[1] == s]
            if not sel:
                continue
            want = "Normal" if kind == "control" else EXPECT[kind]
            ok = [r for r in sel if r[3] == want]
            wrong = sorted({r[3] for r in sel if r[3] != want})
            tds = [r[4] for r in ok]
            print(f"{kind:10s} {s:>5.1f} {len(ok):>4d}/{len(sel):<4d} {np.mean(tds) if tds else float('nan'):>14.1f}   wrong labels: {wrong}")


if __name__ == "__main__":
    main()
