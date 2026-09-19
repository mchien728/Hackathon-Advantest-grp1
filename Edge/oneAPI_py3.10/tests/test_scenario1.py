import json
import os
import random
import sys
import types
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "bin"))
import test_sample_local as harness  # noqa: E402  (installs fake oneapi / libACSAction modules)

_ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..")
DATA_DIR = next((d for d in (os.path.join(_ROOT, "training", "training", "Data"), os.path.join(_ROOT, "SmarTest", "training", "Data")) if os.path.isdir(d)),
                os.path.join(_ROOT, "training", "training", "Data"))


class FakeMulti:
    """MultiParametric event: one entry per site, each with a result list and pin names."""

    def __init__(self, entries):
        self.entries = entries
        self.pin_calls = 0

    def get_ResultCount(self):
        return len(self.entries)

    def query_Results(self, i):
        return self.entries[i]["results"]

    def query_TestSuite(self, i):
        return self.entries[i]["suite"]

    def query_TestText(self, i):
        return self.entries[i]["text"]

    def query_TestNumber(self, i):
        return self.entries[i].get("number", 0)

    def query_HeadSite(self, i):
        return self.entries[i]["site"]

    def query_PinResults(self, i):
        self.pin_calls += 1
        pins = self.entries[i].get("pins")
        if pins is None:
            raise RuntimeError("no pin info")
        return list(range(len(pins)))

    def query_PinName(self, pin_id):
        return self._names[pin_id]


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
        return self.rows[i].get("x", 0)

    def query_YCoord(self, i):
        return self.rows[i].get("y", 0)

    def query_PartId(self, i):
        return self.rows[i].get("part_id", 0)

    def query_SBinResult(self, i):
        return self.rows[i].get("sbin", 1)

    def get_TimeStamp(self):
        return 0

    def get_WaferId(self):
        return "W99"

    def get_LotId(self):
        return "LOT1"

    def __getattr__(self, name):
        if name.startswith(("get_", "query_")):
            return (lambda *a: []) if "List" in name else (lambda *a: 0)
        raise AttributeError(name)


