"""Provider authoring is replaceable and never needed to replay saved plans."""

from pathlib import Path
from typing import TypeVar

from pydantic import BaseModel

from dataloom.service import GenerateInput, IntrospectInput, Service

T = TypeVar("T", bound=BaseModel)


class PlanProvider:
    calls = 0

    def structured(self, prompt: str, output: type[T]) -> T:
        self.calls += 1
        assert "widgets" in prompt
        assert "sql_type" in prompt and "primary_key" in prompt and "checks" in prompt
        assert "email" in prompt
        return output.model_validate({"seed": 123, "entities": {"widgets": {"rows": 5}}})


def test_authored_plan_replays_without_provider(tmp_path: Path) -> None:
    (tmp_path / "schema.sql").write_text("CREATE TABLE widgets(id INT PRIMARY KEY)")
    provider = PlanProvider()
    service = Service(tmp_path, provider)
    service.introspect(IntrospectInput(ddl_file="schema.sql"))
    authored = service.generate(
        GenerateInput(
            genome_file=".dataloom/genome.json", request="five widgets", output="authored"
        )
    )
    assert provider.calls == 1
    replay = Service(tmp_path).generate(
        GenerateInput(
            genome_file="authored/genome.json", plan_file="authored/plan.json", output="replay"
        )
    )
    assert replay.receipt == authored.receipt
