# Operations runbook

## Deploy

1. Copy `.env.example` to `.env`. Set a real model API key, a long random `AGENT_API_TOKEN`, stable and canary model names, and `CANARY_PERCENT=0` for the first rollout.
2. Run `docker compose up --build -d`. The compose file binds localhost port 8080 and stores the SQLite ledger on `agent_data`.
3. Terminate TLS at a reverse proxy. Keep `/rollout`, `/metrics`, `/prometheus`, and `/alerts` on an operator network. They also require the bearer token.
4. Check `/healthz` and make one authenticated `/run` call using a non-sensitive prompt.

## Observe

Set `OTEL_EXPORTER_OTLP_TRACES_ENDPOINT` and, for authenticated Phoenix, `PHOENIX_API_KEY` to export spans. Configure Prometheus from `deploy/prometheus.yml` with the API token mounted at `/run/secrets/agent_api_token`. Load `deploy/alert-rules.yml` and route alerts through your Alertmanager. Check `/alerts` for persisted loop and rollback events.

## Canary rollout

Start at zero. `POST /rollout` with `{"percent":5}` to route a small traffic share to the canary. Compare error rate, latency, cost, and a held out quality evaluation against stable. Increase traffic in stages only after the observation window is healthy. A canary failure rate above the configured threshold sets the persisted percentage to zero. To roll back manually, post `{"percent":0}`.

## Back up and recover

Use SQLite's online backup API or stop writes before copying the database volume. Restore to an isolated environment first. The rollout percentage persists across restarts, so check it before re-enabling traffic. Rotate model and API tokens through the deployment platform. Raw prompts are not stored in the call ledger, but model providers and tracing collectors have separate retention policies.

## Scale limit

The included profile is one process and one SQLite database. Before horizontal scaling, migrate rollout and metrics state to a shared store and use an ingress that assigns canary buckets consistently. The cost metric is an estimate until provider usage and billing reconciliation are integrated.
