"""Command line client for the authenticated production agent service."""

from __future__ import annotations

import argparse
import json
import os
from urllib.parse import urlparse
from urllib.request import Request, urlopen


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Production agent service client")
    parser.add_argument("--url", default="http://127.0.0.1:8080")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("serve")
    run = commands.add_parser("run")
    run.add_argument("prompt")
    run.add_argument("--run-id")
    commands.add_parser("metrics")
    commands.add_parser("alerts")
    rollout = commands.add_parser("rollout")
    rollout.add_argument("percent", type=int)
    args = parser.parse_args(argv)
    if args.command == "serve":
        from .__main__ import main as serve_main

        serve_main()
        return 0
    parsed = urlparse(args.url)
    if parsed.scheme != "https" and not (
        parsed.scheme == "http" and parsed.hostname in {"localhost", "127.0.0.1", "::1"}
    ):
        raise ValueError("service URL must be HTTPS or loopback")
    token = os.environ.get("AGENT_API_TOKEN", "")
    if not token:
        raise RuntimeError("Set AGENT_API_TOKEN for client commands")
    body = None
    if args.command == "run":
        body = {"prompt": args.prompt, "run_id": args.run_id}
    elif args.command == "rollout":
        body = {"percent": args.percent}
    request = Request(
        args.url.rstrip("/") + "/" + args.command,
        data=json.dumps(body).encode() if body is not None else None,
        headers={
            "Authorization": "Bearer " + token,
            "Content-Type": "application/json",
        },
        method="POST" if body is not None else "GET",
    )
    with urlopen(request, timeout=35) as response:
        result = json.load(response)
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
