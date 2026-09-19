import os
import random
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "bin"))
from detector import Detector, normalize_key, robust_stats  # noqa: E402

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

    def test_robust_stats_is_accurate_and_ignores_outliers(self):
        rng = random.Random(5)
        clean = [rng.gauss(10.0, 2.0) for _ in range(2000)]
        mu, sigma = robust_stats(clean)
        self.assertAlmostEqual(mu, 10.0, delta=0.2)
        self.assertAlmostEqual(sigma, 2.0, delta=0.15)
        mu2, sigma2 = robust_stats(clean[:1900] + [500.0] * 100)
        self.assertAlmostEqual(sigma2, 2.0, delta=0.3)

    def test_sigma_is_inflated_by_sample_size(self):
        small = Detector({"a#p": {"mu": 0.0, "sigma": 1.0, "monitor": True, "n": 25}})
        large = Detector({"a#p": {"mu": 0.0, "sigma": 1.0, "monitor": True, "n": 10 ** 6}})
        small.update("a#p", 1, 0.0, 0)
        large.update("a#p", 1, 0.0, 0)
        self.assertAlmostEqual(1.0 / small._st["a#p"].inv, 1.0 + 0.5 / 5.0, places=6)
        self.assertAlmostEqual(1.0 / large._st["a#p"].inv, 1.0, delta=0.01)

    def test_mismatched_baseline_falls_back_to_warmup_without_false_alarms(self):
        det = Detector({k: {"mu": 0.0, "sigma": 1.0, "monitor": True, "n": 10 ** 9} for k in KEYS})
        rng = random.Random(9)
        verdicts = []
        for td in range(30):
            for key in KEYS:
                for site in (1, 2, 3, 4):
                    det.update(key, site, 1000.0 + rng.gauss(0.0, 1.0), td)
            verdicts.append(det.end_touchdown())
        self.assertFalse(any(v["anomaly"] for v in verdicts))
        self.assertTrue(all(st.warm is None and st.ok for st in det._st.values()))

    def test_single_site_spike_is_not_treated_as_baseline_mismatch(self):
        det = Detector(BASE)
        for site, value in ((1, 0.1), (2, 0.2), (3, 500.0), (4, -0.1)):
            det.update(KEYS[0], site, value, 0)
        self.assertIsNone(det._st[KEYS[0]].probe)
        self.assertTrue(det._st[KEYS[0]].ok)
        self.assertTrue(det.end_touchdown()["anomaly"])

    def test_common_wafer_offset_is_removed_without_false_alarms(self):
        keys = [f"Main.S{i}#CP" for i in range(30)]
        base = {k: {"mu": 0.0, "sigma": 1.0, "monitor": True} for k in keys}
        det = Detector(base, {"off_min_n": 20})
        verdicts = run(det, 30, mod=lambda t, s, x: x + 0.9, keys=keys)
        self.assertFalse(any(v["anomaly"] for v in verdicts))
        self.assertAlmostEqual(det._off, 0.9, delta=0.3)
        self.assertEqual(det.end_wafer()["label"], "Normal")

    def test_end_wafer_labels_mean_trend_and_direction(self):
        keys = [f"Main.S{i}#CP" for i in range(40)]
        base = {k: {"mu": 0.0, "sigma": 1.0, "monitor": True} for k in keys}
        for sign, label in ((1, "Mean Trend Up"), (-1, "Mean Trend Down")):
            det = Detector(base, {"off_min_n": 20})
            run(det, 12, mod=lambda t, s, x: x + sign * 1.5 * t, start=4, keys=keys)
            self.assertEqual(det.end_wafer()["label"], label)

    def test_labels_are_independent_and_first_one_is_the_classification(self):
        det = Detector(BASE)
        f = {"site": 25, "mean_up": 40, "mean_down": 0, "var_up": 0, "yield": 0.9, "devices": 40}
        self.assertEqual(det._labels(f), ["Site unbalance", "Mean Trend Up"])
        self.assertEqual(det._classify(f), "Site unbalance")
        f = {"site": 0, "mean_up": 0, "mean_down": 35, "var_up": 21, "yield": 0.7, "devices": 40}
        self.assertEqual(det._labels(f), ["Mean Trend Down", "Stdev Trend Up", "Low yield"])
        f = {"site": 0, "mean_up": 0, "mean_down": 0, "var_up": 0, "yield": 0.7, "devices": 10}
        self.assertEqual((det._labels(f), det._classify(f)), ([], "Normal"))

    def test_evidence_lists_tests_of_the_flagged_group_with_kind_and_direction(self):
        keys = [f"Main.subflow1.Flow1_Suite{i}#CP" for i in range(40)]
        base = {k: {"mu": 0.0, "sigma": 1.0, "monitor": True} for k in keys}
        det = Detector(base, {"off_min_n": 20})
        run(det, 12, mod=lambda t, s, x: x + 1.5 * t, start=4, keys=keys)
        ev = det.evidence()
        self.assertGreaterEqual(len(ev), 30)
        self.assertEqual({r["group"] for r in ev}, {"Main.subflow1"})
        self.assertTrue(all(r["direction"] == "up" for r in ev if "mean_shift" in r["kinds"]))
        self.assertEqual(set(ev[0]), {"test", "group", "kinds", "direction", "site"})
        self.assertEqual(Detector(base).evidence(), [])

    def test_die_detail_reports_group_and_count_for_the_last_touchdown(self):
        keys = [f"Main.subflow1.Flow1_Suite{i}#CP" for i in range(6)]
        base = {k: {"mu": 0.0, "sigma": 1.0, "monitor": True} for k in keys}
        det = Detector(base)
        for key in keys:
            for site in (1, 2, 3, 4):
                det.update(key, site, 20.0 if site == 3 else 0.0, 0)
        det.end_touchdown()
        self.assertEqual(det.die_detail(), {3: ("Main.subflow1", 6)})
        self.assertEqual(det.die_flags(), {3: 6})

    def test_end_wafer_labels_low_yield_but_ignores_systematic_bin(self):
        det = Detector(BASE)
        for i in range(40):
            det.update_device(1, i % 2 == 0, 6)
        self.assertEqual(det.end_wafer()["label"], "Low yield")
        det.reset("wafer")
        for i in range(40):
            det.update_device(1, i % 2 == 0, 3)
        self.assertEqual(det.end_wafer()["label"], "Normal")

    def test_reset_wafer_clears_offset_and_counters(self):
        det = Detector(BASE, {"off_min_n": 5})
        run(det, 3, mod=lambda t, s, x: x + 0.8)
        self.assertNotEqual(det._off, 0.0)
        det.reset("wafer")
        self.assertEqual(det._off, 0.0)
        self.assertEqual(det.end_wafer()["touchdowns"], 0)

    def test_metrics_are_json_serializable_and_report_ramp(self):
        import json
        keys = [f"Main.subflow2.S{i}#CP" for i in range(40)]
        base = {k: {"mu": 0.0, "sigma": 1.0, "monitor": True} for k in keys}
        det = Detector(base, {"off_min_n": 20})
        run(det, 14, mod=lambda t, s, x: x + 1.5 * t if t < 6 else x, start=3, keys=keys)
        m = json.loads(json.dumps(det.metrics()))
        self.assertEqual([c["id"] for c in m["criteria"]], list(range(1, 9)))
        self.assertEqual(m["label"], "Mean Trend Up")
        ramp = m["criteria"][6]["detail"]
        self.assertIsNotNone(ramp["onset_td"])
        self.assertTrue(ramp["snapped_back"])
        self.assertEqual(ramp["group"], "Main.subflow2")
        self.assertIn("Main.subflow2", m["series"])

    def test_info_reports_baseline_size(self):
        self.assertEqual(Detector(BASE).info(), {"monitored_tests": 5, "baseline_tests": 5, "load_error": None})


if __name__ == "__main__":
    unittest.main()
