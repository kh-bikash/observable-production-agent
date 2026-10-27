# Architecture

## Goal

Serve an authenticated agent API with health checks, durable request metrics, optional OTLP tracing, canary traffic, and automatic rollback.

## Request path

Authenticated HTTP request -> persisted rollout allocation -> stable/canary model -> OpenTelemetry span and JSON log -> SQLite latency/cost/error metric -> rollback when canary failure rate crosses threshold.

## Components

- `src/observable_production_agent/engine.py`: policy and state transitions for this project.
- `src/observable_production_agent/llm.py`: injected model protocol and HTTPS OpenAI-compatible adapter with timeouts and retry for transient transport failures.
- `tests/test_engine.py`: deterministic behavior and failure tests.
- `.github/workflows/ci.yml`: install and test gate.
- `src/observable_production_agent/__main__.py`: HTTP service entry point.
- `Dockerfile`: non-root container image.

## State and failure behavior

Run behind TLS and a reverse proxy. Mount /data on persistent storage. The cost metric is an estimate; production billing reconciliation needs provider usage fields. Configure `PHOENIX_API_KEY` or exporter headers as required by your collector. Rollback triggers from the observed window and is persisted.

The LLM adapter times out after 30 seconds and retries transient HTTP failures twice. Model output is untrusted input and is parsed or validated at the project boundary.

## Operations checklist

1. Set secrets through a secret manager and rotate them regularly.
2. Put the service or integrating application behind TLS and authentication.
3. Persist and back up the SQLite rollout, metric, and alert store. Use a shared state backend before horizontal scaling.
4. Run `pytest -q` in CI before deployment.
5. Define workload specific evaluation cases, latency objectives, and rollback criteria before serving real users.

## Serving and observability

The HTTP service requires a bearer API token for `/run`, `/rollout`, `/metrics`, `/prometheus`, and `/alerts`; `/healthz` is unauthenticated. `calls` stores variant, latency, estimated cost, error, run ID, and a prompt hash. Raw prompts are not stored in the ledger. Repeated prompts with the same run ID trigger a durable loop alert. Canary percentage is persisted in `rollout`; a canary failure rate above the configured threshold sets it to zero. `alerts` records loop and rollback events.

The optional tracing extra exports OpenTelemetry spans over OTLP HTTP. Set `OTEL_EXPORTER_OTLP_TRACES_ENDPOINT` and, for authenticated Phoenix, `PHOENIX_API_KEY`. A trace ID is returned to clients and included in structured logs. The Prometheus endpoint exposes counters and gauges; `deploy/alert-rules.yml` defines failure, loop, and rollback alerts. The sample scrape config reads the bearer token from a mounted secret file.

Deploy behind TLS with persistent `/data`. The service uses SQLite and a thread-based HTTP server, so use one replica per database or move state to a shared database before horizontal scaling. The cost value is an estimate until provider usage and billing reconciliation are wired in.
