import copy
import threading
import time
from collections import deque

from detector import Detector

MSG_MAX = 200
NO_COORD = -32768
DIE_COLUMNS = ["td", "site", "x", "y", "sbin", "passed", "suspect"]
_ONSET_CRITERION = {"Mean Trend Up": 2, "Mean Trend Down": 2, "Stdev Trend Up": 3, "Site unbalance": 4, "Low yield": 5}
CRIT_KEYS = {2: "mean_trend", 3: "stdev_up", 4: "site_unbalance", 5: "yield"}
PRIORITY = ("site_unbalance", "mean_trend", "stdev_up", "yield")
HEAVY = ("heatmap", "tds", "evidence")


def _valid_xy(x, y):
    return x is not None and y is not None and x != NO_COORD and y != NO_COORD


def test_key(suite, text):
    return f"{suite}#{text}"


class Scenario1:
    """Glue between machine events and the Detector; holds the dashboard state. No oneapi imports, so it runs locally."""

    def __init__(self, detector=None, max_recent=50, max_reports=10, label_stable_td=3):
        self.det = detector if detector is not None else Detector.load()
        self.label_stable_td = label_stable_td
        self._lock = threading.Lock()
        self.lot = None
        self.wafer = None
        self.td = 0
        self.totals = {"touchdowns": 0, "anomaly_touchdowns": 0}
        self.recent = deque(maxlen=max_recent)
        self.reports = deque(maxlen=max_reports)
        self._dies = []
        self._map = []
        self._prev_anomaly = False
        self._label_sent = "Normal"
        self._cand = "Normal"
        self._cand_n = 0
        self._msg = None
        self._open = False
        self._explicit = False
        self._seen_xy = set()
        self._auto_n = 0
        self._wafer_seq = 0
        self._tds = []
        self._die_n = 0
        self._archive = deque(maxlen=max_reports)

    def lot_start(self, lot_id=None):
        with self._lock:
            self.lot = lot_id
            self.totals = {"touchdowns": 0, "anomaly_touchdowns": 0}
            self.td = 0
            self._explicit = False
            self._auto_n = 0
        self.det.reset("lot")

    def wafer_start(self, wafer_id=None, auto=False):
        with self._lock:
            if not auto:
                self._explicit = True
            self.wafer = wafer_id
            self._open = False
            self._seen_xy = set()
            self.td = 0
            self._prev_anomaly = False
            self._label_sent = "Normal"
            self._cand = "Normal"
            self._cand_n = 0
            self._map = []
            self._wafer_seq += 1
            self._tds = []
            self._die_n = 0
        self.det.reset("wafer")

    def _auto_rollover(self):
        self.wafer_end()
        self._auto_n += 1
        self.wafer_start(f"auto-{self._auto_n + 1}", auto=True)
        self.td = 1

    def test_start(self, dies):
        if not self._explicit and self.wafer is None:
            self.wafer = "auto-1"
            self._wafer_seq = max(self._wafer_seq, 1)
        self.td += 1
        self._dies = [dict(d) for d in dies]

    def measurement(self, suite, text, site, value):
        if suite:
            self.det.update(test_key(suite, text), site, value, self.td)

    def test_end(self, dies):
        det = self.det
        if not self._explicit:
            xy = {(d.get("x"), d.get("y")) for d in dies if _valid_xy(d.get("x"), d.get("y"))}
            if self._seen_xy and xy & self._seen_xy:
                self._auto_rollover()
        for d in dies:
            det.update_device(d["site"], bool(d.get("passed")), d.get("sbin"))
        verdict = det.end_touchdown()
        fe = det.end_wafer()
        label = fe["label"]
        detail = det.die_detail()
        started = {d["site"]: d for d in self._dies}
        rows = []
        die_recs = []
        for d in dies:
            st = started.get(d["site"], {})
            x, y = (d.get("x"), d.get("y")) if _valid_xy(d.get("x"), d.get("y")) else (st.get("x"), st.get("y"))
            if not _valid_xy(x, y):
                x = y = None
            group, n = detail.get(d["site"], (None, 0))
            suspect = n >= det.p["die_out_k"]
            rows.append([self.td, d["site"], x, y, d.get("sbin"), bool(d.get("passed")), suspect])
            die_recs.append({"index": self._die_n + len(die_recs), "site": d["site"], "x": x, "y": y, "sbin": d.get("sbin"),
                             "passed": bool(d.get("passed")), "suspect": suspect, "outlier_tests": n, "group": group if n else None})
        with self._lock:
            self._die_n += len(die_recs)
            self._tds.append({"td": self.td, "label": label, "labels": list(fe.get("labels", [])), "anomaly": verdict["anomaly"],
                              "n_alerts": verdict["n_alerts"], "yield": fe.get("yield"), "devices": fe.get("devices"), "dies": die_recs})
            self._open = True
            self._seen_xy.update((r[2], r[3]) for r in rows if r[2] is not None and r[3] is not None)
            self._map.extend(rows)
            onset = verdict["anomaly"] and not self._prev_anomaly
            cleared = self._prev_anomaly and not verdict["anomaly"]
            self._prev_anomaly = verdict["anomaly"]
            self.totals["touchdowns"] += 1
            self.totals["anomaly_touchdowns"] += int(verdict["anomaly"])
            self.recent.append({
                "td": self.td, "time": time.time(), "anomaly": verdict["anomaly"], "onset": onset, "cleared": cleared,
                "wafer": self.wafer, "score": verdict["score"], "n_alerts": verdict["n_alerts"], "top_alerts": verdict["top_alerts"],
                "message": verdict["message"], "dies": [dict(d) for d in dies],
            })
            self.recent[-1]["label"] = label
            if label == self._cand:
                self._cand_n += 1
            else:
                self._cand, self._cand_n = label, 1
            if label != "Normal" and label != self._label_sent and self._cand_n >= self.label_stable_td:
                self._msg = f"TD{self.td}: wafer looks like {label}"[:MSG_MAX]
                self._label_sent = label

    def _die_map(self):
        rows = [list(r) for r in self._map]
        xs = [r[2] for r in rows if r[2] is not None]
        ys = [r[3] for r in rows if r[3] is not None]
        extent = {"x": [min(xs), max(xs)], "y": [min(ys), max(ys)]} if xs and ys else None
        return {"columns": DIE_COLUMNS, "rows": rows, "extent": extent}

    def lot_end(self):
        return self.wafer_end()

    def wafer_end(self):
        if not self._open:
            return None
        m = self.det.metrics()
        report = self._report(m)
        ev = self.det.evidence()
        with self._lock:
            self._open = False
            self.reports.append(report)
            self._archive.append(self._view(m, ev, copy.deepcopy(self._tds), self._wafer_id(), self.wafer, False))
            self._tds = []
            self._die_n = 0
            if report["label"] != "Normal" and report["label"] != self._label_sent:
                self._msg = f"WAFER {self.wafer}: {report['message']}"[:MSG_MAX]
        return report

    @staticmethod
    def _confidence(m):
        crit = {c["id"]: c for c in m["criteria"]}
        yl = crit.get(5, {}).get("value")
        ratios = [crit[i]["value"] / crit[i]["threshold"] for i in (2, 3, 4) if i in crit]
        if yl is not None:
            ratios.append(crit[5]["threshold"] / max(yl, 1e-6))
        worst = max(ratios, default=0.0)
        return round(worst / (1.0 + worst), 3) if (m["label"] or "Normal") != "Normal" else round(1.0 / (1.0 + worst), 3)

    def _report(self, m=None):
        m = m if m is not None else self.det.metrics()
        crit = {c["id"]: c for c in m["criteria"]}
        label = m["label"] or "Normal"
        yl = crit.get(5, {}).get("value")
        cid = _ONSET_CRITERION.get(label)
        onset = crit[cid]["detail"].get("onset_td") if cid in crit else None
        grp = m["groups"][0] if m["groups"] else None
        where = f" in {grp['group']}" if grp and label not in ("Normal", "Low yield") else ""
        parts = [label + where]
        if onset is not None:
            parts.append(f"onset TD{onset}")
        if yl is not None:
            parts.append(f"yield {yl:.1%}")
        return {"wafer": self.wafer, "label": label, "onset_td": onset, "confidence": self._confidence(m), "yield": yl,
                "n_devices": m["devices"], "message": ", ".join(parts)}

    def _wafer_id(self):
        return None if self.wafer is None else f"{max(self._wafer_seq, 1):03d}_{self.wafer}"

    def _criteria(self, m):
        p = self.det.p
        out = {}
        for c in m["criteria"]:
            key = CRIT_KEYS.get(c["id"])
            if key is None:
                continue
            d = c["detail"]
            e = {"key": key, "label": None, "value": c["value"], "threshold": c["threshold"], "triggered": bool(c["triggered"]),
                 "trigger_when": "below" if key == "yield" else "at_least", "group": d.get("group"), "direction": d.get("direction"),
                 "worst_site": d.get("worst_site"), "onset_td": d.get("onset_td"), "enough_data": True}
            if key == "mean_trend":
                e["label"] = "Mean Trend Up" if d.get("direction") == "up" else "Mean Trend Down"
            elif key == "stdev_up":
                e["label"] = "Stdev Trend Up"
            elif key == "site_unbalance":
                e["label"] = "Site unbalance"
                e["by_site"] = d.get("by_site", {})
            else:
                e["label"] = "Low yield"
                e["enough_data"] = d.get("devices", 0) >= p["cls_yield_min_dev"]
            out[key] = e
        return [out[k] for k in PRIORITY if k in out]

    def _sites(self, tds, crit):
        ignore = self.det.p["cls_ignore_bins"]
        site_c = next((c for c in crit if c["key"] == "site_unbalance"), None)
        by_site = (site_c or {}).get("by_site", {})
        stat = {}
        for t in tds:
            for d in t["dies"]:
                s = stat.setdefault(d["site"], {"site": d["site"], "dies": 0, "fail_dies": 0, "suspect_dies": 0})
                s["dies"] += 1
                s["fail_dies"] += int(not d["passed"] and d["sbin"] not in ignore)
                s["suspect_dies"] += int(d["suspect"])
        for site, s in stat.items():
            s["imbalance_tests"] = int(by_site.get(str(site), 0))
            s["worst"] = bool(site_c and site_c["triggered"] and site_c["worst_site"] == site)
        return [stat[k] for k in sorted(stat)]

    def _summary(self, m, tds, wid, wafer, current):
        crit = self._criteria(m)
        labels = [c["label"] for c in crit if c["triggered"]]
        label = m["label"] or "Normal"
        cid = _ONSET_CRITERION.get(label)
        onset = next((c["onset_td"] for c in crit if c["label"] == label), None) if cid else None
        yl = next((c["value"] for c in crit if c["key"] == "yield"), None)
        return {"id": wid, "wafer": wafer, "current": current, "label": label, "labels": labels, "headline": " + ".join(labels) or "Normal",
                "onset_td": onset, "confidence": self._confidence(m), "yield": yl, "touchdowns": m["touchdowns"], "devices": m["devices"],
                "criteria": crit, "sites": self._sites(tds, crit)}

    def _view(self, m, ev, tds, wid, wafer, current):
        v = self._summary(m, tds, wid, wafer, current)
        sites = sorted({d["site"] for t in tds for d in t["dies"]})
        cells = [[next((d["outlier_tests"] for d in t["dies"] if d["site"] == s), None) for t in tds] for s in sites]
        v["heatmap"] = {"metric": "outlier_tests", "threshold": self.det.p["die_out_k"], "tds": [t["td"] for t in tds], "sites": sites, "cells": cells}
        v["tds"] = tds
        v["evidence"] = ev
        return v

    def get_wafer(self, wafer_id=None):
        with self._lock:
            if wafer_id not in (None, "current"):
                done = next((copy.deepcopy(v) for v in self._archive if v["id"] == wafer_id), None)
                if done is not None or wafer_id != self._wafer_id():
                    return done
            tds, wid, wafer = copy.deepcopy(self._tds), self._wafer_id(), self.wafer
        if not tds:
            return None
        return self._view(self.det.metrics(), self.det.evidence(), tds, wid, wafer, True)

    def pop_message(self):
        with self._lock:
            msg, self._msg = self._msg, None
        return msg

    def get_state(self):
        try:
            m = self.det.metrics()
        except Exception:
            m = None
        error = self.det.load_error
        with self._lock:
            history = [{"td": r["td"], "label": r.get("label", "Normal")} for r in self.recent]
            finished = [{k: r[k] for k in ("wafer", "label", "onset_td", "confidence", "yield", "n_devices")} for r in self.reports]
            wafer_map = dict(self._die_map(), wafer=self.wafer)
            done = [{k: v for k, v in w.items() if k not in HEAVY} for w in self._archive]
            cur = copy.deepcopy(self._tds)
            wid, wafer = self._wafer_id(), self.wafer
        wafers = done
        if m and cur:
            try:
                wafers = done + [self._summary(m, cur, wid, wafer, True)]
            except Exception:
                pass
        return {
            "lot": self.lot, "wafer": self.wafer, "touchdown": self.td,
            "label": m["label"] if m else None, "confidence": self._confidence(m) if m else None,
            "error": error, "indicators": m["criteria"] if m else [],
            "wafer_map": wafer_map, "history": history, "finished": finished, "wafers": wafers,
        }
