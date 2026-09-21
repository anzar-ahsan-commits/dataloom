"""Classification uses metadata only and caches validated results."""

from typing import TypeVar

import pytest
from pydantic import BaseModel

from dataloom.classification import ALIASES, classify, semantic_for
from dataloom.introspection import parse_ddl

T = TypeVar("T", bound=BaseModel)


class FakeProvider:
    calls = 0

    def structured(self, prompt: str, output: type[T]) -> T:
        self.calls += 1
        assert "contact" in prompt
        return output.model_validate({"labels": {"people.contact": "email"}})


def test_cache_skips_second_provider_call() -> None:
    genome = parse_ddl("CREATE TABLE people (id INT PRIMARY KEY, contact TEXT)")
    provider = FakeProvider()
    first = classify(genome, provider)
    assert classify(first, provider) == first
    assert provider.calls == 1
    classify(first, provider, refresh=True)
    assert provider.calls == 2


@pytest.mark.parametrize(
    ("name", "label"),
    [
        ("customer_email", "email"),
        ("shipping_city", "city"),
        ("internal_notes", "description"),
        ("EmailAddress", "email"),
        ("firstName", "first_name"),
        ("zipCode", "postcode"),
        ("billing_state", "us_state"),
        ("company_name", "company"),
    ],
)
def test_token_spans_and_camel_case_are_recognized(name: str, label: str) -> None:
    matched = semantic_for(name, set(ALIASES.values()))
    assert matched is not None and matched[0] == label


@pytest.mark.parametrize("name", ["product_name", "order_state", "status", "amount", "created_at"])
def test_generic_words_do_not_borrow_a_person_or_place_meaning(name: str) -> None:
    assert semantic_for(name, set(ALIASES.values())) is None
