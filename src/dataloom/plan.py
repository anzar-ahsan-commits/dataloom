"""Declarative, versioned generation instructions with no executable expressions."""

from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING, Literal, Self

import yaml
from pydantic import Field, model_validator

from dataloom.genome import Genome, Model, Scalar

if TYPE_CHECKING:
    from pathlib import Path

    from dataloom.providers import Provider


class Rule(Model):
    """Column overrides; proportions select an exact rounded quota of rows."""

    semantic_type: str | None = None
    choices: list[Scalar] | None = Field(default=None, min_length=1)
    minimum: float | None = None
    maximum: float | None = None
    null_rate: float = Field(default=0, ge=0, le=1)
    proportion: float | None = Field(default=None, ge=0, le=1)
    value: Scalar = None
    otherwise: Scalar = None

    @model_validator(mode="after")
    def validate_rule(self) -> Self:
        """Reject ambiguous generators and inverted bounds."""
        modes = sum(
            (
                self.semantic_type is not None,
                self.choices is not None,
                self.minimum is not None or self.maximum is not None,
                self.proportion is not None,
            )
        )
        if modes > 1:
            raise ValueError("Use one of semantic_type, choices, bounds, or proportion")
        if self.minimum is not None and self.maximum is not None and self.minimum > self.maximum:
            raise ValueError("minimum exceeds maximum")
        if self.proportion is not None and self.null_rate:
            raise ValueError("Proportion rules cannot also specify null_rate")
        return self


class Fanout(Model):
    """Number of children per generated parent along one explicit FK."""

    parent: str
    foreign_key: list[str] = Field(min_length=1)
    minimum: int = Field(default=1, ge=0)
    maximum: int = Field(default=1, ge=0)

    @model_validator(mode="after")
    def validate_bounds(self) -> Self:
        """Require a nonempty inclusive interval."""
        if self.minimum > self.maximum:
            raise ValueError("Fanout minimum exceeds maximum")
        return self


class EntityPlan(Model):
    """One target table with fixed count or parent-relative fanout."""

    rows: int | None = Field(default=None, ge=0)
    fanout: Fanout | None = None
    rules: dict[str, Rule] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_count(self) -> Self:
        """Require exactly one count mode."""
        if (self.rows is None) == (self.fanout is None):
            raise ValueError("Specify exactly one of rows or fanout")
        return self


class Plan(Model):
    """CI-safe execution artifact; all temporal defaults are explicit."""

    format_version: Literal[1] = 1
    seed: int = 42
    reference_date: date = date(2025, 1, 1)
    entities: dict[str, EntityPlan] = Field(min_length=1)
    max_rows: int = Field(default=100000, ge=1, le=10000000)

    @classmethod
    def load(cls, path: Path) -> Plan:
        """Load JSON or YAML with safe parsing and strict validation."""
        return cls.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))

    def save(self, path: Path) -> None:
        """Persist a reviewable JSON plan (also valid YAML)."""
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(self.model_dump_json(indent=2) + "\n", encoding="utf-8")


def author_plan(request: str, genome: Genome, provider: Provider) -> Plan:
    """Ask a provider to author a plan using metadata, excluding observed values."""
    metadata = {
        table.name: {
            "columns": [c.name for c in table.columns],
            "foreign_keys": [f.model_dump() for f in table.foreign_keys],
        }
        for table in genome.tables
    }
    return provider.structured(
        f"Author a generation plan for this request: {request}\nSchema: {metadata}\n"
        "Include all required parents. Use exact proportion rules for percentage requests.",
        Plan,
    )
