import json
import os
import sys
import unittest

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "bin"))
sys.path.insert(0, os.path.join(HERE, "..", "tools"))
from predictor import SensorPredictor, normalize  # noqa: E402

DATA_DIR = os.path.join(HERE, "..", "..", "..", "training", "training", "Data")
FIXTURE = os.path.join(HERE, "fixtures", "sensor_reference.json")
EXPECTED_FEATURES = {1: 29, 2: 400, 3: 20, 4: 600, 5: 400, 6: 800}
TARGETS = {1: "Main.sensor1#CP", 2: "Main.sensor2#DS0", 3: "Main.sensor3#IO4", 4: "Main.sensor4#IO1", 5: "Main.sensor5#IO2", 6: "Main.sensor6#IO3"}


class SensorPredictorTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.pred = SensorPredictor.load()

    def test_loads_all_six_models_without_sklearn(self):
        self.assertIsNone(self.pred.load_error)
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
                tol = 1e-6 if s == 5 else 1e-9
                self.assertAlmostEqual(self.pred.predict(s, x), expect, delta=tol, msg=f"{dev} sensor {s}")

    @unittest.skipUnless(os.path.isdir(DATA_DIR), "training data not present")
    def test_every_feature_occurs_before_its_target(self):
        from wafer_data import load_wafer, wafer_files
        keys = load_wafer(wafer_files(DATA_DIR)[1])["keys"]
        pos = {k: i for i, k in enumerate(keys)}
        for s in self.pred.models:
            t = pos[self.pred.target(s)]
            self.assertTrue(all(pos[f] < t for f in self.pred.required(s)), f"sensor {s} uses a later test")


if __name__ == "__main__":
    unittest.main()