class Scenario1SampleTest(unittest.TestCase):
    def setUp(self):
        harness.FakeActionManager.reset()
        import sample
        sample.toSite = lambda v: v
        sample.toHead = lambda v: 1
        self.sample = sample
        self.mon = sample.SampleMonitor()
        from detector import Detector
        from scenario1 import Scenario1
        base = {f"Main.subflow2.Flow2_Suite{i}#CP": {"mu": 0.0, "sigma": 1.0, "monitor": True} for i in range(40)}
        self.mon.s1 = Scenario1(Detector(base, {"off_min_n": 20}))
        self.tc = types.SimpleNamespace(testerId="testerA", testerIP="127.0.0.1")

    def run_wafer(self, n_td, ramp_from=None, n_tests=40, end=True):
        rng = random.Random(5)
        self.mon.consumeLotStart(FakeResults([]))
        self.mon.consumeWaferStart(FakeResults([]))
        for td in range(n_td):
            dies = [{"site": s, "x": s, "y": td} for s in (1, 2, 3, 4)]
            self.mon.consumeTestStart(FakeResults(dies))
            rows = []
            for i in range(n_tests):
                for s in (1, 2, 3, 4):
                    v = rng.gauss(0, 1) + (1.5 * (td - ramp_from) if ramp_from is not None and td >= ramp_from else 0.0)
                    rows.append({"site": s, "suite": f"Main.subflow2.Flow2_Suite{i}", "text": "CP", "value": v})
            self.mon.consumeMultiParametric(FakeResults(rows))
            self.mon.consumeTestEnd(FakeResults([dict(d, part_id=td * 4 + d["site"], sbin=1) for d in dies]))
        if end:
            self.mon.consumeWaferEnd(FakeResults([]))

    def test_state_matches_contract_and_is_json(self):
        self.run_wafer(3)
        st = self.mon.get_state()
        self.assertEqual(sorted(st), ["confidence", "error", "finished", "history", "indicators", "label", "lot", "predictions", "predictor_error", "touchdown", "wafer", "wafer_map", "wafers"])
        self.assertEqual((st["lot"], st["wafer"], st["touchdown"]), ("LOT1", "W99", 3))
        self.assertEqual([h["td"] for h in st["history"]], [1, 2, 3])
        self.assertEqual(len(st["indicators"]), 8)
        self.assertIsNone(st["error"])
        self.assertNotIn("summary", json.dumps(st))
        json.dumps(st)

    def test_wafer_map_has_die_coordinates_and_resets_per_wafer(self):
        self.run_wafer(3)
        st = self.mon.get_state()
        wm = st["wafer_map"]
        self.assertEqual(wm["wafer"], "W99")
        self.assertEqual(len(wm["rows"]), 12)
        row = dict(zip(wm["columns"], wm["rows"][0]))
        self.assertEqual((row["td"], row["site"], row["x"], row["y"], row["sbin"], row["passed"]), (1, 1, 1, 0, 1, True))
        self.assertNotIn("part_id", row)
        self.assertEqual(wm["extent"], {"x": [1, 4], "y": [0, 2]})
        self.mon.consumeWaferStart(FakeResults([]))
        self.assertEqual(self.mon.get_state()["wafer_map"]["rows"], [])
        json.dumps(st)

    def run_wafer_no_start(self, n_td):
        rng = random.Random(9)
        for td in range(n_td):
            dies = [{"site": s, "x": s, "y": td} for s in (1, 2, 3, 4)]
            self.mon.consumeTestStart(FakeResults(dies))
            rows = [{"site": s, "suite": f"Main.subflow2.Flow2_Suite{i}", "text": "CP", "value": rng.gauss(0, 1)} for i in range(40) for s in (1, 2, 3, 4)]
            self.mon.consumeMultiParametric(FakeResults(rows))
            self.mon.consumeTestEnd(FakeResults([dict(d, part_id=1, sbin=1) for d in dies]))

    def test_new_wafer_is_detected_from_repeated_die_coordinates_when_no_wafer_start(self):
        self.run_wafer_no_start(4)
        self.assertEqual(self.mon.get_state()["wafer"], "auto-1")
        self.run_wafer_no_start(3)
        st = self.mon.get_state()
        self.assertEqual(st["wafer"], "auto-2")
        self.assertEqual([f["wafer"] for f in st["finished"]], ["auto-1"])
        self.assertEqual((st["touchdown"], len(st["wafer_map"]["rows"])), (3, 12))
        self.mon.consumeLotEnd(FakeResults([]))
        self.assertEqual([f["wafer"] for f in self.mon.get_state()["finished"]], ["auto-1", "auto-2"])

    def test_unset_coordinates_at_test_start_do_not_trigger_rollover(self):
        rng = random.Random(3)
        for td in range(4):
            starts = [{"site": s, "x": -32768, "y": -32768} for s in (1, 2, 3, 4)]
            ends = [{"site": s, "x": 10 + s, "y": td, "part_id": "", "sbin": 1} for s in (1, 2, 3, 4)]
            self.mon.consumeTestStart(FakeResults(starts))
            self.mon.consumeMultiParametric(FakeResults([{"site": s, "suite": "Main.subflow2.Flow2_Suite1", "text": "CP", "value": rng.gauss(0, 1)} for s in (1, 2, 3, 4)]))
            self.mon.consumeTestEnd(FakeResults(ends))
        st = self.mon.get_state()
        self.assertEqual((st["wafer"], st["touchdown"], st["finished"]), ("auto-1", 4, []))
        self.assertEqual(st["wafer_map"]["extent"], {"x": [11, 14], "y": [0, 3]})

    def test_no_auto_rollover_once_wafer_start_was_seen(self):
        self.mon.consumeWaferStart(FakeResults([]))
        self.run_wafer_no_start(3)
        self.run_wafer_no_start(3)
        st = self.mon.get_state()
        self.assertEqual((st["wafer"], st["touchdown"], st["finished"]), ("W99", 6, []))

    def test_wafer_end_without_data_is_ignored(self):
        self.assertIsNone(self.mon.s1.wafer_end())
        self.run_wafer(2)
        self.assertEqual(len(self.mon.get_state()["finished"]), 1)
        self.mon.consumeWaferEnd(FakeResults([]))
        self.assertEqual(len(self.mon.get_state()["finished"]), 1)

    def test_state_is_a_copy(self):
        self.run_wafer(2)
        st = self.mon.get_state()
        st["history"].clear()
        self.assertEqual(len(self.mon.get_state()["history"]), 2)

    def test_unknown_test_names_do_not_break_callbacks(self):
        self.mon.consumeMultiParametric(FakeResults([{"site": 1, "suite": "", "text": "", "value": 1.0}]))
        self.mon.consumeMultiParametric(FakeResults([{"site": 1, "suite": "Main.X", "text": "CP", "value": float("nan")}]))

    def test_ramp_wafer_is_reported_and_message_is_sent_once(self):
        self.run_wafer(12, ramp_from=4)
        report = self.mon.get_state()["finished"][-1]
        self.assertEqual(report["label"], "Mean Trend Up")
        self.assertEqual(report["wafer"], "W99")
        self.assertIsNotNone(report["onset_td"])
        self.mon.consumeData(self.tc, types.SimpleNamespace(getType=lambda: None))
        self.assertIn("Mean Trend Up", harness.FakeActionManager.messages["testerA"])
        harness.FakeActionManager.reset()
        self.mon.consumeData(self.tc, types.SimpleNamespace(getType=lambda: None))
        self.assertNotIn("testerA", harness.FakeActionManager.messages)

    def test_normal_wafer_sends_no_message(self):
        self.run_wafer(12)
        self.mon.consumeData(self.tc, types.SimpleNamespace(getType=lambda: None))
        self.assertNotIn("testerA", harness.FakeActionManager.messages)
        self.assertEqual(self.mon.get_state()["finished"][-1]["label"], "Normal")

    def _record(self):
        got = []
        self.mon.s1.measurement = lambda suite, text, site, value: got.append(("s1", suite, text, site, value))
        self.mon.s2.observe = lambda suite, text, site, value: got.append(("s2", suite, text, site, value))
        return got

    def _multi(self, entries):
        ev = FakeMulti(entries)
        names = {}
        for e in entries:
            for j, name in enumerate(e.get("pins") or []):
                names[j] = name
        ev._names = names
        return ev

    def test_pin_names_split_a_pin_group_result_into_one_measurement_per_pin(self):
        got = self._record()
        ev = self._multi([{"suite": "Main.Suite14", "text": "PinGrp", "site": 1, "number": 560, "results": [1.119, 1.475], "pins": ["CP", "MR"]}])
        self.mon.consumeMultiParametric(ev)
        self.assertEqual([g for g in got if g[0] == "s1"], [("s1", "Main.Suite14", "CP", 1, 1.119), ("s1", "Main.Suite14", "MR", 1, 1.475)])
        self.assertEqual([g[2:] for g in got if g[0] == "s2"], [("CP", 1, 1.119), ("MR", 1, 1.475)])

    def test_pin_name_wins_over_test_text_when_they_differ(self):
        got = self._record()
        ev = self._multi([{"suite": "Main.Suite3", "text": "IO1", "site": 2, "number": 280, "results": [1.381], "pins": ["IO2"]}])
        self.mon.consumeMultiParametric(ev)
        self.assertEqual([g[1:] for g in got if g[0] == "s1"], [("Main.Suite3", "IO2", 2, 1.381)])

    def test_normal_test_keeps_the_same_key_as_before(self):
        got = self._record()
        ev = self._multi([{"suite": "Main.Suite2", "text": "IO1", "site": 3, "number": 240, "results": [0.9], "pins": ["IO1"]}])
        self.mon.consumeMultiParametric(ev)
        self.assertEqual([g[1:] for g in got if g[0] == "s1"], [("Main.Suite2", "IO1", 3, 0.9)])

    def test_missing_or_mismatched_pin_info_falls_back_to_the_test_text_and_first_result(self):
        got = self._record()
        ev = self._multi([
            {"suite": "Main.A", "text": "T1", "site": 1, "number": 1, "results": [1.0, 2.0], "pins": None},
            {"suite": "Main.B", "text": "T2", "site": 1, "number": 2, "results": [3.0], "pins": ["X", "Y"]},
        ])
        self.mon.consumeMultiParametric(ev)
        self.assertEqual([g[1:] for g in got if g[0] == "s1"], [("Main.A", "T1", 1, 1.0), ("Main.B", "T2", 1, 3.0)])

    def test_pin_names_are_looked_up_once_per_test(self):
        self._record()
        entry = {"suite": "Main.Suite14", "text": "PinGrp", "number": 560, "results": [1.0, 2.0], "pins": ["CP", "MR"]}
        ev = self._multi([dict(entry, site=s) for s in (1, 2, 3, 4)])
        self.mon.consumeMultiParametric(ev)
        self.mon.consumeMultiParametric(ev)
        self.assertEqual(ev.pin_calls, 1)

    def test_pin_lookup_failure_does_not_break_the_event(self):
        got = self._record()
        ev = self._multi([{"suite": "Main.C", "text": "T", "site": 1, "number": 3, "results": [5.0], "pins": None}])
        self.mon.consumeMultiParametric(ev)
        self.assertEqual([g[1:] for g in got if g[0] == "s1"], [("Main.C", "T", 1, 5.0)])

    def test_wafers_summary_and_drilldown(self):
        self.run_wafer(12, ramp_from=4, end=False)
        st = self.mon.get_state()
        self.assertEqual(len(st["wafers"]), 1)
        w = st["wafers"][0]
        self.assertTrue(w["current"])
        self.assertEqual((w["wafer"], w["id"]), ("W99", "001_W99"))
        self.assertEqual([c["key"] for c in w["criteria"]], ["site_unbalance", "mean_trend", "stdev_up", "yield"])
        self.assertEqual(w["labels"], ["Mean Trend Up"])
        self.assertEqual(w["headline"], "Mean Trend Up")
        self.assertEqual(len(w["sites"]), 4)
        for heavy in ("heatmap", "tds", "evidence"):
            self.assertNotIn(heavy, w)
        d = self.mon.get_wafer()
        self.assertEqual(len(d["tds"]), 12)
        self.assertEqual(len(d["tds"][0]["dies"]), 4)
        self.assertEqual(set(d["tds"][0]["dies"][0]), {"index", "site", "x", "y", "sbin", "passed", "suspect", "outlier_tests", "group"})
        self.assertEqual(d["heatmap"]["sites"], [1, 2, 3, 4])
        self.assertEqual(d["heatmap"]["tds"], list(range(1, 13)))
        self.assertEqual(len(d["heatmap"]["cells"]), 4)
        self.assertEqual([len(r) for r in d["heatmap"]["cells"]], [12] * 4)
        self.assertGreater(len(d["evidence"]), 0)
        json.dumps(d)
        json.dumps(st)

    def test_finished_wafer_is_archived_with_detail_and_dropped_from_summary_payload(self):
        self.run_wafer(12, ramp_from=4)
        st = self.mon.get_state()
        self.assertEqual(len(st["wafers"]), 1)
        self.assertFalse(st["wafers"][0]["current"])
        self.assertNotIn("tds", st["wafers"][0])
        d = self.mon.get_wafer("001_W99")
        self.assertEqual(d["label"], "Mean Trend Up")
        self.assertEqual(len(d["tds"]), 12)
        self.assertIsNone(self.mon.get_wafer("nope"))
        self.mon.get_wafer("001_W99")["tds"].clear()
        self.assertEqual(len(self.mon.get_wafer("001_W99")["tds"]), 12)

    def test_get_wafer_is_none_before_any_data(self):
        self.assertIsNone(self.mon.get_wafer())

    @unittest.skipUnless(os.path.isdir(DATA_DIR), "official training data not present")
    def test_real_wafers_through_scenario1(self):
        sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "tools"))
        from wafer_data import wafer_files, load_wafer
        from scenario1 import Scenario1
        for n, expect in ((14, "Mean Trend Up"), (2, "Normal")):
            w = load_wafer(wafer_files(DATA_DIR)[n])
            s = Scenario1()
            s.wafer_start(f"W{n}")
            for td in range(20):
                rows = range(td * 4, td * 4 + 4)
                s.test_start([{"site": int(w["site"][r])} for r in rows])
                for j, k in enumerate(w["keys"]):
                    suite, _, pin = k.partition("#")
                    for r in rows:
                        s.measurement(suite, pin, int(w["site"][r]), w["values"][r, j])
                s.test_end([{"site": int(w["site"][r]), "sbin": int(w["sbin"][r]), "passed": int(w["sbin"][r]) == 1} for r in rows])
            self.assertEqual(s.wafer_end()["label"], expect)


