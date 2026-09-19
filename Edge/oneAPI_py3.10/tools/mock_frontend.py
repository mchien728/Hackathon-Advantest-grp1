import argparse
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class Store:
    def __init__(self):
        self.lock = threading.Lock()
        self.latest = None
        self.count = 0


def make_server(host="127.0.0.1", port=0, store=None):
    store = store or Store()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_POST(self):
            if self.path != "/api/state":
                return self._reply(404, {"error": "not found"})
            try:
                data = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))).decode("utf-8"))
            except ValueError:
                return self._reply(400, {"error": "invalid json"})
            with store.lock:
                store.latest, store.count = data, store.count + 1
            self._reply(200, {"ok": True})

        def do_GET(self):
            if self.path == "/healthz":
                return self._reply(200, {"ok": True})
            if self.path != "/api/state":
                return self._reply(404, {"error": "not found"})
            with store.lock:
                self._reply(200, store.latest if store.latest is not None else {"error": "no state received yet"})

        def _reply(self, code, obj):
            body = json.dumps(obj).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    server = ThreadingHTTPServer((host, port), Handler)
    server.store = store
    return server


def main():
    ap = argparse.ArgumentParser(description="Minimal stand-in for the frontend: accepts POST /api/state from the backend and serves the latest state on GET /api/state")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=5000)
    a = ap.parse_args()
    srv = make_server(a.host, a.port)
    print(f"listening on http://{a.host}:{srv.server_address[1]}  (POST /api/state to push, GET /api/state to read)")
    srv.serve_forever()


if __name__ == "__main__":
    main()
