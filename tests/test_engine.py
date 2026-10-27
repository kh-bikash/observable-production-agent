import pytest
from observable_production_agent.engine import ProductionAgent


class Stub:
    def __init__(self, fail=False):
        self.fail = fail

    def complete(self, messages, *, model=None):
        if self.fail:
            raise RuntimeError("down")
        return "ok"


def test_canary_rolls_back_on_failure(tmp_path):
    agent = ProductionAgent(Stub(), Stub(fail=True), tmp_path / "metrics.db", canary_percent=100)
    with pytest.raises(RuntimeError):
        agent.run("hi", bucket=0)
    assert agent.canary_percent == 0
    assert agent.run("hi", bucket=0).variant == "stable"
    assert agent.metrics()["canary"]["errors"] == 1
    restarted = ProductionAgent(Stub(), Stub(), tmp_path / "metrics.db", canary_percent=100)
    assert restarted.run("hi", bucket=0).variant == "stable"
