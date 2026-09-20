# Contributing to DataLoom

Use Python 3.11+ and install `python -m pip install -e ".[dev]"`. Before submitting:

```sh
python -m ruff check src tests examples
python -m ruff format --check src tests examples
python -m mypy src/dataloom
python -m pytest
```

Public functions/classes need type hints and docstrings. Tests should check
observable invariants, failure handling, and replay—not only mock call counts.
Keep each milestone or coherent feature in a separate commit. Explain the problem,
resulting behavior, validation, and supported limits in your PR.

Never contribute employer schemas, internal identifiers, proprietary structures,
production samples, credentials, or confidential documentation. Use independently
designed fictional fixtures and public standards with compatible attribution.

## Domain packs

A pack exports a `DomainPack(name, version, generators, templates)`. Generators
accept a `Context` and return a JSON scalar. Templates are zero-argument functions
returning a `Genome`. Keep domain knowledge out of the relational engine.

```python
from dataloom.domains import Context, DomainPack

def sample_ticket_state(context: Context) -> str:
    """Produce a test ticket state using the supplied RNG."""
    return context.rng.choice(("queued", "active", "closed"))

PACK = DomainPack(
    name="example_support",
    version="1",
    generators={"support_ticket_state": sample_ticket_state},
)
```

Register it explicitly with `registry.register(PACK)`, or publish this entry point:

```toml
[project.entry-points."dataloom.domain_packs"]
example_support = "your_package:PACK"
```

The CLI/service discovers installed entry points. Direct `Registry.builtin()`
does not discover external plugins unless `discover=True`. Plugin imports execute
Python: install trusted packs only. Duplicate pack or semantic names fail instead
of silently replacing existing behavior. Qualified templates use `pack:template`.

Use `context.rng`, `context.faker`, and `context.reference_date`. Do not read the
clock, access network services, mutate global RNGs, or depend on external state
during generation. Add deterministic tests and standards/reference attribution.
Bump the pack version whenever outputs change. Future finance and retail packs
should follow this interface; neither is implemented by the core project.

## Connectors and providers

Implement `Connector.write(genome, data, receipt) -> list[str]` for a transport.
Validate before external writes; document atomicity and retry behavior. Keep
transport details outside `engine.py`. MLLP/Kafka belong here when implemented.

Implement `Provider.structured(prompt, output_model)` for another LLM vendor.
Return the validated Pydantic model and raise a useful error for invalid responses.
Provider SDK imports belong in adapters, never in generation business logic.

## Schema or plan changes

Both artifact formats carry `format_version`. Breaking changes require a new
version and documented migration policy. Preserve composite-column ordering.
Reject unsupported constructs explicitly rather than dropping constraints. Add
regression fixtures for DDL and live reflection where appropriate.
