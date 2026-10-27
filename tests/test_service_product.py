import json
import os
import socket
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.error import URLError
from urllib.request import urlopen

import pytest

from observable_production_agent.cli import main


def test_cli_and_browser_against_running_service(tmp_path, monkeypatch, capsys):
    class ModelHandler(BaseHTTPRequestHandler):
        def do_POST(self):
            size = int(self.headers["Content-Length"])
            json.loads(self.rfile.read(size))
            body = json.dumps(
                {"choices": [{"message": {"content": "A useful answer"}}]}
            ).encode()
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    model = HTTPServer(("127.0.0.1", 0), ModelHandler)
    model_worker = threading.Thread(target=model.serve_forever, daemon=True)
    model_worker.start()
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    token = "a-long-agent-api-token"
    env = os.environ.copy()
    env.update(
        {
            "OPENAI_API_KEY": "test",
            "OPENAI_BASE_URL": f"http://127.0.0.1:{model.server_port}/v1",
            "AGENT_API_TOKEN": token,
            "APP_DB": str(tmp_path / "agent.sqlite3"),
            "HOST": "127.0.0.1",
            "PORT": str(port),
        }
    )
    process = subprocess.Popen(
        [sys.executable, "-m", "observable_production_agent"],
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    base = f"http://127.0.0.1:{port}"
    try:
        for _ in range(50):
            try:
                with urlopen(base + "/healthz", timeout=1) as response:
                    if response.status == 200:
                        break
            except URLError:
                time.sleep(0.1)
        else:
            raise AssertionError("service did not start")
        with urlopen(base + "/") as response:
            assert b"Production Agent" in response.read()
        monkeypatch.setenv("AGENT_API_TOKEN", token)
        assert main(["--url", base, "run", "Explain the test"]) == 0
        assert json.loads(capsys.readouterr().out)["answer"] == "A useful answer"
        assert main(["--url", base, "metrics"]) == 0
        assert json.loads(capsys.readouterr().out)["stable"]["requests"] == 1
    finally:
        process.terminate()
        process.wait(timeout=10)
        model.shutdown()
        model.server_close()
        model_worker.join()


def test_service_rejects_example_api_token(monkeypatch):
    from observable_production_agent.__main__ import main as serve_main

    monkeypatch.setenv("AGENT_API_TOKEN", "replace-with-a-long-random-token")
    with pytest.raises(SystemExit, match="non-example"):
        serve_main()
