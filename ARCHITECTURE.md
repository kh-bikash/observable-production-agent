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
3. Persist SQLite files on durable storage and back them up; migrate to a managed database for high write volume or multiple replicas.
4. Run `pytest -q` in CI before deployment.
5. Define workload specific evaluation cases, latency objectives, and rollback criteria before serving real users.
