import csv
import glob
import os
import re

import numpy as np

INFO_COLS = ("PID", "Lot", "Wafer", "Site", "X", "Y", "PF", "SBin", "HBin", "Test Time")
_PREFIX = re.compile(r"^\d+_")
LABEL_LINE = re.compile(r"^\s*W(\d+)\s*:\s*(.+?)\s*$")


def normalize(col):
    return _PREFIX.sub("", col, count=1)


def load_wafer(path):
    with open(path, newline="") as f:
        rows = list(csv.reader(f))
    header = rows[0]
    n_info = len(INFO_COLS)
    tests = header[n_info:]
    pin_row, num_row, high_row, low_row = rows[1], rows[2], rows[3], rows[4]
    body = rows[5:]
    info = {name: [r[i] for r in body] for i, name in enumerate(INFO_COLS)}
    return {
        "path": path,
        "keys": [normalize(c) for c in tests],
        "cols": tests,
        "pin": pin_row[n_info:],
        "test_num": [int(v) if v else 0 for v in num_row[n_info:]],
        "high": np.array([float(v) if v else np.nan for v in high_row[n_info:]]),
        "low": np.array([float(v) if v else np.nan for v in low_row[n_info:]]),
        "values": np.array([[float(v) if v else np.nan for v in r[n_info:]] for r in body]),
        "site": np.array([int(v) for v in info["Site"]]),
        "x": np.array([int(v) for v in info["X"]]),
        "y": np.array([int(v) for v in info["Y"]]),
        "pf": np.array([int(v) for v in info["PF"]]),
        "sbin": np.array([int(v) for v in info["SBin"]]),
        "hbin": np.array([int(v) for v in info["HBin"]]),
        "wafer": info["Wafer"][0] if info["Wafer"] else "",
    }


def load_labels(path):
    labels = {}
    with open(path) as f:
        for line in f:
            m = LABEL_LINE.match(line)
            if m:
                text = m.group(2).strip()
                labels[int(m.group(1))] = "Low yield" if text.lower().startswith("low yield") else text
    return labels


def wafer_files(data_dir):
    out = {}
    for p in glob.glob(os.path.join(data_dir, "A12345_W*_RawResult.csv")):
        m = re.search(r"_W(\d+)_RawResult", p)
        out[int(m.group(1))] = p
    return dict(sorted(out.items()))


def load_all(data_dir):
    return {n: load_wafer(p) for n, p in wafer_files(data_dir).items()}
