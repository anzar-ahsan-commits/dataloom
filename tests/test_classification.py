"""Classification uses metadata only and caches validated results."""

from typing import TypeVar

from pydantic import BaseModel

from dataloom.classification import classify
from dataloom.introspection import parse_ddl

T = TypeVar("T", bound=BaseModel)


class FakeProvider:
    calls = 0

    def structured(self, prompt: str, output: type[T]) -> T:
        self.calls += 1
        assert "contact" in prompt
        return output.model_validate({"labels": {"people.contact": "email"}})


def test_cache_skips_second_provider_call() -> None:
    genome = parse_ddl("CREATE TABLE people (contact TEXT)")
    provider = FakeProvider()
    first = classify(genome, provider)
    assert classify(first, provider) == first
    assert provider.calls == 1
    classify(first, provider, refresh=True)
    assert provider.calls == 2
