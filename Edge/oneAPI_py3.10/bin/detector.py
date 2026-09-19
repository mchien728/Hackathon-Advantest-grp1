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
}
_PREFIX = re.compile(r"^\d+_")
_INF = float("inf")


def normalize_key(key):
    return _PREFIX.sub("", str(key), count=1)


def _median(sorted_vals):
    n = len(sorted_vals)
    mid = n // 2
    return sorted_vals[mid] if n % 2 else 0.5 * (sorted_vals[mid - 1] + sorted_vals[mid])


def robust_stats(vals):
    s = sorted(vals)
    med = _median(s)
    sigma = 1.4826 * _median(sorted(abs(v - med) for v in vals))
    if sigma < 1e-12:
        mean = sum(vals) / len(vals)
        sigma = math.sqrt(sum((v - mean) ** 2 for v in vals) / max(len(vals) - 1, 1))
    return med, sigma


class _State:
    __slots__ = ("key", "mu", "inv", "ok", "warm", "cp", "cn", "cus_on", "ev", "ev_on", "last", "td",
                 "dn", "dsy", "dsxy", "dbuf", "dpos", "drift_on", "rings", "run", "site_on")

    def __init__(self, key, drift_w, mu=None, sigma=None, ok=False):
        self.key = key
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
            st = _State(key, self.p["drift_w"], float(b.get("mu", 0.0)), sigma if ok else 1.0, ok)
        self._st[key] = st
        return st

    def _finish_warmup(self, st):
        mu, sigma = robust_stats(st.warm)
        st.warm = None
        if sigma > 1e-12:
            st.mu, st.inv, st.ok = mu, 1.0 / sigma, True

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
        out = []
        if -p["z_out"] >= z or z >= p["z_out"]:
            out.append(self._raise(key, "outlier", site, abs(z) / p["z_out"], seq))
            self._outl.append((key, site))
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
            out.append(self._raise(key, "mean_shift", None, c / self._h, seq))
        vc = p["var_clip"]
        zv = -vc if z < -vc else (vc if z > vc else z)
        last = st.last.get(site)
        st.last[site] = zv
        if last is not None:
            ev = st.ev + p["ewma_lambda"] * (0.5 * (zv - last) * (zv - last) - st.ev)
            st.ev = ev
            if st.ev_on:
                if ev < self._ev_off:
                    st.ev_on = False
                    self._clear(key, "variance_change", None)
                else:
                    self._active[(key, "variance_change", None)]["score"] = (ev - 1.0) / (self._ucl - 1.0)
            elif ev >= self._ucl:
                st.ev_on = True
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
                self._raise(key, "mean_drift", None, score, seq)
        elig = [(site, r[3] / r[2], r[2]) for site, r in rings.items() if r[2] >= p["site_min"]]
        ns = len(elig)
        if ns < 2:
            return
        tot = sum(e[1] for e in elig)
        sd = math.sqrt((1.0 + 1.0 / (ns - 1)) / min(e[2] for e in elig))
        for site, ms, _ in elig:
            score = abs((ms - (tot - ms) / (ns - 1)) / sd) / p["site_thr"]
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
        return verdict

    def reset(self, scope="lot"):
        keep = {k: st for k, st in self._st.items() if st.ok and scope != "lot"}
        self._st = {k: _State(k, self.p["drift_w"], st.mu, 1.0 / st.inv, True) for k, st in keep.items()}
        self._active = {}
        self._touched = []
        self._outl = []
