import argparse
import json
import multiprocessing as mp
import os
import sys
import time

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "bin"))
sys.path.insert(0, os.path.join(ROOT, "tools"))
from detector import Detector  # noqa: E402
from fit_baseline_wafers import fit_from_wafers  # noqa: E402
from wafer_data import load_all, load_labels  # noqa: E402

BASELINE = os.path.join(ROOT, "bin", "model", "baseline.json")
G = {}


def replay(w, tests, params):
    det = Detector(tests, params)
    keys, vals, site = w["keys"], w["values"], w["site"]
    n_td = len(site) // 4
    t0 = time.perf_counter()
    labels_by_td = []
    for td in range(n_td):
        rows = range(td * 4, td * 4 + 4)
        for j, key in enumerate(keys):
            col = vals[:, j]
            for r in rows:
                det.update(key, int(site[r]), col[r], td)
        for r in rows:
            det.update_device(int(site[r]), int(w["pf"][r]) == 0, int(w["sbin"][r]))
        det.end_touchdown()
        labels_by_td.append(det.end_wafer()["label"])
    feats = det.end_wafer()
    feats["first_td"] = next((i for i in range(n_td) if all(l == feats["label"] for l in labels_by_td[i:])), n_td)
    feats["secs"] = time.perf_counter() - t0
    return feats


def work(n):
    wafers, labels, params, mode = G["wafers"], G["labels"], G["params"], G["mode"]
    normal = [m for m, lab in labels.items() if lab == "Normal"]
    train = [m for m in normal if m != n] if mode != "all" else normal
    if G["train_n"]:
        train = train[:G["train_n"]]
    t0 = time.perf_counter()
    if G["train_n"] == -1:
        tests = {}
    else:
        tests, _, _, _, _ = fit_from_wafers([wafers[m] for m in train], wafers[normal[0]]["keys"])
    fit_s = time.perf_counter() - t0
    feats = replay(wafers[n], tests, params)
    feats["fit_secs"] = fit_s
    return n, feats


def main():
    ap = argparse.ArgumentParser(description="Replay the labeled training wafers through the detector and classify each wafer")
    ap.add_argument("--data", required=True)
    ap.add_argument("--labels", required=True)
    ap.add_argument("--mode", choices=("loo", "all"), default="loo", help="loo: a Normal wafer is left out of its own baseline")
    ap.add_argument("--wafers", default="", help="comma list, default all")
    ap.add_argument("--train-n", type=int, default=0, help="use only the first K Normal wafers for the baseline; -1 = no baseline (pure warm-up)")
    ap.add_argument("--procs", type=int, default=12)
    ap.add_argument("--set", action="append", default=[], help="override a detector param, e.g. --set cls_group_min=40")
    ap.add_argument("--json", default="")
    a = ap.parse_args()
    params = json.load(open(BASELINE)).get("params", {}) if os.path.exists(BASELINE) else {}
    for kv in a.set:
        k, v = kv.split("=")
        params[k] = float(v) if "." in v else int(v)
    G["wafers"], G["labels"], G["params"], G["mode"] = load_all(a.data), load_labels(a.labels), params, a.mode
    G["train_n"] = a.train_n
    todo = [int(x) for x in a.wafers.split(",") if x] or sorted(G["wafers"])
    t0 = time.perf_counter()
    with mp.get_context("fork").Pool(a.procs) as pool:
        res = dict(pool.map(work, todo, chunksize=1))
    print(f"{'W':>3s} {'truth':16s} {'predicted':16s} {'ok':>3s} {'up':>4s} {'down':>5s} {'var':>4s} {'site':>5s} {'badDie':>6s} {'yield':>6s} {'offset':>7s} {'replay s':>8s} {'1st td':>6s}")
    hit = 0
    for n in todo:
        f, truth = res[n], G["labels"][n]
        ok = f["label"] == truth
        hit += ok
        print(f"{n:>3d} {truth:16s} {f['label']:16s} {'Y' if ok else 'N':>3s} {f['mean_up']:>4d} {f['mean_down']:>5d} {f['var_up']:>4d} {f['site']:>5d} "
              f"{f['bad_dies']:>6d} {f['yield']:>6.3f} {f['offset']:>7.2f} {f['secs']:>8.1f} {f['first_td']:>6d}")
    print(f"correct {hit}/{len(todo)}   total wall {time.perf_counter() - t0:.0f}s")
    if a.json:
        json.dump(res, open(a.json, "w"), default=float)


if __name__ == "__main__":
    main()
