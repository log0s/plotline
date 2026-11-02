"""Static file server that counts requests per path and reports them at /_hits."""

import collections
import http.server
import json
import sys

HITS: collections.Counter[str] = collections.Counter()


class Handler(http.server.SimpleHTTPRequestHandler):
    def _count(self) -> bool:
        if self.path == "/_hits":
            body = json.dumps(HITS).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return True
        HITS[self.path.split("?")[0]] += 1
        return False

    def do_GET(self) -> None:
        if not self._count():
            super().do_GET()

    def do_HEAD(self) -> None:
        if not self._count():
            super().do_HEAD()


if __name__ == "__main__":
    handler = lambda *a, **k: Handler(*a, directory=sys.argv[1], **k)  # noqa: E731
    http.server.ThreadingHTTPServer(("0.0.0.0", 8080), handler).serve_forever()
