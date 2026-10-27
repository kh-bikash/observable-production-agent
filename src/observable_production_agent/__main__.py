from __future__ import annotations

import hmac
import json
import logging
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from .engine import LoopDetected, ProductionAgent
from .llm import OpenAICompatibleLLM
from .tracing import configure_tracing


class ModelClient:
    def __init__(self, client: OpenAICompatibleLLM, model: str):
        self.client, self.model = client, model

    def complete(self, messages, *, model=None):
        return self.client.complete(messages, model=model or self.model)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    token = os.environ.get("AGENT_API_TOKEN", "")
    if len(token) < 16:
        raise SystemExit("Set AGENT_API_TOKEN to at least 16 characters")
    client = OpenAICompatibleLLM.from_env()
    configure_tracing()
    agent = ProductionAgent(ModelClient(client, os.environ.get("STABLE_MODEL", "gpt-4.1-mini")),
                            ModelClient(client, os.environ.get("CANARY_MODEL", "gpt-4.1")),
                            os.environ.get("APP_DB", "agent.sqlite3"),
                            canary_percent=int(os.environ.get("CANARY_PERCENT", "0")))

    class Handler(BaseHTTPRequestHandler):
        def authorized(self) -> bool:
            supplied = self.headers.get("Authorization", "").removeprefix("Bearer ")
            return hmac.compare_digest(supplied, token)

        def do_GET(self):
            if self.path == "/healthz":
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b"ok")
            elif self.path == "/metrics" and self.authorized():
                self.send_json(200, agent.metrics())
            elif self.path == "/alerts" and self.authorized():
                self.send_json(200, {"alerts": agent.alerts()})
            elif self.path == "/prometheus" and self.authorized():
                body = agent.prometheus_metrics().encode()
                self.send_response(200)
                self.send_header("Content-Type", "text/plain; version=0.0.4")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            else:
                self.send_error(404)

        def send_json(self, status: int, data: dict):
            body = json.dumps(data).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_POST(self):
            if not self.authorized():
                self.send_error(401)
                return
            size = int(self.headers.get("Content-Length", "0"))
            if not 0 < size <= 20000:
                self.send_error(413)
                return
            try:
                data = json.loads(self.rfile.read(size))
                if self.path == "/run":
                    response = agent.run(str(data["prompt"]), run_id=data.get("run_id"))
                    self.send_json(200, response.__dict__)
                elif self.path == "/rollout":
                    agent.set_canary_percent(int(data["percent"]))
                    self.send_json(200, {"canary_percent": agent.canary_percent})
                else:
                    self.send_error(404)
            except (ValueError, KeyError, TypeError):
                self.send_error(400)
            except LoopDetected:
                self.send_error(409)
            except RuntimeError:
                self.send_error(502)

    server = ThreadingHTTPServer((os.environ.get("HOST", "127.0.0.1"), int(os.environ.get("PORT", "8080"))), Handler)
    try:
        server.serve_forever()
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
