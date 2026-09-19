import json
import threading
import time
import urllib.request


class StatePusher(threading.Thread):
    """Background thread that POSTs the dashboard state to the frontend every few seconds; never blocks or crashes the event callbacks."""

    def __init__(self, get_state, url, interval=3.0, timeout=2.0, log=print):
        super().__init__(daemon=True, name="state-pusher")
        if not str(url).startswith(("http://", "https://")):
            raise ValueError(f"frontend url must start with http:// or https://, got {url!r}")
        self.get_state = get_state
        self.url = url
        self.interval = max(float(interval), 0.05)
        self.timeout = timeout
        self.log = log
        self.seq = 0
        self.sent = 0
        self.failed = 0
        self.consecutive_failures = 0
        self.last_error = None
        self.last_ok = None
        self._stop_event = threading.Event()

    def push_once(self):
        try:
            state = self.get_state()
            self.seq += 1
            body = json.dumps(dict(state, seq=self.seq, sent_at=time.time()), separators=(",", ":"), default=str).encode("utf-8")
            req = urllib.request.Request(self.url, data=body, method="POST", headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                if not 200 <= resp.status < 300:
                    raise RuntimeError(f"frontend answered HTTP {resp.status}")
        except Exception as e:
            self.failed += 1
            self.consecutive_failures += 1
            self.last_error = f"{type(e).__name__}: {e}"
            if self.consecutive_failures in (1, 10) or self.consecutive_failures % 100 == 0:
                self.log(f"[state-pusher] push to {self.url} failed ({self.consecutive_failures} in a row): {self.last_error}")
            return False
        if self.consecutive_failures:
            self.log(f"[state-pusher] push to {self.url} recovered after {self.consecutive_failures} failures")
        self.sent += 1
        self.consecutive_failures = 0
        self.last_ok = time.time()
        return True

    def run(self):
        while not self._stop_event.is_set():
            self.push_once()
            self._stop_event.wait(self.interval)

    def stop(self):
        self._stop_event.set()
