import pytest

from observable_production_agent.engine import LoopDetected, ProductionAgent


class Stub:
    def __init__(self, fail=False):
        self.fail = fail

    def complete(self, messages, *, model=None):
        if self.fail:
            raise RuntimeError("down")
        return "ok"


def test_canary_rolls_back_on_failure(tmp_path):
    agent = ProductionAgent(
        Stub(), Stub(fail=True), tmp_path / "metrics.db", canary_percent=100
    )
    with pytest.raises(RuntimeError):
        agent.run("hi", bucket=0)
    assert agent.canary_percent == 0
    assert agent.run("hi", bucket=0).variant == "stable"
    assert agent.metrics()["canary"]["errors"] == 1
    restarted = ProductionAgent(
        Stub(), Stub(), tmp_path / "metrics.db", canary_percent=100
    )
    assert restarted.run("hi", bucket=0).variant == "stable"
    assert agent.alerts()[0]["kind"] == "canary_rollback"


def test_loop_detection_and_prometheus(tmp_path):
    agent = ProductionAgent(
        Stub(), Stub(), tmp_path / "metrics.db", max_repeats_per_run=2
    )
    agent.run("same", run_id="r1")
    agent.run("same", run_id="r1")
    with pytest.raises(LoopDetected):
        agent.run("same", run_id="r1")
    assert agent.alerts()[0]["kind"] == "loop"
    assert 'agent_requests_total{variant="stable"} 2' in agent.prometheus_metrics()
