"""The default provider adapter validates responses without live API calls."""

from types import SimpleNamespace

import pytest

from dataloom.errors import LLMResponseError
from dataloom.plan import Plan
from dataloom.providers import AnthropicProvider


@pytest.mark.parametrize(
    "payload",
    [
        {"entities": {"items": {"rows": 3}}},
        {"entities": {"items": {"rows": -1}}},
        None,
    ],
)
def test_structured_provider_contract(monkeypatch: pytest.MonkeyPatch, payload: object) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "fictional-test-key")
    provider = AnthropicProvider("fictional-test-model")

    def create(**kwargs: object) -> SimpleNamespace:
        assert kwargs["model"] == "fictional-test-model"
        assert kwargs["tool_choice"] == {"type": "tool", "name": "submit"}
        blocks = (
            []
            if payload is None
            else [SimpleNamespace(type="tool_use", name="submit", input=payload)]
        )
        return SimpleNamespace(content=blocks)

    monkeypatch.setattr(provider.client.messages, "create", create)
    try:
        if payload == {"entities": {"items": {"rows": 3}}}:
            assert provider.structured("three items", Plan).entities["items"].rows == 3
        else:
            with pytest.raises(LLMResponseError):
                provider.structured("invalid plan", Plan)
    finally:
        provider.client.close()