class ScriptedDetector:
    """Detector stand-in that reports a scripted wafer label per touchdown."""

    p = {"die_out_k": 3}

    def __init__(self, labels):
        self.labels = list(labels)
        self.i = -1

    def reset(self, scope="lot"):
        pass

    def update_device(self, site, passed, sbin=None):
        pass

    def end_touchdown(self):
        self.i += 1
        return {"anomaly": False, "score": 0.0, "n_alerts": 0, "top_alerts": [], "message": ""}

    def end_wafer(self):
        return {"label": self.labels[self.i]}

    def die_flags(self):
        return {}

    def die_detail(self):
        return {}


class LabelStabilityTest(unittest.TestCase):
    def messages(self, labels, stable=3):
        from scenario1 import Scenario1
        s = Scenario1(ScriptedDetector(labels), label_stable_td=stable)
        s.wafer_start("W1")
        out = []
        for td in range(len(labels)):
            s.test_start([{"site": 1}])
            s.test_end([{"site": 1, "sbin": 1, "passed": True}])
            msg = s.pop_message()
            if msg:
                out.append((td + 1, msg))
        return out

    def test_short_lived_label_is_not_sent(self):
        got = self.messages(["Normal", "Low yield", "Low yield", "Normal", "Normal"])
        self.assertEqual(got, [])

    def test_label_is_sent_once_it_has_held_for_n_touchdowns(self):
        got = self.messages(["Normal", "Mean Trend Up", "Mean Trend Up", "Mean Trend Up", "Mean Trend Up"])
        self.assertEqual(got, [(4, "TD4: wafer looks like Mean Trend Up")])

    def test_flip_between_labels_restarts_the_count(self):
        got = self.messages(["Low yield", "Low yield", "Stdev Trend Up", "Stdev Trend Up", "Stdev Trend Up"])
        self.assertEqual(got, [(5, "TD5: wafer looks like Stdev Trend Up")])

    def test_stable_of_one_sends_immediately(self):
        got = self.messages(["Normal", "Low yield"], stable=1)
        self.assertEqual(got, [(2, "TD2: wafer looks like Low yield")])

    def test_new_wafer_resets_the_count(self):
        from scenario1 import Scenario1
        s = Scenario1(ScriptedDetector(["Low yield", "Low yield", "Low yield", "Low yield"]), label_stable_td=3)
        s.wafer_start("W1")
        for _ in range(2):
            s.test_start([{"site": 1}])
            s.test_end([{"site": 1, "sbin": 1, "passed": True}])
        s.wafer_start("W2")
        s.det.i = 1
        for _ in range(2):
            s.test_start([{"site": 1}])
            s.test_end([{"site": 1, "sbin": 1, "passed": True}])
        self.assertIsNone(s.pop_message())


    @unittest.skipUnless(os.path.isdir(DATA_DIR), "official training data not present")
    def test_real_wafer_drilldown_shows_site_row_and_block(self):
        sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "tools"))
        from wafer_data import wafer_files, load_wafer
        from scenario1 import Scenario1
        for n, label in ((1, "Site unbalance"), (14, "Mean Trend Up")):
            w = load_wafer(wafer_files(DATA_DIR)[n])
            s = Scenario1()
            s.wafer_start(f"W{n}")
            for td in range(20):
                rows = range(td * 4, td * 4 + 4)
                s.test_start([{"site": int(w["site"][r])} for r in rows])
                for j, k in enumerate(w["keys"]):
                    suite, _, pin = k.partition("#")
                    for r in rows:
                        s.measurement(suite, pin, int(w["site"][r]), w["values"][r, j])
                s.test_end([{"site": int(w["site"][r]), "sbin": int(w["sbin"][r]), "passed": int(w["sbin"][r]) == 1} for r in rows])
            d = s.get_wafer()
            self.assertIn(label, d["labels"])
            cells = dict(zip(d["heatmap"]["sites"], d["heatmap"]["cells"]))
            if n == 1:
                self.assertEqual([x.get("site") for x in d["sites"] if x["worst"]], [4])
                self.assertGreaterEqual(sum(1 for v in cells[4] if v and v >= 50), 4)
                self.assertLess(max(v or 0 for v in cells[1]), 10)
            else:
                self.assertGreaterEqual(sum(1 for i in range(20) if all((cells[s_][i] or 0) >= 50 for s_ in (1, 2, 3, 4))), 2)


if __name__ == "__main__":
    unittest.main()
