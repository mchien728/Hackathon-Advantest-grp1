import os
import random
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "bin"))
from detector import Detector, normalize_key  # noqa: E402

KEYS = [f"Main.S{i}#CP" for i in range(5)]
BASE = {k: {"mu": 0.0, "sigma": 1.0, "monitor": True} for k in KEYS}


def run(det, n_td, mod=None, start=0, seed=1, keys=KEYS):
    rng = random.Random(seed)
    verdicts = []
    for td in range(n_td):
        for key in keys:
            for site in (1, 2, 3, 4):
                x = rng.gauss(0.0, 1.0)
                if mod and td >= start:
                    x = mod(td - start, site, x)
                det.update(key, site, x, td)
        verdicts.append(det.end_touchdown())
    return verdicts


def kinds(verdict):
    return {a["kind"] for a in verdict["top_alerts"]}


class DetectorTest(unittest.TestCase):
    def test_normalize_key_strips_test_number(self):
        self.assertEqual(normalize_key("220_Main.Suite1#CP"), "Main.Suite1#CP")
        self.assertEqual(normalize_key("Main.Suite1#CP"), "Main.Suite1#CP")

    def test_missing_baseline_file_does_not_crash(self):
        det = Detector.load("/nonexistent/baseline.json")
        self.assertIsNotNone(det.load_error)
        self.assertEqual(det.update("a#p", 1, 1.0, 0), [])
        self.assertFalse(det.end_touchdown()["anomaly"])

    def test_corrupt_baseline_file_does_not_crash(self):
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
            f.write("{not json")
        try:
            self.assertIsNotNone(Detector.load(f.name).load_error)
        finally:
            os.unlink(f.name)

    def test_non_numeric_values_are_ignored(self):
        det = Detector(BASE)
        for bad in (float("nan"), float("inf"), None, "abc"):
            self.assertEqual(det.update(KEYS[0], 1, bad, 0), [])
        self.assertEqual(det.skipped, 4)

    def test_unseen_test_warms_up_then_flags_outlier(self):
        det = Detector()
        rng = random.Random(3)
        for i in range(39):
            self.assertEqual(det.update("new#p", 1 + i % 4, 10.0 + 0.1 * rng.gauss(0, 1), 0), [])
        det.update("new#p", 1, 10.0, 0)
        alerts = det.update("new#p", 2, 11.5, 1)
        self.assertEqual([a["kind"] for a in alerts], ["outlier"])

    def test_moderate_value_is_not_an_outlier(self):
        det = Detector(BASE)
        self.assertEqual(det.update(KEYS[0], 1, 3.0, 0), [])

    def test_clean_stream_raises_no_verdict(self):
        verdicts = run(Detector(BASE), 150)
        self.assertFalse(any(v["anomaly"] for v in verdicts))

    def test_mean_shift_is_detected(self):
        verdicts = run(Detector(BASE), 60, lambda t, s, x: x + 3.0, start=20)
        self.assertFalse(any(v["anomaly"] for v in verdicts[:20]))
        hit = [i for i, v in enumerate(verdicts) if v["anomaly"]]
        self.assertTrue(hit and hit[0] - 20 <= 5)
        self.assertIn("mean_shift", kinds(verdicts[hit[0]]))

    def test_variance_change_is_detected(self):
        verdicts = run(Detector(BASE), 120, lambda t, s, x: x * 3.0, start=30)
        self.assertTrue(any("variance_change" in kinds(v) for v in verdicts[30:]))

    def test_site_imbalance_is_detected_on_the_right_site(self):
        verdicts = run(Detector(BASE), 90, lambda t, s, x: x + (3.0 if s == 2 else 0.0), start=25)
        alerts = [a for v in verdicts[25:] for a in v["top_alerts"] if a["kind"] == "site_imbalance"]
        self.assertTrue(alerts)
        self.assertTrue(all(a["site"] == 2 for a in alerts))

    def test_drift_is_detected(self):
        verdicts = run(Detector(BASE), 100, lambda t, s, x: x + 0.3 * t, start=25)
        self.assertTrue(any("mean_drift" in kinds(v) for v in verdicts[25:]))

    def test_shift_alert_is_emitted_once(self):
        det = Detector(BASE)
        emitted = 0
        for td in range(40):
            for site in (1, 2, 3, 4):
                emitted += sum(a["kind"] == "mean_shift" for a in det.update(KEYS[0], site, 4.0, td))
            det.end_touchdown()
        self.assertEqual(emitted, 1)

    def test_reset_clears_active_alerts(self):
        det = Detector(BASE)
        run(det, 40, lambda t, s, x: x + 5.0, start=0)
        det.reset("lot")
        self.assertEqual(det.end_touchdown()["n_alerts"], 0)

    def test_verdict_schema_and_message_length(self):
        verdicts = run(Detector(BASE), 30, lambda t, s, x: x + 5.0, start=0)
        v = next(v for v in verdicts if v["anomaly"])
        self.assertEqual(set(v), {"anomaly", "score", "n_alerts", "top_alerts", "message"})
        self.assertLessEqual(len(v["top_alerts"]), 5)
        self.assertTrue(0 < len(v["message"]) <= 200)
        self.assertEqual(set(v["top_alerts"][0]), {"kind", "test", "site", "score", "seq"})


if __name__ == "__main__":
    unittest.main()
