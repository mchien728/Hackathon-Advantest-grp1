import json
import math
import os
import re

DEFAULTS = {
    "warmup_n": 40, "z_out": 6.0, "z_clip": 4.0, "var_clip": 3.0,
    "cusum_k": 0.5, "cusum_h": 12.3,
    "ewma_lambda": 0.05, "ewma_L": 9.0,
    "drift_w": 30, "drift_min": 10, "drift_thr": 4.7,
    "site_ws": 20, "site_min": 10, "site_thr": 4.6, "site_persist": 3,
    "group_k": 3, "hard_ratio": 3.0,
    "sigma_infl_base": 0.5, "sigma_infl_warm": 2.0, "mismatch_z": 6.0, "mismatch_n": 4,
    "ewma_L_cls": 6.0, "site_thr_cls": 3.7, "scale_min": 0.6, "scale_max": 1.6, "off_tds": 2, "off_min_n": 300, "die_out_k": 3,
    "cls_group_min": 30, "cls_var_min": 20, "cls_site_min": 20, "cls_yield_min": 0.8, "cls_yield_min_dev": 20, "cls_ignore_bins": (3,),
}
_PREFIX = re.compile(r"^\d+_")
_INF = float("inf")


def normalize_key(key):
    return _PREFIX.sub("", str(key), count=1)


def group_of(key):
    return key.rpartition("#")[0].rpartition(".")[0] or "-"


def _median(sorted_vals):
    n = len(sorted_vals)
    mid = n // 2
    return sorted_vals[mid] if n % 2 else 0.5 * (sorted_vals[mid - 1] + sorted_vals[mid])


def robust_stats(vals):
    s = sorted(vals)
    mu = _median(s)
    sigma = 1.4826 * _median(sorted(abs(v - mu) for v in vals))
    if sigma < 1e-12:
        mean = sum(vals) / len(vals)
        return mean, math.sqrt(sum((v - mean) ** 2 for v in vals) / max(len(vals) - 1, 1))
    for _ in range(3):
        core = [v for v in vals if abs(v - mu) <= 3.0 * sigma]
        if len(core) < 3:
            break
        mu = sum(core) / len(core)
        sigma = math.sqrt(sum((v - mu) ** 2 for v in core) / (len(core) - 1)) / 0.9866
    return mu, sigma


class _State:
    __slots__ = ("key", "mu", "inv", "ok", "warm", "cp", "cn", "cus_on", "ev", "ev_on", "last", "td",
                 "dn", "dsy", "dsxy", "dbuf", "dpos", "drift_on", "rings", "run", "site_on", "probe", "grp", "runc", "wb")

    def __init__(self, key, drift_w, mu=None, sigma=None, ok=False):
        self.key = key
        self.grp = group_of(key)
        self.mu = mu
        self.inv = 1.0 / sigma if sigma else 1.0
        self.ok = ok
        self.warm = None
        self.cp = self.cn = 0.0
        self.cus_on = self.ev_on = self.drift_on = False
        self.ev = 1.0
        self.last = {}
        self.td = []
        self.dn = self.dpos = 0
        self.dsy = self.dsxy = 0.0
        self.dbuf = [0.0] * drift_w
        self.rings = {}
        self.run = {}
        self.site_on = set()
        self.runc = {}
        self.wb = False
        self.probe = None


