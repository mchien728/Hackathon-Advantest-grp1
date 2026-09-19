import json
import os
import sys
import threading
import time
import types
import unittest

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import test_sample_local as harness  # noqa: E402  (installs fake oneapi / libACSAction modules)
sys.path.insert(0, os.path.join(HERE, "..", "tools"))
from predictor import SensorPredictor  # noqa: E402
from scenario2 import Scenario2  # noqa: E402

_ROOT = os.path.join(HERE, "..", "..", "..")
DATA_DIR = os.path.join(_ROOT, "SmarTest", "training", "Data")
HAVE_DATA = os.path.isdir(DATA_DIR)


def split(key):
    suite, _, text = key.partition("#")
    return suite, text


def load_wafer(n=1):
    from wafer_data import load_wafer as lw, wafer_files
    return lw(wafer_files(DATA_DIR)[n])


@unittest.skipUnless(HAVE_DATA, "training data not present")
class Scenario2FlowTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.w = load_wafer(1)
        cls.index = {k: i for i, k in enumerate(cls.w["keys"])}
        cls.pred = SensorPredictor.load()

    def feed(self, s2, sensor, rows, skip=None):
        """Feed every test that precedes the sensor's request in flow order, one die per site."""
        target = self.index[self.pred.target(sensor)]
        for site, row in enumerate(rows, start=1):
            for j in range(target):
                key = self.w["keys"][j]
                if key == skip:
                    continue
                s2.observe(*split(key), site, self.w["values"][row, j])

    def expected(self, sensor, row):
        x = [self.w["values"][row, self.index[f]] for f in self.pred.required(sensor)]
        ref = self.w["values"][row, self.index[self.pred.reference(sensor)]] if self.pred.reference(sensor) else None
        return self.pred.predict(sensor, x, ref)

    def test_each_sensor_is_ready_at_its_request_time_and_sites_do_not_mix(self):
        rows = [0, 1, 2, 3]
        for sensor in range(1, 7):
            s2 = Scenario2(self.pred, wait_ms=50)
            s2.test_start(1)
            self.feed(s2, sensor, rows)
            res = s2.predict(sensor, [1, 2, 3, 4])
            self.assertTrue(res["ready"], f"sensor {sensor}: {res['message']}")
            for site, row in enumerate(rows, start=1):
                self.assertAlmostEqual(res["values"][site], self.expected(sensor, row), places=9)
            self.assertEqual(len({round(v, 6) for v in res["values"].values()}), 4)
            self.assertLess(res["latency_ms"], 200)

    def test_missing_feature_is_reported_not_filled(self):
        s2 = Scenario2(self.pred, wait_ms=100)
        s2.test_start(1)
        skip = self.pred.required(4)[7]
        self.feed(s2, 4, [0, 1], skip=skip)
        t0 = time.perf_counter()
        res = s2.predict(4, [1, 2])
        self.assertFalse(res["ready"])
        self.assertEqual(res["values"], {1: None, 2: None})
        self.assertIn("not_ready:1", res["message"])
        self.assertLess(time.perf_counter() - t0, 0.5)

    def test_late_measurement_is_waited_for(self):
        s2 = Scenario2(self.pred, wait_ms=1000)
        s2.test_start(1)
        late = self.pred.required(2)[-1]
        self.feed(s2, 2, [0], skip=late)
        j = self.index[late]
        threading.Timer(0.15, lambda: s2.observe(*split(late), 1, self.w["values"][0, j])).start()
        res = s2.predict(2, [1])
        self.assertTrue(res["ready"])
        self.assertGreaterEqual(res["latency_ms"], 100)
        self.assertAlmostEqual(res["values"][1], self.expected(2, 0), places=9)

    def test_new_touchdown_clears_previous_values(self):
        s2 = Scenario2(self.pred, wait_ms=20)
        s2.test_start(1)
        self.feed(s2, 1, [0])
        self.assertTrue(s2.predict(1, [1])["ready"])
        s2.test_start(2)
        self.assertFalse(s2.predict(1, [1])["ready"])

    def test_actual_and_error_are_filled_when_the_sensor_is_measured(self):
        s2 = Scenario2(self.pred, wait_ms=20)
        s2.test_start(1)
        self.feed(s2, 1, [0, 1])
        s2.predict(1, [1, 2])
        t = self.index[self.pred.target(1)]
        for site, row in ((1, 0), (2, 1)):
            s2.observe(*split(self.pred.target(1)), site, self.w["values"][row, t])
        rec = s2.state()["predictions"][-1]
        self.assertEqual(set(rec["actual"]), {"1", "2"})
        self.assertLess(abs(rec["error"]["1"]), 0.1)
        json.dumps(s2.state())


