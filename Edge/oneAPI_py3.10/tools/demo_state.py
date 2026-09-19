import argparse
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "bin"))
sys.path.insert(0, os.path.join(ROOT, "tools"))
from scenario1 import Scenario1  # noqa: E402
from wafer_data import wafer_files, load_wafer  # noqa: E402


def replay_states(w, s1):
    keys, vals, site = w["keys"], w["values"], w["site"]
    timeline = []
    s1.wafer_start(f"W{w['wafer']}" if w["wafer"] else None)
    for td in range(len(site) // 4):
        rows = range(td * 4, td * 4 + 4)
        s1.test_start([{"site": int(site[r]), "x": int(w["x"][r]), "y": int(w["y"][r])} for r in rows])
        for j, key in enumerate(keys):
            suite, _, pin = key.partition("#")
            for r in rows:
                s1.measurement(suite, pin, int(site[r]), vals[r, j])
        s1.test_end([{"site": int(site[r]), "x": int(w["x"][r]), "y": int(w["y"][r]), "part_id": int(r) + 1,
                      "sbin": int(w["sbin"][r]), "passed": int(w["sbin"][r]) == 1} for r in rows])
        timeline.append(s1.get_state())
    s1.wafer_end()
    timeline.append(s1.get_state())
    return timeline


def main():
    ap = argparse.ArgumentParser(description="Replay one training wafer and dump get_state()-shaped JSON (final + per-touchdown timeline) for the dashboard")
    ap.add_argument("--data", required=True)
    ap.add_argument("--wafer", type=int, default=14)
    ap.add_argument("--out", default="")
    ap.add_argument("--detail-out", default="", help="also write the get_wafer() JSON of the finished wafer")
    a = ap.parse_args()
    w = load_wafer(wafer_files(a.data)[a.wafer])
    s1 = Scenario1()
    timeline = replay_states(w, s1)
    out = {"wafer": a.wafer, "final": timeline[-1], "timeline": timeline}
    text = json.dumps(out, separators=(",", ":"))
    if a.out:
        with open(a.out, "w") as f:
            f.write(text)
    fin = timeline[-1]
    if a.detail_out and fin["wafers"]:
        with open(a.detail_out, "w") as f:
            json.dump(s1.get_wafer(fin["wafers"][-1]["id"]), f, separators=(",", ":"))
    print(f"wafer {a.wafer}: label={fin['label']} confidence={fin['confidence']}  json={len(text) / 1024:.0f} KB (one state {len(json.dumps(fin)) / 1024:.1f} KB)")
    for c in fin["indicators"]:
        print(f"  #{c['id']} {c['key']:16s} value={c['value']} threshold={c['threshold']} triggered={c['triggered']}")


if __name__ == "__main__":
    main()
