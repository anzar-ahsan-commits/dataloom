"""Typed business relationships between fields, without executable expressions."""

from __future__ import annotations

import math
import operator
from datetime import date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal, localcontext
from typing import TYPE_CHECKING, Annotated, Literal, Self

from pydantic import Field, model_validator

from dataloom.errors import PlanError
from dataloom.genome import Model, Scalar

if TYPE_CHECKING:
    from random import Random

    from dataloom.genome import Table


class Copy(Model):
    """Copy another field in the same generated row."""

    kind: Literal["copy"] = "copy"
    source: str


class Arithmetic(Model):
    """Combine numeric fields in order, then round using decimal half-up rounding."""

    kind: Literal["arithmetic"] = "arithmetic"
    operation: Literal["add", "subtract", "multiply"]
    fields: list[str] = Field(min_length=2)
    decimals: int = Field(default=2, ge=0, le=12)


class DateOffset(Model):
    """Offset an ISO date or timestamp by a seeded inclusive number of days."""

    kind: Literal["date_offset"] = "date_offset"
    source: str
    minimum_days: int = Field(default=0, ge=-365000, le=365000)
    maximum_days: int = Field(default=0, ge=-365000, le=365000)

    @model_validator(mode="after")
    def validate_interval(self) -> Self:
        """Reject reversed intervals before generation."""
        if self.minimum_days > self.maximum_days:
            raise ValueError("minimum_days exceeds maximum_days")
        return self


class Branch(Model):
    """One ordered conditional branch; the first matching branch wins."""

    operator: Literal["eq", "ne", "lt", "le", "gt", "ge"]
    value: Scalar
    then: Scalar


class Case(Model):
    """Choose a value based on another column, including explicit NULL branches."""

    kind: Literal["case"] = "case"
    source: str
    cases: list[Branch] = Field(min_length=1)
    otherwise: Scalar = None


Derivation = Annotated[Copy | Arithmetic | DateOffset | Case, Field(discriminator="kind")]


def dependencies(rule: Derivation) -> list[str]:
    """List source fields without interpreting any text as code."""
    return rule.fields if isinstance(rule, Arithmetic) else [rule.source]


def order_derivations(table: Table, rules: dict[str, Derivation]) -> list[str]:
    """Validate references/types and resolve a stable dependency order."""
    columns = {c.name: c for c in table.columns}
    numeric = ("INT", "SERIAL", "NUMERIC", "DECIMAL", "REAL", "FLOAT", "DOUBLE")
    for target, rule in rules.items():
        if target not in columns or set(dependencies(rule)) - columns.keys():
            raise PlanError(f"Unknown derived source or target in {table.name}.{target}")
        if isinstance(rule, Arithmetic):
            for name in [target, *rule.fields]:
                if not any(token in columns[name].sql_type.upper() for token in numeric):
                    raise PlanError(f"Arithmetic requires numeric columns: {table.name}.{name}")
        if isinstance(rule, DateOffset):
            for name in [target, rule.source]:
                kind = columns[name].sql_type.upper()
                if not (kind == "DATE" or "TIMESTAMP" in kind or kind == "DATETIME"):
                    raise PlanError(
                        f"Date offsets require date/timestamp columns: {table.name}.{name}"
                    )
            if (columns[target].sql_type.upper() == "DATE") != (
                columns[rule.source].sql_type.upper() == "DATE"
            ):
                raise PlanError("Date offsets must preserve date versus timestamp type")
    pending = {name: set(dependencies(rule)) & rules.keys() for name, rule in rules.items()}
    result = []
    while pending:
        ready = sorted(name for name, sources in pending.items() if not sources)
        if not ready:
            raise PlanError(f"Cyclic derived fields in {table.name}: {sorted(pending)}")
        for name in ready:
            result.append(name)
            del pending[name]
        for sources in pending.values():
            sources.difference_update(ready)
    return result


def derive(rule: Derivation, row: dict[str, Scalar], rng: Random) -> Scalar:
    """Evaluate a typed rule; arithmetic/date/copy propagate source NULLs."""
    if isinstance(rule, Arithmetic):
        values = [row[name] for name in rule.fields]
        if any(value is None for value in values):
            return None
        if any(
            isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v)
            for v in values
        ):
            raise PlanError("Arithmetic sources must contain finite numbers")
        with localcontext() as context:
            context.prec = 50
            numbers = [Decimal(str(v)) for v in values]
            operation = {"add": operator.add, "subtract": operator.sub, "multiply": operator.mul}[
                rule.operation
            ]
            result = numbers[0]
            for number in numbers[1:]:
                result = operation(result, number)
            if not result.is_finite() or result.adjusted() > 30:
                raise PlanError("Derived arithmetic exceeds the supported finite numeric range")
            result = result.quantize(Decimal(10) ** -rule.decimals, rounding=ROUND_HALF_UP)
            return int(result) if result == result.to_integral_value() else float(result)
    value = row[rule.source]
    if isinstance(rule, Copy):
        return value
    if isinstance(rule, DateOffset):
        if value is None:
            return None
        if not isinstance(value, str):
            raise PlanError("Date offset source must be an ISO date or timestamp")
        try:
            origin = (
                date.fromisoformat(value) if len(value) == 10 else datetime.fromisoformat(value)
            )
            return (
                origin + timedelta(days=rng.randint(rule.minimum_days, rule.maximum_days))
            ).isoformat()
        except (ValueError, OverflowError) as exc:
            raise PlanError(
                "Invalid date source or date offset outside the supported calendar"
            ) from exc
    for branch in rule.cases:
        if branch.operator in {"eq", "ne"}:
            matched = value == branch.value and (
                isinstance(value, bool) == isinstance(branch.value, bool)
            )
            if branch.operator == "ne":
                matched = not matched
        elif value is None or branch.value is None:
            matched = False
        else:
            if (
                isinstance(value, bool)
                or isinstance(branch.value, bool)
                or not isinstance(value, (int, float))
                or not isinstance(branch.value, (int, float))
            ):
                raise PlanError("Ordered case comparisons require numeric values")
            matched = {"lt": operator.lt, "le": operator.le, "gt": operator.gt, "ge": operator.ge}[
                branch.operator
            ](value, branch.value)
        if matched:
            return branch.then
    return rule.otherwise
