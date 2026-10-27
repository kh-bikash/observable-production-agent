# Observable Production Agent

Serve an authenticated agent API with health checks, durable request metrics, optional OTLP tracing, canary traffic, and automatic rollback.

The service exposes authenticated `/metrics`, `/prometheus`, and `/alerts` endpoints. Supply a stable `run_id` on related `/run` calls to detect repeated prompts and stop loops. Canary rollback and loop events are persisted in the alert table.

`deploy/prometheus.yml` and `deploy/alert-rules.yml` provide a scrape configuration and alerts for failure rate, loops, and rollback. Place the API token in the referenced secret file and route Prometheus alerts to your alert manager.

## Quick start

Requires Python 3.11 or newer. From this repository:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e '.[tracing,dev]'
pytest -q
```

On macOS or Linux:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[tracing,dev]'
pytest -q
```

For live model calls, set `OPENAI_API_KEY` and optionally `OPENAI_MODEL` and `OPENAI_BASE_URL` as shown in `.env.example`. The test suite uses stubs and needs no model key.

```powershell
# PowerShell:
$env:OPENAI_API_KEY = "your-key"
$env:AGENT_API_TOKEN = "replace-with-a-long-random-token"
$env:CANARY_PERCENT = "5"
# Optional Arize Phoenix endpoint, with the tracing extra installed:
$env:OTEL_EXPORTER_OTLP_TRACES_ENDPOINT = "https://app.phoenix.arize.com/v1/traces"
python -m observable_production_agent
# GET /healthz; authenticated GET /metrics; POST /run {"prompt":"..."}; POST /rollout {"percent":5}
```

## Architecture

Authenticated HTTP request -> persisted rollout allocation -> stable/canary model -> OpenTelemetry span and JSON log -> SQLite latency/cost/error metric -> rollback when canary failure rate crosses threshold.

See [ARCHITECTURE.md](ARCHITECTURE.md) for components, state, failure behavior, and operations.

## Deployment and safety

Run behind TLS and a reverse proxy. Mount /data on persistent storage. The cost metric is an estimate; production billing reconciliation needs provider usage fields. Set `PHOENIX_API_KEY` when the Phoenix collector requires authentication; the exporter sends it as a bearer token. Rollback triggers from the observed window and is persisted.

A Dockerfile is included for the HTTP service. Set secrets through your deployment platform and persist the SQLite database on a mounted volume.

## Verification

`pytest -q` runs deterministic tests. GitHub Actions runs the same suite on pushes and pull requests.

## License

MIT. See [LICENSE](LICENSE).
