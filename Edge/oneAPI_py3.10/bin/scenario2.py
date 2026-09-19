import time
from collections import deque

import numpy as np

from predictor import SensorPredictor

MAX_SITE = 64


class Scenario2:
    """Per-site measurement store and predict-request handling; no oneapi imports, so it runs locally."""

    def __init__(self, predictor=None, wait_ms=500, max_records=30):
        self.pred = predictor if predictor is not None else SensorPredictor.load()
        self.wait_ms = wait_ms
        self.td = 0
        self.store = np.full((MAX_SITE + 1, max(len(self.pred.keys), 1)), np.nan)
        self.targets = {m["target"]: s for s, m in self.pred.models.items()}
        self.records = deque(maxlen=max_records)
        self._pending = {}

    def test_start(self, td=None):
        self.td = self.td + 1 if td is None else td
        self.store.fill(np.nan)

    def observe(self, suite, text, site, value):
        key = f"{suite}#{text}"
        col = self.pred.key_index.get(key)
        if col is not None and 0 < site <= MAX_SITE:
            self.store[site, col] = value
        sensor = self.targets.get(key)
        if sensor is not None:
            rec = self._pending.get(sensor)
            if rec is not None and str(site) in rec["values"]:
                rec["actual"][str(site)] = float(value)
                p = rec["values"][str(site)]
                if p is not None:
                    rec["error"][str(site)] = float(value) - p

    def predict(self, sensor, sites):
        t0 = time.perf_counter()
        sites = [int(s) for s in sites if 0 < int(s) <= MAX_SITE]
        m = self.pred.models.get(sensor)
        if m is None:
            reason = self.pred.load_error or f"unknown sensor {sensor}"
            return self._record(sensor, "", sites, {s: None for s in sites}, {s: -1 for s in sites}, t0, f"prediction {sensor}: not_ready ({reason})"[:200])
        cols = m["cols"]
        ref_col = self.pred.key_index[m["reference"]] if m["reference"] else None
        extra_ref = ref_col is not None and ref_col not in set(cols.tolist())
        deadline = t0 + self.wait_ms / 1000.0
        while True:
            missing = {s: int(np.isnan(self.store[s, cols]).sum()) + (int(np.isnan(self.store[s, ref_col])) if extra_ref else 0) for s in sites}
            if not any(missing.values()) or time.perf_counter() >= deadline:
                break
            time.sleep(0.02)
        values = {s: self.pred.predict(sensor, self.store[s, cols], self.store[s, ref_col] if ref_col is not None else None) if not missing[s] else None for s in sites}
        parts = [f"({s},{v:.3f})" if v is not None else f"({s},not_ready:{missing[s]})" for s, v in values.items()]
        return self._record(sensor, m["target"], sites, values, missing, t0, f"prediction {sensor}: " + " ".join(parts))

    def _record(self, sensor, target, sites, values, missing, t0, message):
        rec = {"td": self.td, "time": time.time(), "sensor": sensor, "target": target,
               "values": {str(s): v for s, v in values.items()}, "actual": {}, "error": {},
               "ready": bool(sites) and all(v is not None for v in values.values()),
               "missing": int(sum(max(v, 0) for v in missing.values())), "latency_ms": round((time.perf_counter() - t0) * 1000.0, 2)}
        self.records.append(rec)
        self._pending[sensor] = rec
        return {"message": message, "ready": rec["ready"], "values": dict(values), "missing": dict(missing), "latency_ms": rec["latency_ms"]}

    def state(self):
        recs = []
        for r in list(self.records):
            c = dict(r, values=dict(r["values"]), actual=dict(r["actual"]) or None, error=dict(r["error"]) or None)
            recs.append(c)
        return {"predictions": recs, "predictor_error": self.pred.load_error}
