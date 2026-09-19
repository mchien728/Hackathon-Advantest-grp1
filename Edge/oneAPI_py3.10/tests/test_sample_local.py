import json
import os
import sys
import types
import unittest
from unittest.mock import MagicMock

BIN_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "bin")


class FakeActionManager:
    messages = {}

    @classmethod
    def reset(cls):
        cls.messages = {}

    @classmethod
    def set_message(cls, testerid, reason):
        cls.messages[testerid] = reason
        return True

    @classmethod
    def get(cls, testerid):
        return json.dumps({"tester": testerid, "message": cls.messages.get(testerid, "")})

    @classmethod
    def get_prod(cls, testerid):
        return cls.get(testerid)


def install_fake_modules():
    fake_oneapi = types.ModuleType("oneapi")
    fake_oneapi.Monitor = type("Monitor", (), {"__init__": lambda self: None})
    for name in ("DataType", "TestCell", "Command", "Interface", "toHead", "toSite", "DFFData", "QueryResponse", "DFF"):
        setattr(fake_oneapi, name, MagicMock())
    fake_action = types.ModuleType("libACSAction")
    fake_action.ActionManager = FakeActionManager
    fake_transfer = types.ModuleType("FileTransfer")
    fake_transfer.FileTransfer = MagicMock
    sys.modules.update({"oneapi": fake_oneapi, "libACSAction": fake_action, "FileTransfer": fake_transfer})
    sys.path.insert(0, BIN_DIR)


install_fake_modules()


class SampleMonitorLocalTest(unittest.TestCase):
    def setUp(self):
        FakeActionManager.reset()
        import sample
        self.sample = sample
        self.monitor = sample.SampleMonitor()
        self.tc = types.SimpleNamespace(testerId="testerA", testerIP="127.0.0.1")

    def test_list_request_returns_seeded_message(self):
        response = self.monitor.consumeTPRequest(self.tc, json.dumps({"action": "list"}))
        self.assertIn("adaptive loop wiring OK", response)
        self.assertEqual(FakeActionManager.messages["testerA"], "py-app test message: adaptive loop wiring OK")

    def test_health_request_still_ok(self):
        self.assertEqual(self.monitor.consumeTPRequest(self.tc, json.dumps({"key": "health"})), "ok")

    def test_unknown_request_unsupported(self):
        self.assertEqual(self.monitor.consumeTPRequest(self.tc, json.dumps({"key": "nope"})), "unsupported")

    def test_parametric_event_dispatch_does_not_crash(self):
        data_type = sys.modules["oneapi"].DataType
        data = MagicMock()
        data.getType.return_value = data_type.DATA_TYP_MEASURED_PARAMETRIC
        data.get_ResultCount.return_value = 1
        self.monitor.consumeData(self.tc, data)
        data.query_Result.assert_called_once_with(0)


if __name__ == "__main__":
    unittest.main()
