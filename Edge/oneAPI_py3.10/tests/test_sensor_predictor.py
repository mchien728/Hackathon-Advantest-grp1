import json
import os
import sys
import unittest

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "bin"))
sys.path.insert(0, os.path.join(HERE, "..", "tools"))
from predictor import SensorPredictor, normalize  # noqa: E402

_ROOT = os.path.join(HERE, "..", "..", "..")
DATA_DIR = os.path.join(_ROOT, "SmarTest", "training", "Data")
FIXTURE = os.path.join(HERE, "fixtures", "sensor_reference.json")
EXPECTED_FEATURES = {1: 29, 2: 400, 3: 20, 4: 600, 5: 200, 6: 800}
TARGETS = {1: "Main.sensor1#CP", 2: "Main.sensor2#DS0", 3: "Main.sensor3#IO4", 4: "Main.sensor4#IO1", 5: "Main.sensor5#IO2", 6: "Main.sensor6#IO3"}


class SensorPredictorTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.pred = SensorPredictor.load()

    def test_loads_all_six_models_without_sklearn(self):
        self.assertIsNone(self.pred.load_error)
        self.assertEqual(self.pred.reference(5), "Main.sensor4#IO1")
        self.assertIsNone(self.pred.reference(1))
        self.assertEqual({s: len(self.pred.required(s)) for s in self.pred.models}, EXPECTED_FEATURES)
        self.assertEqual({s: self.pred.target(s) for s in self.pred.models}, TARGETS)
        self.assertNotIn("sklearn", sys.modules.get("predictor").__dict__)

    def test_feature_names_are_normalized_and_unique(self):
        self.assertEqual(normalize("100_Main.sensor1#CP"), "Main.sensor1#CP")
        for s in self.pred.models:
            f = self.pred.required(s)
            self.assertEqual(len(f), len(set(f)))
            self.assertFalse(any(x[0].isdigit() and "_" in x.split(".")[0] for x in f))

    def test_bad_input_is_rejected_not_imputed(self):
        n = len(self.pred.required(1))
        with self.assertRaises(ValueError):
            self.pred.predict(1, np.full(n, np.nan))
        x = np.zeros(n)
        x[3] = np.nan
        with self.assertRaises(ValueError):
            self.pred.predict(1, x)
        with self.assertRaises(ValueError):
            self.pred.predict(1, np.zeros(n + 1))

    def test_missing_model_dir_does_not_crash(self):
        p = SensorPredictor.load("/nonexistent/dir")
        self.assertIsNotNone(p.load_error)
        self.assertEqual(p.models, {})

    @unittest.skipUnless(os.path.isdir(DATA_DIR) and os.path.exists(FIXTURE), "training data or fixture not present")
    def test_matches_sklearn_reference_predictions(self):
        from wafer_data import load_wafer, wafer_files
        ref = json.load(open(FIXTURE))["devices"]
        cache = {}
        for dev, preds in ref.items():
            w, d = int(dev[1:3]), int(dev.split("_d")[1]) - 1
            if w not in cache:
                cache[w] = load_wafer(wafer_files(DATA_DIR)[w])
            wf = cache[w]
            index = {k: i for i, k in enumerate(wf["keys"])}
            for s, expect in preds.items():
                s = int(s)
                x = np.array([wf["values"][d, index[f]] for f in self.pred.required(s)])
                r = wf["values"][d, index[self.pred.reference(s)]] if self.pred.reference(s) else None
                self.assertAlmostEqual(self.pred.predict(s, x, r), expect, delta=1e-9, msg=f"{dev} sensor {s}")

    @unittest.skipUnless(os.path.isdir(DATA_DIR), "training data not present")
    def test_every_feature_occurs_before_its_target(self):
        from wafer_data import load_wafer, wafer_files
        keys = load_wafer(wafer_files(DATA_DIR)[1])["keys"]
        pos = {k: i for i, k in enumerate(keys)}
        for s in self.pred.models:
            t = pos[self.pred.target(s)]
            self.assertTrue(all(pos[f] < t for f in self.pred.required(s)), f"sensor {s} uses a later test")
            if self.pred.reference(s):
                self.assertLess(pos[self.pred.reference(s)], t, f"sensor {s} reference is measured later than the target")


class DeltaModelTest(unittest.TestCase):
    def test_delta_model_adds_the_measured_reference_value_and_refuses_without_it(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            np.savez(os.path.join(d, "sensor1.npz"), kind=np.array("ridge"), w=np.array([2.0, 1.0]), b=np.array(0.5))
            json.dump({"sensors": {"1": {"file": "sensor1.npz", "target": "Main.sensor2#X", "model": "Ridge", "features": ["Main.a#P", "Main.b#P"],
                                         "mode": "delta_from_sensor1", "reference": "Main.sensor1#Y"}}}, open(os.path.join(d, "manifest.json"), "w"))
            p = SensorPredictor.load(d)
            self.assertIsNone(p.load_error)
            self.assertEqual(p.reference(1), "Main.sensor1#Y")
            self.assertIn("Main.sensor1#Y", p.key_index)
            self.assertAlmostEqual(p.predict(1, [1.0, 2.0], 30.0), 2.0 * 1.0 + 2.0 + 0.5 + 30.0)
            for bad in (None, float("nan")):
                with self.assertRaises(ValueError):
                    p.predict(1, [1.0, 2.0], bad)


if __name__ == "__main__":
    unittest.main()
