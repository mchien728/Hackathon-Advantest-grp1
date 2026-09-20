import json
import os
import signal
import sys
import time
from collections import OrderedDict

BIN = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "bin")
sys.path.insert(0, BIN if os.path.isdir(BIN) else os.path.dirname(os.path.abspath(__file__)))
from oneapi import AppInfo, DataType, Interface  # noqa: E402
import sample  # noqa: E402

OUT = os.environ.get("PROBE_OUT", "/tmp/probe.json")
NAMES = {getattr(DataType, n): n for n in dir(DataType) if n.startswith("DATA_TYP_")}


class Probe(sample.SampleMonitor):
    def __init__(self):
        sample.SampleMonitor.__init__(self)
        self.seq = []
        self.timing = OrderedDict()
        self.facts = {}
        self.td_ms = 0.0
        self.td_log = []

    def _note(self, key, value):
        self.facts.setdefault(key, value)

    def _peek(self, name, data):
        try:
            if name == "DATA_TYP_MEASURED_MULTI_PARAM" and data.get_ResultCount() > 0:
                r = data.query_Results(0)
                self._note("multi_param", {"suite": data.query_TestSuite(0), "text": data.query_TestText(0), "site": int(sample.toSite(data.query_HeadSite(0))),
                                           "results_type": type(r).__name__, "results_len": len(r), "first_type": type(r[0]).__name__ if len(r) else None,
                                           "first": float(r[0]) if len(r) else None})
            elif name == "DATA_TYP_PRODUCTION_TESTEND" and data.get_ResultCount() > 0:
                self._note("test_end", [{"site": int(sample.toSite(data.query_HeadSite(i))), "part_flag": str(data.query_PartFlag(i)), "sbin": data.query_SBinResult(i),
                                         "hbin": data.query_HBinResult(i), "x": data.query_XCoord(i), "y": data.query_YCoord(i), "part_id": str(data.query_PartId(i)),
                                         "types": [type(data.query_XCoord(i)).__name__, type(data.query_SBinResult(i)).__name__]} for i in range(data.get_ResultCount())])
            elif name == "DATA_TYP_PRODUCTION_TESTSTART" and data.get_ResultCount() > 0:
                self._note("test_start", [{"site": int(sample.toSite(data.query_HeadSite(i))), "x": data.query_XCoord(i), "y": data.query_YCoord(i)} for i in range(data.get_ResultCount())])
            elif name in ("DATA_TYP_PRODUCTION_LOTSTART", "DATA_TYP_PRODUCTION_WAFERSTART"):
                getter = "get_LotId" if name.endswith("LOTSTART") else "get_WaferId"
                self._note(name.lower() + "_id", str(getattr(data, getter)()))
        except Exception as e:
            self._note("peek_error_" + name, repr(e))

    def consumeData(self, tc, data):
        name = NAMES.get(data.getType(), str(data.getType()))
        if not self.seq or self.seq[-1][0] != name:
            self.seq.append([name, 0])
        self.seq[-1][1] += 1
        self._peek(name, data)
        t0 = time.perf_counter()
        try:
            sample.SampleMonitor.consumeData(self, tc, data)
        finally:
            ms = (time.perf_counter() - t0) * 1000.0
            t = self.timing.setdefault(name, [0, 0.0, 0.0])
            t[0] += 1
            t[1] += ms
            t[2] = max(t[2], ms)
            self.td_ms += ms
            if name in ("DATA_TYP_PRODUCTION_TESTEND", "DATA_TYP_PRODUCTION_WAFEREND", "DATA_TYP_PRODUCTION_LOTEND"):
                if name.endswith("TESTEND"):
                    self.td_log.append(round(self.td_ms, 1))
                    self.td_ms = 0.0
                self.dump()

    def dump(self):
        try:
            report = {"time": time.time(), "sequence_runlength": self.seq[-60:], "n_events": sum(c for _, c in self.seq),
                      "timing_ms": {k: {"count": v[0], "total": round(v[1], 1), "max": round(v[2], 1)} for k, v in self.timing.items()},
                      "callback_ms_per_touchdown": self.td_log[-30:], "facts": self.facts, "state": self.get_state()}
            with open(OUT + ".tmp", "w") as f:
                json.dump(report, f, default=str)
            os.replace(OUT + ".tmp", OUT)
        except Exception as e:
            print("probe dump failed:", repr(e))


def quit(signum, frame):
    Interface.disconnect()
    sys.exit()


def main():
    mon = Probe()
    Interface.registerMonitor(mon)
    me = AppInfo()
    me.name = "sample"
    me.vendor = "adv"
    me.version = "1.0.0"
    res = Interface.connect(me, True, True)
    print("connect result:", res, flush=True)
    if res != 0:
        sys.exit(1)
    signal.signal(signal.SIGINT, quit)
    signal.signal(signal.SIGTERM, quit)
    while True:
        signal.pause()


if __name__ == "__main__":
    main()