class Scenario2EdgeCaseTest(unittest.TestCase):
    def test_unknown_sensor_and_bad_sites_do_not_raise(self):
        s2 = Scenario2(SensorPredictor.load(), wait_ms=10)
        s2.test_start(1)
        res = s2.predict(9, [1, 2])
        self.assertFalse(res["ready"])
        self.assertIn("prediction 9", res["message"])
        self.assertEqual(s2.predict(1, [])["ready"], False)
        self.assertEqual(s2.predict(1, [0, 99, -1])["values"], {})

    def test_predictor_load_failure_is_reported(self):
        s2 = Scenario2(SensorPredictor.load("/nonexistent/dir"), wait_ms=10)
        res = s2.predict(1, [1])
        self.assertFalse(res["ready"])
        self.assertIn("No such file", res["message"])
        self.assertIsNotNone(s2.state()["predictor_error"])
        s2.observe("Main.Suite1", "CP", 1, 1.0)


@unittest.skipUnless(HAVE_DATA, "training data not present")
class Scenario2DeltaFlowTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.w = load_wafer(1)
        cls.index = {k: i for i, k in enumerate(cls.w["keys"])}
        cls.pred = SensorPredictor.load()

    def feed(self, s2, rows, upto, skip=None):
        for site, row in enumerate(rows, start=1):
            for j in range(upto):
                if self.w["keys"][j] != skip:
                    s2.observe(*split(self.w["keys"][j]), site, self.w["values"][row, j])

    def test_sensor5_uses_the_measured_sensor4_and_matches_the_reference(self):
        s2 = Scenario2(self.pred, wait_ms=50)
        s2.test_start(1)
        rows = [0, 1, 2, 3]
        self.feed(s2, rows, self.index[self.pred.target(5)])
        res = s2.predict(5, [1, 2, 3, 4])
        self.assertTrue(res["ready"], res["message"])
        for site, row in enumerate(rows, start=1):
            x = [self.w["values"][row, self.index[f]] for f in self.pred.required(5)]
            r = self.w["values"][row, self.index[self.pred.reference(5)]]
            self.assertAlmostEqual(res["values"][site], self.pred.predict(5, x, r), places=9)

    def test_sensor5_is_not_ready_when_the_sensor4_measurement_has_not_arrived(self):
        s2 = Scenario2(self.pred, wait_ms=60)
        s2.test_start(1)
        self.feed(s2, [0], self.index[self.pred.target(5)], skip=self.pred.reference(5))
        res = s2.predict(5, [1])
        self.assertFalse(res["ready"])
        self.assertIn("not_ready:1", res["message"])


class FakeResults:
    def __init__(self, rows):
        self.rows = rows

    def get_ResultCount(self):
        return len(self.rows)

    def query_HeadSite(self, i):
        return self.rows[i]["site"]

    def query_TestSuite(self, i):
        return self.rows[i]["suite"]

    def query_TestText(self, i):
        return self.rows[i]["text"]

    def query_Results(self, i):
        return [self.rows[i]["value"]]

    def query_XCoord(self, i):
        return -32768

    def query_YCoord(self, i):
        return -32768

    def __getattr__(self, name):
        if name.startswith(("get_", "query_")):
            return lambda *a: 0
        raise AttributeError(name)


@unittest.skipUnless(HAVE_DATA, "training data not present")
class PredictRequestThroughSampleTest(unittest.TestCase):
    def setUp(self):
        harness.FakeActionManager.reset()
        import sample
        sample.toSite = lambda v: v
        sample.toHead = lambda v: 1
        self.mon = sample.SampleMonitor()
        self.mon.s2.wait_ms = 50
        self.tc = types.SimpleNamespace(testerId="testerA", testerIP="127.0.0.1")
        self.w = load_wafer(1)

    def send_sensor1_inputs(self, rows):
        index = {k: i for i, k in enumerate(self.w["keys"])}
        self.mon.consumeTestStart(FakeResults([{"site": s} for s in range(1, len(rows) + 1)]))
        target = index[self.mon.s2.pred.target(1)]
        for j in range(target):
            suite, text = split(self.w["keys"][j])
            self.mon.consumeMultiParametric(FakeResults([{"site": s, "suite": suite, "text": text, "value": self.w["values"][r, j]} for s, r in enumerate(rows, start=1)]))

    def test_predict_request_returns_values_for_every_active_site(self):
        self.send_sensor1_inputs([0, 1, 2, 3])
        self.mon.sites = [1, 2, 3, 4]
        self.mon.consumeTPRequest(self.tc, json.dumps({"key": "predict", "data": 1}))
        msg = harness.FakeActionManager.messages["testerA"]
        self.assertTrue(msg.startswith("prediction 1: (1,"), msg)
        self.assertEqual(msg.count("("), 4)
        self.assertNotIn("not_ready", msg)
        st = self.mon.get_state()
        self.assertTrue(st["predictions"][-1]["ready"])
        json.dumps(st)

    def test_predict_request_with_missing_inputs_says_not_ready(self):
        self.mon.consumeTestStart(FakeResults([{"site": 1}]))
        self.mon.sites = [1]
        self.mon.consumeTPRequest(self.tc, json.dumps({"key": "predict", "data": "4"}))
        self.assertIn("not_ready", harness.FakeActionManager.messages["testerA"])

    def test_bad_predict_number_does_not_crash(self):
        self.mon.sites = [1]
        self.mon.consumeTPRequest(self.tc, json.dumps({"key": "predict", "data": "abc"}))
        self.assertIn("error", harness.FakeActionManager.messages["testerA"])


if __name__ == "__main__":
    unittest.main()
