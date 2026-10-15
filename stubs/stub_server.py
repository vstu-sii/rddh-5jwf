"""HTTP-заглушка сервиса из C4: отвечает на /health, остальное — 501 до реализации в лабе 3."""

import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

SERVICE_NAME = os.getenv("SERVICE_NAME", "stub")
PORT = int(os.getenv("PORT", "8080"))


class StubHandler(BaseHTTPRequestHandler):
    def _send(self, status: int, payload: dict) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _handle(self) -> None:
        if self.path == "/health":
            self._send(200, {"service": SERVICE_NAME, "status": "ok", "stub": True})
        else:
            self._send(501, {"service": SERVICE_NAME, "detail": "not implemented in stub"})

    do_GET = _handle
    do_POST = _handle

    def log_message(self, format: str, *args) -> None:
        print(f"[{SERVICE_NAME}] {self.address_string()} {format % args}", flush=True)


if __name__ == "__main__":
    print(f"[{SERVICE_NAME}] stub listening on :{PORT}", flush=True)
    ThreadingHTTPServer(("0.0.0.0", PORT), StubHandler).serve_forever()
