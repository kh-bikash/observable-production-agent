from __future__ import annotations

import json
import hashlib
import logging
import random
import sqlite3
import time
import uuid
from contextlib import nullcontext
from dataclasses import dataclass
from pathlib import Path

from .llm import LLM

log = logging.getLogger(__name__)


class LoopDetected(RuntimeError):
    pass


def _span(name: str):
    try:
        from opentelemetry import trace
        return trace.get_tracer(__name__).start_as_current_span(name)
    except ImportError:
        return nullcontext()


@dataclass(frozen=True)
class Response:
    answer: str
    variant: str
    trace_id: str
    latency_ms: float


class ProductionAgent:
    def __init__(self, stable: LLM, canary: LLM, db_path: str | Path, *, canary_percent: int = 0,
                 max_failure_rate: float = 0.2, max_repeats_per_run: int = 3):
        if not 0 <= canary_percent <= 100:
            raise ValueError("canary_percent must be 0..100")
        self.stable, self.canary, self.db_path = stable, canary, str(db_path)
        self.canary_percent, self.max_failure_rate = canary_percent, max_failure_rate
        self.max_repeats_per_run = max_repeats_per_run
        if max_repeats_per_run < 1:
            raise ValueError("max_repeats_per_run must be positive")
        with self._db() as db:
            db.execute("CREATE TABLE IF NOT EXISTS calls(id INTEGER PRIMARY KEY, variant TEXT, latency_ms REAL, estimated_cost_usd REAL, error INTEGER, created_at REAL)")
            columns = {row[1] for row in db.execute("PRAGMA table_info(calls)")}
            if "run_id" not in columns:
                db.execute("ALTER TABLE calls ADD COLUMN run_id TEXT")
            if "prompt_hash" not in columns:
                db.execute("ALTER TABLE calls ADD COLUMN prompt_hash TEXT")
            db.execute("CREATE TABLE IF NOT EXISTS alerts(id INTEGER PRIMARY KEY, kind TEXT, detail TEXT, created_at REAL)")
            db.execute("CREATE TABLE IF NOT EXISTS rollout(key TEXT PRIMARY KEY, value INTEGER NOT NULL)")
            db.execute("INSERT OR IGNORE INTO rollout(key,value) VALUES('canary_percent',?)", (canary_percent,))

    def _db(self):
        return sqlite3.connect(self.db_path, timeout=10)

    def run(self, prompt: str, *, bucket: int | None = None, run_id: str | None = None) -> Response:
        with _span("agent.run") as span:
            return self._run(prompt, bucket=bucket, span=span, run_id=run_id)

    def _run(self, prompt: str, *, bucket: int | None, span, run_id: str | None) -> Response:
        if not prompt.strip() or len(prompt) > 16_000:
            raise ValueError("prompt must be nonempty and at most 16000 characters")
        run_id = run_id or uuid.uuid4().hex
        prompt_hash = hashlib.sha256(prompt.encode()).hexdigest()
        with self._db() as db:
            repeats = db.execute("SELECT count(*) FROM calls WHERE run_id=? AND prompt_hash=?", (run_id, prompt_hash)).fetchone()[0]
            if repeats >= self.max_repeats_per_run:
                db.execute("INSERT INTO alerts(kind,detail,created_at) VALUES('loop',?,?)", (run_id, time.time()))
        if repeats >= self.max_repeats_per_run:
            raise LoopDetected("Repeated prompt limit exceeded for run " + run_id)
        bucket = random.randrange(100) if bucket is None else bucket
        with self._db() as db:
            active_percent = db.execute("SELECT value FROM rollout WHERE key='canary_percent'").fetchone()[0]
        variant = "canary" if bucket < active_percent else "stable"
        trace_id = uuid.uuid4().hex
        if span is not None:
            span.set_attribute("agent.variant", variant)
            span.set_attribute("agent.trace_id", trace_id)
        start = time.monotonic()
        try:
            answer = (self.canary if variant == "canary" else self.stable).complete([{"role": "user", "content": prompt}])
            error = 0
        except Exception:
            error, answer = 1, ""
            log.exception("agent call failed", extra={"trace_id": trace_id, "variant": variant})
        latency = (time.monotonic() - start) * 1000
        estimated_cost = (len(prompt) + len(answer)) / 4 * 0.000001
        with self._db() as db:
            db.execute("INSERT INTO calls(variant,latency_ms,estimated_cost_usd,error,created_at,run_id,prompt_hash) VALUES(?,?,?,?,?,?,?)", (variant, latency, estimated_cost, error, time.time(), run_id, prompt_hash))
        log.info(json.dumps({"trace_id": trace_id, "variant": variant, "latency_ms": latency, "estimated_cost_usd": estimated_cost, "error": error}))
        if variant == "canary" and self.failure_rate("canary") > self.max_failure_rate:
            self.canary_percent = 0
            with self._db() as db:
                db.execute("UPDATE rollout SET value=0 WHERE key='canary_percent'")
                db.execute("INSERT INTO alerts(kind,detail,created_at) VALUES('canary_rollback',?,?)", (trace_id, time.time()))
            log.warning("canary rolled back", extra={"trace_id": trace_id})
        if error:
            if span is not None:
                span.set_attribute("agent.error", True)
            raise RuntimeError("Agent call failed; trace_id=" + trace_id)
        return Response(answer, variant, trace_id, latency)

    def set_canary_percent(self, percent: int) -> None:
        if not 0 <= percent <= 100:
            raise ValueError("canary_percent must be 0..100")
        with self._db() as db:
            db.execute("UPDATE rollout SET value=? WHERE key='canary_percent'", (percent,))
        self.canary_percent = percent

    def failure_rate(self, variant: str, *, window: int = 100) -> float:
        with self._db() as db:
            rows = db.execute("SELECT error FROM calls WHERE variant=? ORDER BY id DESC LIMIT ?", (variant, window)).fetchall()
        return sum(row[0] for row in rows) / len(rows) if rows else 0.0

    def metrics(self) -> dict[str, dict[str, float]]:
        with self._db() as db:
            rows = db.execute("SELECT variant,count(*),avg(latency_ms),sum(estimated_cost_usd),sum(error) FROM calls GROUP BY variant").fetchall()
        return {variant: {"requests": count, "avg_latency_ms": latency, "estimated_cost_usd": cost, "errors": errors} for variant, count, latency, cost, errors in rows}

    def alerts(self, *, limit: int = 100) -> list[dict[str, object]]:
        with self._db() as db:
            rows = db.execute("SELECT kind,detail,created_at FROM alerts ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
        return [{"kind": kind, "detail": detail, "created_at": created_at} for kind, detail, created_at in rows]

    def prometheus_metrics(self) -> str:
        lines = ["# TYPE agent_requests_total counter", "# TYPE agent_errors_total counter", "# TYPE agent_estimated_cost_usd counter", "# TYPE agent_avg_latency_ms gauge", "# TYPE agent_alerts_total counter", "# TYPE agent_canary_percent gauge"]
        for variant, values in self.metrics().items():
            label = '{variant="' + variant + '"}'
            lines.extend([f"agent_requests_total{label} {values['requests']}",
                          f"agent_errors_total{label} {values['errors']}",
                          f"agent_estimated_cost_usd{label} {values['estimated_cost_usd']}",
                          f"agent_avg_latency_ms{label} {values['avg_latency_ms']}"])
        with self._db() as db:
            alert_counts = db.execute("SELECT kind,count(*) FROM alerts GROUP BY kind").fetchall()
            percent = db.execute("SELECT value FROM rollout WHERE key='canary_percent'").fetchone()[0]
        for kind, count in {"loop": 0, "canary_rollback": 0, **dict(alert_counts)}.items():
            lines.append(f'agent_alerts_total{{kind="{kind}"}} {count}')
        lines.append(f"agent_canary_percent {percent}")
        return "\n".join(lines) + "\n"
