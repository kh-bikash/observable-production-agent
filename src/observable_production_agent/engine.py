from __future__ import annotations

import json
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
    def __init__(self, stable: LLM, canary: LLM, db_path: str | Path, *, canary_percent: int = 0, max_failure_rate: float = 0.2):
        if not 0 <= canary_percent <= 100:
            raise ValueError("canary_percent must be 0..100")
        self.stable, self.canary, self.db_path = stable, canary, str(db_path)
        self.canary_percent, self.max_failure_rate = canary_percent, max_failure_rate
        with self._db() as db:
            db.execute("CREATE TABLE IF NOT EXISTS calls(id INTEGER PRIMARY KEY, variant TEXT, latency_ms REAL, estimated_cost_usd REAL, error INTEGER, created_at REAL)")
            db.execute("CREATE TABLE IF NOT EXISTS rollout(key TEXT PRIMARY KEY, value INTEGER NOT NULL)")
            db.execute("INSERT OR IGNORE INTO rollout(key,value) VALUES('canary_percent',?)", (canary_percent,))

    def _db(self):
        return sqlite3.connect(self.db_path, timeout=10)

    def run(self, prompt: str, *, bucket: int | None = None) -> Response:
        with _span("agent.run") as span:
            return self._run(prompt, bucket=bucket, span=span)

    def _run(self, prompt: str, *, bucket: int | None, span) -> Response:
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
            db.execute("INSERT INTO calls(variant,latency_ms,estimated_cost_usd,error,created_at) VALUES(?,?,?,?,?)", (variant, latency, estimated_cost, error, time.time()))
        log.info(json.dumps({"trace_id": trace_id, "variant": variant, "latency_ms": latency, "estimated_cost_usd": estimated_cost, "error": error}))
        if variant == "canary" and self.failure_rate("canary") > self.max_failure_rate:
            self.canary_percent = 0
            with self._db() as db:
                db.execute("UPDATE rollout SET value=0 WHERE key='canary_percent'")
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