class Detector:
    def __init__(self, tests=None, params=None):
        p = dict(DEFAULTS)
        if params:
            p.update(params)
        self.p = p
        self._base = {normalize_key(k): v for k, v in (tests or {}).items()}
        self._st = {}
        self._kc = {}
        self._active = {}
        self._touched = []
        self._outl = []
        self._seq = 0
        self.skipped = 0
        self.load_error = None
        self._h = p["cusum_h"]
        self._k = p["cusum_k"]
        self._cap = 2.0 * self._h
        self._ucl = 1.0 + p["ewma_L"] * math.sqrt(2.0 * p["ewma_lambda"] / (2.0 - p["ewma_lambda"]))
        self._ev_off = 1.0 + 0.5 * (self._ucl - 1.0)
        self._ucl_cls = 1.0 + p["ewma_L_cls"] * math.sqrt(2.0 * p["ewma_lambda"] / (2.0 - p["ewma_lambda"]))
        self._new_wafer()

    def _new_wafer(self):
        self._off = 0.0
        self._scale = 1.0
        self._off_td = 0
        self._zs = []
        self._tdn = 0
        self._fired = {"mean_shift": {}, "mean_drift": {}, "variance_change": {}, "site_imbalance": {}, "variance_cls": {}, "site_cls": {}}
        self._dies = {}
        self._ndev = self._nfail = self._nsys = 0
        self._gacc = {}
        self._gser = {}
        self._onset = {}

    @classmethod
    def load(cls, path=None):
        if path is None:
            path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "model", "baseline.json")
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return cls(data.get("tests"), data.get("params"))
        except (OSError, ValueError, AttributeError, TypeError) as e:
            det = cls()
            det.load_error = str(e)
            return det

    def _new_state(self, key):
        b = self._base.get(key)
        if b is None:
            st = _State(key, self.p["drift_w"])
            st.warm = []
        else:
            sigma = float(b.get("sigma", 0.0))
            ok = bool(b.get("monitor", True)) and sigma > 1e-12
            infl = 1.0 + self.p["sigma_infl_base"] / math.sqrt(max(int(b.get("n", 80)), 1))
            st = _State(key, self.p["drift_w"], float(b.get("mu", 0.0)), sigma * infl if ok else 1.0, ok)
            st.wb = True
            if ok and self.p["mismatch_n"] > 0:
                st.probe = []
        self._st[key] = st
        return st

    def _finish_warmup(self, st):
        mu, sigma = robust_stats(st.warm)
        infl = 1.0 + self.p["sigma_infl_warm"] / math.sqrt(len(st.warm))
        st.warm = None
        if sigma > 1e-12:
            st.mu, st.inv, st.ok = mu, 1.0 / (sigma * infl), True

    def _baseline_mismatch(self, st):
        probe, st.probe = st.probe, None
        zs = [(x - st.mu) * st.inv for x in probe]
        limit = self.p["mismatch_z"]
        if max(sum(1 for z in zs if z > limit), sum(1 for z in zs if z < -limit)) < len(probe) - 1:
            return False
        for k in [k for k in self._active if k[0] == st.key]:
            del self._active[k]
        fresh = _State(st.key, self.p["drift_w"])
        fresh.warm = list(probe)
        self._st[st.key] = fresh
        st.td = []
        return True

    def _raise(self, key, kind, site, score, seq):
        a = {"kind": kind, "test": key, "site": site, "score": score, "seq": seq}
        self._active[(key, kind, site)] = a
        return dict(a)

    def _clear(self, key, kind, site):
        self._active.pop((key, kind, site), None)

    def update(self, test_key, site, value, seq=0):
        key = self._kc.get(test_key)
        if key is None:
            key = self._kc[test_key] = normalize_key(test_key)
        try:
            v = float(value)
        except (TypeError, ValueError):
            self.skipped += 1
            return []
        if v != v or v == _INF or v == -_INF:
            self.skipped += 1
            return []
        st = self._st.get(key)
        if st is None:
            st = self._new_state(key)
        self._seq = seq
        if st.warm is not None:
            st.warm.append(v)
            if len(st.warm) >= self.p["warmup_n"]:
                self._finish_warmup(st)
            return []
        if not st.ok:
            return []
        p = self.p
        z = (v - st.mu) * st.inv
        if st.wb:
            if self._off_td < p["off_tds"]:
                self._zs.append(z)
            z = (z - self._off) / self._scale
        acc = self._gacc.get(st.grp)
        if acc is None:
            acc = self._gacc[st.grp] = [0, 0, 0, 0.0]
        acc[0] += 1
        acc[3] += z * z
        if z > 3.0:
            acc[1] += 1
        elif z < -3.0:
            acc[2] += 1
        if st.probe is not None:
            st.probe.append(v)
            if len(st.probe) >= p["mismatch_n"] and self._baseline_mismatch(st):
                return []
        out = []
        if -p["z_out"] >= z or z >= p["z_out"]:
            out.append(self._raise(key, "outlier", site, abs(z) / p["z_out"], seq))
            self._outl.append((key, site))
            gc = self._dies.setdefault((self._tdn, site), {})
            gc[st.grp] = gc.get(st.grp, 0) + 1
        clip = p["z_clip"]
        z = -clip if z < -clip else (clip if z > clip else z)
        cp = st.cp + z - self._k
        cp = 0.0 if cp < 0.0 else (self._cap if cp > self._cap else cp)
        cn = st.cn - z - self._k
        cn = 0.0 if cn < 0.0 else (self._cap if cn > self._cap else cn)
        st.cp, st.cn = cp, cn
        c = cp if cp > cn else cn
        if st.cus_on:
            if c < 0.5 * self._h:
                st.cus_on = False
                self._clear(key, "mean_shift", None)
            else:
                self._active[(key, "mean_shift", None)]["score"] = c / self._h
        elif c >= self._h:
            st.cus_on = True
            self._fired["mean_shift"].setdefault(key, 1 if cp > cn else -1)
            out.append(self._raise(key, "mean_shift", None, c / self._h, seq))
        vc = p["var_clip"]
        zv = -vc if z < -vc else (vc if z > vc else z)
        last = st.last.get(site)
        st.last[site] = zv
        if last is not None:
            ev = st.ev + p["ewma_lambda"] * (0.5 * (zv - last) * (zv - last) - st.ev)
            st.ev = ev
            if ev >= self._ucl_cls:
                self._fired["variance_cls"][key] = 1
            if st.ev_on:
                if ev < self._ev_off:
                    st.ev_on = False
                    self._clear(key, "variance_change", None)
                else:
                    self._active[(key, "variance_change", None)]["score"] = (ev - 1.0) / (self._ucl - 1.0)
            elif ev >= self._ucl:
                st.ev_on = True
                self._fired["variance_change"][key] = 1
                out.append(self._raise(key, "variance_change", None, (ev - 1.0) / (self._ucl - 1.0), seq))
        td = st.td
        if not td:
            self._touched.append(st)
        td.append((site, z))
        return out

    def _finalize(self, st, seq):
        p = self.p
        td = st.td
        st.td = []
        cnt = len(td)
        if not cnt:
            return
        key = st.key
        ws = p["site_ws"]
        rings = st.rings
        s = 0.0
        for site, z in td:
            s += z
            r = rings.get(site)
            if r is None:
                r = rings[site] = [[0.0] * ws, 0, 0, 0.0]
            if r[2] < ws:
                r[0][r[2]] = z
                r[2] += 1
                r[3] += z
            else:
                old = r[0][r[1]]
                r[3] += z - old
                r[0][r[1]] = z
                r[1] = (r[1] + 1) % ws
        m = s / cnt
        w = p["drift_w"]
        if st.dn < w:
            st.dbuf[st.dn] = m
            st.dn += 1
            st.dsy += m
            st.dsxy += st.dn * m
        else:
            old = st.dbuf[st.dpos]
            st.dsxy = st.dsxy - st.dsy + w * m
            st.dsy += m - old
            st.dbuf[st.dpos] = m
            st.dpos = (st.dpos + 1) % w
        n = st.dn
        if n >= p["drift_min"]:
            sxx = n * (n * n - 1) / 12.0
            zs = (st.dsxy - 0.5 * (n + 1) * st.dsy) / sxx * math.sqrt(sxx * cnt)
            score = abs(zs) / p["drift_thr"]
            if st.drift_on:
                if score < 0.7:
                    st.drift_on = False
                    self._clear(key, "mean_drift", None)
                else:
                    self._active[(key, "mean_drift", None)]["score"] = score
            elif score >= 1.0:
                st.drift_on = True
                self._fired["mean_drift"].setdefault(key, 1 if zs > 0 else -1)
                self._raise(key, "mean_drift", None, score, seq)
        elig = [(site, r[3] / r[2], r[2]) for site, r in rings.items() if r[2] >= p["site_min"]]
        ns = len(elig)
        if ns < 2:
            return
        tot = sum(e[1] for e in elig)
        sd = math.sqrt((1.0 + 1.0 / (ns - 1)) / min(e[2] for e in elig))
        for site, ms, _ in elig:
            stat = abs((ms - (tot - ms) / (ns - 1)) / sd)
            runc = st.runc.get(site, 0) + 1 if stat >= p["site_thr_cls"] else 0
            st.runc[site] = runc
            if runc >= p["site_persist"]:
                self._fired["site_cls"][key] = site
            score = stat / p["site_thr"]
            run = st.run.get(site, 0) + 1 if score >= 1.0 else 0
            st.run[site] = run
            if site in st.site_on:
                if score < 0.7:
                    st.site_on.discard(site)
                    self._clear(key, "site_imbalance", site)
                else:
                    self._active[(key, "site_imbalance", site)]["score"] = score
            elif run >= p["site_persist"]:
                st.site_on.add(site)
                self._fired["site_imbalance"][key] = site
                self._raise(key, "site_imbalance", site, score, seq)

    def _verdict(self):
        act = self._active
        if not act:
            return {"anomaly": False, "score": 0.0, "n_alerts": 0, "top_alerts": [], "message": ""}
        groups = {}
        best = 0.0
        for (key, _, _), a in act.items():
            pin = key.rpartition("#")[2] if "#" in key else "-"
            groups.setdefault(pin, set()).add(key)
            best = max(best, a["score"])
        pin, keys = max(groups.items(), key=lambda kv: len(kv[1]))
        anomaly = len(keys) >= self.p["group_k"] or best >= self.p["hard_ratio"]
        top = [dict(a) for a in sorted(act.values(), key=lambda a: -a["score"])[:5]]
        msg = ""
        if anomaly:
            t = top[0]
            msg = f"ANOMALY {t['kind']} {t['test']} site={t['site']} score={t['score']:.1f}; {len(keys)} tests active in pin {pin}"[:200]
        return {"anomaly": anomaly, "score": best, "n_alerts": len(act), "top_alerts": top, "message": msg}

    def end_touchdown(self):
        seq = self._seq
        for st in self._touched:
            self._finalize(st, seq)
        self._touched = []
        verdict = self._verdict()
        for key, site in self._outl:
            self._clear(key, "outlier", site)
        self._outl = []
        for g, acc in self._gacc.items():
            if acc[0]:
                n = acc[0]
                self._gser.setdefault(g, []).append((self._tdn + 1, acc[1] / n, acc[2] / n, acc[3] / n))
                acc[0] = acc[1] = acc[2] = 0
                acc[3] = 0.0
        self._tdn += 1
        self._note_onsets()
        if self._off_td < self.p["off_tds"] and len(self._zs) >= self.p["off_min_n"]:
            self._off_td += 1
            zs = sorted(self._zs)
            self._off = _median(zs)
            self._scale = min(max(_median(sorted(abs(x - self._off) for x in zs)) / 0.6745, self.p["scale_min"]), self.p["scale_max"])
            if self._off_td == 1:
                self._restart_streams()
            if self._off_td >= self.p["off_tds"]:
                self._zs = []
        return verdict

    def _restart_streams(self):
        for st in self._st.values():
            if st.ok and st.warm is None:
                st.cp = st.cn = 0.0
                st.cus_on = st.ev_on = st.drift_on = False
                st.ev = 1.0
                st.last = {}
                st.td = []
                st.dn = st.dpos = 0
                st.dsy = st.dsxy = 0.0
                st.rings = {}
                st.run = {}
                st.runc = {}
                st.site_on = set()
        self._active = {k: a for k, a in self._active.items() if k[1] == "outlier"}
        self._touched = []

    def update_device(self, site, passed, sbin=None):
        self._ndev += 1
        if not passed:
            if sbin in self.p["cls_ignore_bins"]:
                self._nsys += 1
            else:
                self._nfail += 1

    def die_flags(self):
        td = self._tdn - 1
        return {site: max(gc.values()) for (t, site), gc in self._dies.items() if t == td and gc}

    def die_detail(self):
        td = self._tdn - 1
        return {site: max(((g, n) for g, n in gc.items()), key=lambda gn: gn[1]) for (t, site), gc in self._dies.items() if t == td and gc}

    def evidence(self, limit=300):
        p = self.p
        focus = {g for g, c in self._group_counts().items()
                 if max(c["up"], c["down"]) >= p["cls_group_min"] or c["var"] >= p["cls_var_min"] or c["site"] >= p["cls_site_min"]}
        rows = {}

        def row(key):
            return rows.setdefault(key, {"test": key, "group": group_of(key), "kinds": [], "direction": None, "site": None})

        for kind in ("mean_drift", "mean_shift"):
            for key, d in self._fired[kind].items():
                if group_of(key) in focus:
                    r = row(key)
                    r["kinds"].append(kind)
                    r["direction"] = "up" if d > 0 else "down"
        for key in self._fired["variance_cls"]:
            if group_of(key) in focus:
                row(key)["kinds"].append("variance_change")
        for key, site in self._fired["site_cls"].items():
            if group_of(key) in focus:
                r = row(key)
                r["kinds"].append("site_imbalance")
                r["site"] = site
        return sorted(rows.values(), key=lambda r: (r["group"], r["test"]))[:limit]

    def _group_counts(self):
        first = {}
        for m in ("mean_drift", "mean_shift"):
            first.update(self._fired[m])
        groups = {}

        def slot(key):
            return groups.setdefault(group_of(key), {"up": 0, "down": 0, "var": 0, "site": 0, "sites": {}})

        for k, d in first.items():
            slot(k)["up" if d > 0 else "down"] += 1
        for k in self._fired["variance_cls"]:
            slot(k)["var"] += 1
        for k, site in self._fired["site_cls"].items():
            g = slot(k)
            g["site"] += 1
            g["sites"][site] = g["sites"].get(site, 0) + 1
        return groups

    def _site_counts(self, group):
        return self._group_counts().get(group, {}).get("sites", {})

    def _features(self):
        p = self.p
        groups = self._group_counts()
        trend = {g for g, c in groups.items() if max(c["up"], c["down"]) >= p["cls_group_min"]}
        bad = sum(1 for gc in self._dies.values() if any(n >= p["die_out_k"] for g, n in gc.items() if g not in trend))
        best = lambda field: max(groups.items(), key=lambda kv: kv[1][field], default=("-", {field: 0}))
        gu, cu = best("up")
        gd, cd = best("down")
        gv, cv = best("var")
        gs, cs = best("site")
        ndev = self._ndev
        return {
            "groups": groups, "bad_dies": bad,
            "mean_up": cu["up"], "mean_up_group": gu, "mean_down": cd["down"], "mean_down_group": gd,
            "var_up": cv["var"], "var_group": gv, "site": cs["site"], "site_group": gs,
            "site_worst": max(cs["sites"], key=cs["sites"].get) if cs.get("sites") else None,
            "yield": 1.0 - self._nfail / ndev if ndev else None,
            "raw_yield": 1.0 - (self._nfail + self._nsys) / ndev if ndev else None,
            "devices": ndev, "systematic_fail": self._nsys, "offset": self._off, "touchdowns": self._tdn,
        }

    def _low_yield(self, f):
        return f["yield"] is not None and f["devices"] >= self.p["cls_yield_min_dev"] and f["yield"] < self.p["cls_yield_min"]

    def _labels(self, f):
        p = self.p
        out = []
        if f["site"] >= p["cls_site_min"]:
            out.append("Site unbalance")
        if max(f["mean_up"], f["mean_down"]) >= p["cls_group_min"]:
            out.append("Mean Trend Up" if f["mean_up"] >= f["mean_down"] else "Mean Trend Down")
        if f["var_up"] >= p["cls_var_min"]:
            out.append("Stdev Trend Up")
        if self._low_yield(f):
            out.append("Low yield")
        return out

    def _classify(self, f):
        labels = self._labels(f)
        return labels[0] if labels else "Normal"

    def _note_onsets(self):
        f = self._features()
        p = self.p
        marks = {"mean": max(f["mean_up"], f["mean_down"]) >= p["cls_group_min"], "var": f["var_up"] >= p["cls_var_min"],
                 "site": f["site"] >= p["cls_site_min"], "yield": self._low_yield(f)}
        for name, hit in marks.items():
            if hit and name not in self._onset:
                self._onset[name] = self._tdn

    def end_wafer(self):
        f = self._features()
        return {"mean_up": f["mean_up"], "mean_down": f["mean_down"], "var_up": f["var_up"], "site": f["site"],
                "bad_dies": f["bad_dies"], "yield": f["yield"], "offset": f["offset"], "touchdowns": f["touchdowns"],
                "devices": f["devices"], "label": self._classify(f), "labels": self._labels(f)}

    def _ramp(self, f):
        up = f["mean_up"] >= f["mean_down"]
        group = f["mean_up_group"] if up else f["mean_down_group"]
        ser = self._gser.get(group, [])
        idx = 1 if up else 2
        thr = 0.03
        hot = [r[0] for r in ser if r[idx] >= thr]
        if not hot:
            return {"onset_td": None, "duration_td": 0, "peak_frac": 0.0, "snapped_back": False, "group": group, "direction": "up" if up else "down"}
        return {"onset_td": hot[0], "duration_td": len(hot), "peak_frac": max(r[idx] for r in ser),
                "snapped_back": bool(ser) and ser[-1][idx] < thr, "group": group, "direction": "up" if up else "down"}

    def metrics(self):
        for _ in range(3):
            try:
                return self._metrics()
            except RuntimeError:
                continue
        return {"label": None, "touchdowns": self._tdn, "devices": self._ndev, "criteria": [], "groups": [], "series": {}, "series_columns": []}

    def _metrics(self):
        p = self.p
        f = self._features()
        label = self._classify(f)
        ramp = self._ramp(f)
        mean_n = max(f["mean_up"], f["mean_down"])
        yl = f["yield"]
        crit = [
            {"id": 1, "key": "wafer_offset", "name": "wafer common offset (sigma)", "value": round(f["offset"], 3), "threshold": None,
             "triggered": False, "detail": {"locked": self._off_td >= p["off_tds"]}},
            {"id": 2, "key": "mean_trend", "name": "tests with same-direction mean alarm (one subflow)", "value": mean_n,
             "threshold": p["cls_group_min"], "triggered": mean_n >= p["cls_group_min"],
             "detail": {"direction": "up" if f["mean_up"] >= f["mean_down"] else "down", "up": f["mean_up"], "down": f["mean_down"],
                        "group": f["mean_up_group"] if f["mean_up"] >= f["mean_down"] else f["mean_down_group"], "onset_td": self._onset.get("mean")}},
            {"id": 3, "key": "stdev_up", "name": "tests with rising variance (one subflow)", "value": f["var_up"],
             "threshold": p["cls_var_min"], "triggered": f["var_up"] >= p["cls_var_min"],
             "detail": {"group": f["var_group"], "onset_td": self._onset.get("var")}},
            {"id": 4, "key": "site_unbalance", "name": "tests with a persistently deviating site", "value": f["site"],
             "threshold": p["cls_site_min"], "triggered": f["site"] >= p["cls_site_min"],
             "detail": {"worst_site": f["site_worst"], "group": f["site_group"], "onset_td": self._onset.get("site"),
                        "by_site": {str(k): v for k, v in sorted(self._site_counts(f["site_group"]).items())}}},
            {"id": 5, "key": "yield", "name": "yield (systematic bins excluded)", "value": None if yl is None else round(yl, 4),
             "threshold": p["cls_yield_min"], "triggered": self._low_yield(f),
             "detail": {"raw_yield": None if f["raw_yield"] is None else round(f["raw_yield"], 4), "devices": f["devices"], "onset_td": self._onset.get("yield")}},
            {"id": 6, "key": "die_fail", "name": "dies with >=%d simultaneous 6-sigma tests in one group" % p["die_out_k"], "value": f["bad_dies"],
             "threshold": None, "triggered": False, "detail": {"rate": round(f["bad_dies"] / f["devices"], 4) if f["devices"] else None}},
            {"id": 7, "key": "ramp_shape", "name": "temporary ramp (onset touchdown)", "value": ramp["onset_td"], "threshold": None,
             "triggered": ramp["onset_td"] is not None and label.startswith("Mean"), "detail": ramp},
            {"id": 8, "key": "systematic_fail", "name": "devices failing in systematic bins", "value": f["systematic_fail"],
             "threshold": None, "triggered": False, "detail": {"bins": list(p["cls_ignore_bins"])}},
        ]
        active = sorted(f["groups"].items(), key=lambda kv: -(kv[1]["up"] + kv[1]["down"] + kv[1]["var"] + kv[1]["site"]))[:6]
        series = {g: [[r[0], round(r[1], 4), round(r[2], 4), round(r[3], 4)] for r in self._gser.get(g, [])] for g, _ in active[:3]}
        return {"label": label, "touchdowns": f["touchdowns"], "devices": f["devices"], "criteria": crit,
                "groups": [{"group": g, "up": c["up"], "down": c["down"], "var": c["var"], "site": c["site"]} for g, c in active],
                "series": series, "series_columns": ["td", "frac_up", "frac_down", "mean_sq"]}

    def info(self):
        return {"monitored_tests": sum(1 for b in self._base.values() if b.get("monitor", True)),
                "baseline_tests": len(self._base), "load_error": self.load_error}

    def reset(self, scope="lot"):
        keep = {k: st for k, st in self._st.items() if st.ok and scope != "lot" and k not in self._base}
        self._st = {k: _State(k, self.p["drift_w"], st.mu, 1.0 / st.inv, True) for k, st in keep.items()}
        self._active = {}
        self._touched = []
        self._outl = []
        self._new_wafer()
