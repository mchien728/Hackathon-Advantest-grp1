import json
import os
import re

import numpy as np

_PREFIX = re.compile(r"^\d+_")


def normalize(name):
    return _PREFIX.sub("", str(name), count=1)


class SensorPredictor:
    """Numpy-only inference for the six temperature-sensor models; never imports sklearn."""

    def __init__(self):
        self.models = {}
        self.load_error = None
        self.keys = []
        self.key_index = {}

    @classmethod
    def load(cls, path=None):
        p = cls()
        if path is None:
            path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "model", "sensors")
        try:
            man = json.load(open(os.path.join(path, "manifest.json"), encoding="utf-8"))
            for s, m in man["sensors"].items():
                z = np.load(os.path.join(path, m["file"]), allow_pickle=False)
                kind = str(z["kind"])
                if kind == "ridge":
                    impl = {"kind": kind, "w": z["w"], "b": float(z["b"])}
                elif kind == "hgb":
                    impl = {"kind": kind, **{k: z[k] for k in ("roots", "feature", "threshold", "left", "right", "value", "is_leaf", "missing_left")}, "baseline": float(z["baseline"])}
                else:
                    raise ValueError(f"unknown model kind {kind}")
                impl.update(target=m["target"], model=m["model"], features=list(m["features"]))
                if kind == "ridge" and len(impl["w"]) != len(impl["features"]):
                    raise ValueError(f"sensor {s}: coefficient count does not match feature count")
                p.models[int(s)] = impl
            seen = {}
            for s in sorted(p.models):
                for f in p.models[s]["features"]:
                    seen.setdefault(f, len(seen))
            p.keys, p.key_index = list(seen), seen
            for s, m in p.models.items():
                m["cols"] = np.array([p.key_index[f] for f in m["features"]], dtype=np.int64)
        except Exception as e:
            p.models, p.keys, p.key_index = {}, [], {}
            p.load_error = f"{type(e).__name__}: {e}"
        return p

    def info(self):
        return {"sensors": {s: {"target": m["target"], "model": m["model"], "n_features": len(m["features"])} for s, m in self.models.items()},
                "load_error": self.load_error}

    def required(self, sensor):
        return self.models[sensor]["features"]

    def target(self, sensor):
        return self.models[sensor]["target"]

    def predict(self, sensor, x):
        m = self.models[sensor]
        x = np.asarray(x, dtype=np.float64)
        if x.shape != (len(m["features"]),):
            raise ValueError(f"sensor {sensor} needs {len(m['features'])} values, got shape {x.shape}")
        if not np.all(np.isfinite(x)):
            raise ValueError(f"sensor {sensor}: input contains NaN or inf")
        if m["kind"] == "ridge":
            return float(np.dot(x, m["w"]) + m["b"])
        idx = m["roots"].copy()
        leaf = m["is_leaf"]
        feat, thr, left, right = m["feature"], m["threshold"], m["left"], m["right"]
        while True:
            done = leaf[idx]
            if done.all():
                break
            go_left = x[feat[idx]] <= thr[idx]
            idx = np.where(done, idx, np.where(go_left, left[idx], right[idx]))
        return float(m["baseline"] + m["value"][idx].sum())
