import json
import os
import sys
import time
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "bin"))
sys.path.insert(0, os.path.join(HERE, "..", "tools"))
from mock_frontend import make_server  # noqa: E402
from pusher import StatePusher  # noqa: E402
import threading  # noqa: E402


class PusherTest(unittest.TestCase):
    def setUp(self):
        self.srv = make_server()
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.url = f"http://127.0.0.1:{self.srv.server_address[1]}/api/state"

    def tearDown(self):
        self.srv.shutdown()
        self.srv.server_close()

    def wait_for(self, cond, secs=3.0):
        end = time.time() + secs
        while time.time() < end:
            if cond():
                return True
            time.sleep(0.02)
        return False

    def test_state_is_posted_repeatedly_with_increasing_seq(self):
        state = {"label": "Normal", "wafer": "W1", "indicators": []}
        p = StatePusher(lambda: state, self.url, interval=0.05)
        p.start()
        self.assertTrue(self.wait_for(lambda: self.srv.store.count >= 3))
        p.stop()
        got = self.srv.store.latest
        self.assertEqual((got["label"], got["wafer"]), ("Normal", "W1"))
        self.assertGreaterEqual(got["seq"], 3)
        self.assertLessEqual(abs(got["sent_at"] - time.time()), 5)
        self.assertEqual(p.failed, 0)

    def test_frontend_down_does_not_raise_and_recovers(self):
        logs = []
        port = self.srv.server_address[1]
        self.srv.shutdown()
        self.srv.server_close()
        p = StatePusher(lambda: {"x": 1}, f"http://127.0.0.1:{port}/api/state", interval=0.05, timeout=0.3, log=logs.append)
        p.start()
        self.assertTrue(self.wait_for(lambda: p.failed >= 3))
        self.assertTrue(p.is_alive())
        self.assertEqual(len([l for l in logs if "failed" in l]), 1)
        self.srv = make_server(port=port)
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.assertTrue(self.wait_for(lambda: p.sent >= 1))
        p.stop()
        self.assertTrue(any("recovered" in l for l in logs))

    def test_get_state_exception_is_counted_not_fatal(self):
        def boom():
            raise RuntimeError("state broke")
        p = StatePusher(boom, self.url, interval=0.05, log=lambda m: None)
        p.start()
        self.assertTrue(self.wait_for(lambda: p.failed >= 2))
        self.assertTrue(p.is_alive())
        self.assertIn("state broke", p.last_error)
        p.stop()

    def test_only_http_urls_are_accepted(self):
        for bad in ("file:///etc/passwd", "ftp://x/y", ""):
            with self.assertRaises(ValueError):
                StatePusher(lambda: {}, bad)

    def test_stop_ends_the_thread(self):
        p = StatePusher(lambda: {}, self.url, interval=0.05)
        p.start()
        p.stop()
        p.join(2)
        self.assertFalse(p.is_alive())

    def test_mock_frontend_serves_the_latest_state(self):
        import urllib.request
        StatePusher(lambda: {"label": "Mean Trend Up"}, self.url).push_once()
        with urllib.request.urlopen(self.url, timeout=2) as r:
            self.assertEqual(json.loads(r.read())["label"], "Mean Trend Up")


if __name__ == "__main__":
    unittest.main()
