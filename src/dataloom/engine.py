"""Pure seeded generation, tuple-aware relationships, and validation receipts."""

from __future__ import annotations

import hashlib
import json
import math
import platform
from collections import Counter
from datetime import date, datetime, timedelta
from decimal import Decimal
from functools import lru_cache
from importlib.metadata import version
from random import Random
from typing import TYPE_CHECKING
from uuid import UUID

from faker import Faker
from pydantic import Field

from dataloom.constraints import evaluate, parse_check
from dataloom.derivations import derive, order_derivations
from dataloom.domains import Context, Registry
from dataloom.errors import GenerationError, PlanError
from dataloom.genome import Column, Genome, Model, Scalar, Table
from dataloom.plan import Plan, Rule
from dataloom.sqltypes import ColumnType, column_type

if TYPE_CHECKING:
    from sqlglot.expressions import Expression

Row = dict[str, Scalar]
Dataset = dict[str, list[Row]]

ATTEMPTS = 500


class Receipt(Model):
    """Replay provenance and observed results, without wall-clock metadata."""

    genome_hash: str
    genome_artifact_hash: str
    plan_hash: str
    data_hash: str
    seed: int
    versions: dict[str, str]
    row_counts: dict[str, int]
    validated: bool = True
    notes: list[str] = Field(default_factory=list)


def ordered_tables(genome: Genome, targets: set[str]) -> list[Table]:
    """Return stable parent-first order or explain missing parents and cycles."""
    tables = {t.name: t for t in genome.tables}
    if targets - tables.keys():
        raise PlanError(f"Unknown entities: {sorted(targets - tables.keys())}")
    remaining = {name: {fk.parent_table for fk in tables[name].foreign_keys} for name in targets}
    for name, parents in remaining.items():
        if parents - targets:
            raise PlanError(f"{name} requires parent entities: {sorted(parents - targets)}")
    result = []
    while remaining:
        ready = sorted(name for name, parents in remaining.items() if not parents)
        if not ready:
            raise PlanError(f"Cyclic foreign keys are not supported in v1: {sorted(remaining)}")
        for name in ready:
            result.append(tables[name])
            del remaining[name]
        for parents in remaining.values():
            parents.difference_update(ready)
    return result


def _fit(value: Scalar, kind: ColumnType) -> Scalar:
    """Truncate generated text to the column's declared length."""
    return value[: kind.length] if isinstance(value, str) and kind.length is not None else value


@lru_cache(maxsize=256)
def _radix(count: int, arity: int) -> int:
    """Get the smallest base whose arity digits address every row index."""
    radix = max(2, math.ceil(math.pow(count, 1.0 / arity)))
    while radix**arity < count:
        radix += 1
    return radix


def _ordinal(index: int, count: int, position: int, arity: int) -> int:
    """Spread row indexes across a candidate key so each member column varies."""
    if arity == 1:
        return index + 1
    radix = _radix(count, arity)
    divisor: int = radix ** (arity - 1 - position)
    return index // divisor % radix + 1


def _primitive(
    column: Column,
    rule: Rule,
    index: int,
    count: int,
    ctx: Context,
    registry: Registry,
    key: tuple[int, int] | None,
) -> Scalar:
    if rule.choices is not None:
        return ctx.rng.choice(rule.choices)
    kind = column_type(column.sql_type)
    unbounded = rule.minimum is None and rule.maximum is None
    semantic = rule.semantic_type or (
        column.classification.semantic_type if column.classification else None
    )
    if semantic and unbounded:
        if semantic not in registry.generators:
            raise PlanError(f"Unknown semantic type: {semantic}")
        return _fit(registry.generators[semantic](ctx), kind)
    if key is not None and unbounded and kind.family in ("integer", "text"):
        ordinal = _ordinal(index, count, *key)
        if kind.family == "integer":
            return ordinal
        label = f"test-{ordinal:06d}"
        return label if kind.length is None or len(label) <= kind.length else str(ordinal)
    low = rule.minimum if rule.minimum is not None else 0
    high = rule.maximum if rule.maximum is not None else 1000
    if low > high:
        raise PlanError(f"Invalid effective bounds for {column.name}")
    if column.profile and column.profile.quantiles and unbounded and kind.numeric:
        points = column.profile.quantiles
        bucket = ctx.rng.randrange(len(points) - 1)
        observed = ctx.rng.uniform(points[bucket], points[bucket + 1])
        return round(observed) if kind.family == "integer" else round(observed, kind.places)
    if kind.family == "integer":
        if math.ceil(low) > math.floor(high):
            raise PlanError(f"No integer exists within bounds for {column.name}")
        return ctx.rng.randint(math.ceil(low), math.floor(high))
    if kind.family == "decimal":
        return round(ctx.rng.uniform(low, high), kind.places)
    if kind.family == "boolean":
        return bool(ctx.rng.getrandbits(1))
    if kind.family == "timestamp":
        stamp = (
            ctx.reference_date - timedelta(days=ctx.rng.randrange(3650))
        ).isoformat() + "T12:00:00"
        return stamp + "+00:00" if kind.zoned else stamp
    if kind.family == "date":
        return (ctx.reference_date - timedelta(days=ctx.rng.randrange(3650))).isoformat()
    if kind.family == "uuid":
        return str(UUID(int=ctx.rng.getrandbits(128), version=4))
    if kind.family == "text":
        return _fit(f"test-{ctx.rng.getrandbits(64):016x}", kind)
    raise PlanError(
        f"Unsupported SQL type {column.sql_type} for {column.name}; add an explicit rule"
    )


def _row_error(table: Table, row: Row, checks: list[Expression]) -> str | None:
    """Explain the first violated type, length, nullability, or CHECK rule."""
    for column in table.columns:
        value = row[column.name]
        kind = column_type(column.sql_type)
        if value is None:
            if not column.nullable:
                return f"{column.name} is NULL but the column is NOT NULL"
            continue
        if kind.family is None:
            return f"{column.name} has unsupported type {column.sql_type}"
        if kind.family == "integer":
            if not isinstance(value, int) or isinstance(value, bool):
                return f"{column.name}={value!r} is not an integer"
            if not -(2 ** (kind.bits - 1)) <= value < 2 ** (kind.bits - 1):
                return f"{column.name}={value!r} is out of range for {column.sql_type}"
        elif kind.family == "decimal":
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(value)
            ):
                return f"{column.name}={value!r} is not a finite number"
            if kind.digits is not None and kind.scale is not None:
                number = Decimal(str(value))
                if abs(number) >= Decimal(10) ** (kind.digits - kind.scale):
                    return f"{column.name}={value!r} is out of range for {column.sql_type}"
                if number != number.quantize(Decimal(10) ** -kind.scale):
                    return f"{column.name}={value!r} needs more than {kind.scale} decimal places"
        elif kind.family == "boolean":
            if not isinstance(value, bool):
                return f"{column.name}={value!r} is not a boolean"
        elif kind.family == "text":
            if not isinstance(value, str):
                return f"{column.name}={value!r} is not a string"
            if kind.length is not None and len(value) > kind.length:
                return f"{column.name} is {len(value)} characters, over {column.sql_type}"
        else:
            if not isinstance(value, str):
                return f"{column.name}={value!r} is not a {kind.family} string"
            try:
                if kind.family == "date":
                    date.fromisoformat(value)
                elif kind.family == "uuid":
                    UUID(value)
                else:
                    datetime.fromisoformat(value)
            except ValueError:
                return f"{column.name}={value!r} is not a valid {kind.family}"
    try:
        for expression, sql in zip(checks, table.checks, strict=True):
            if evaluate(expression, row) is False:
                return f"CHECK ({sql}) is false"
    except (TypeError, ArithmeticError) as exc:
        raise PlanError(f"CHECK types are incompatible in {table.name}: {exc}") from exc
    return None


def validate_dataset(genome: Genome, data: Dataset) -> None:
    """Independently check rows, candidate keys, and composite FK membership."""
    for table in ordered_tables(genome, set(data)):
        checks = [parse_check(check) for check in table.checks]
        keys = [key for key in [table.primary_key, *table.unique] if key]
        seen: list[set[tuple[Scalar, ...]]] = [set() for _ in keys]
        for row in data[table.name]:
            if set(row) != {c.name for c in table.columns}:
                raise GenerationError(f"Row in {table.name} does not match its columns")
            reason = _row_error(table, row, checks)
            if reason is not None:
                raise GenerationError(f"Invalid row in {table.name}: {reason}")
            for key, pool in zip(keys, seen, strict=True):
                value = tuple(row[c] for c in key)
                if None not in value:
                    if value in pool:
                        raise GenerationError(f"Duplicate key in {table.name}: {key}")
                    pool.add(value)
        for fk in table.foreign_keys:
            parents = {tuple(r[c] for c in fk.parent_columns) for r in data[fk.parent_table]}
            for row in data[table.name]:
                value = tuple(row[c] for c in fk.columns)
                if None not in value and value not in parents:
                    raise GenerationError(f"Orphan reference in {table.name}: {fk.columns}")


def _candidate_positions(table: Table, synthesized: set[str]) -> dict[str, tuple[int, int]]:
    """Map each key column DataLoom generates to its position within that key."""
    memberships = Counter(
        name
        for candidate in {tuple(key) for key in [table.primary_key, *table.unique] if key}
        for name in candidate
        if name in synthesized
    )
    # A member shared by candidate keys must not inherit a repeating digit from
    # whichever composite key happened to be visited first.
    positions: dict[str, tuple[int, int]] = {
        name: (0, 1) for name, occurrences in memberships.items() if occurrences > 1
    }
    for candidate in [table.primary_key, *table.unique]:
        members = [name for name in candidate if name in synthesized]
        for position, name in enumerate(members):
            positions.setdefault(name, (position, len(members)))
    return positions


def generate(
    genome: Genome, plan: Plan, registry: Registry | None = None
) -> tuple[Dataset, Receipt]:
    """Generate a fully validated in-memory dataset without network or LLM calls."""
    registry = registry or Registry.builtin()
    original_genome = genome
    if not plan.use_profiles:
        genome = genome.model_copy(deep=True)
        for entity in genome.tables:
            for field in entity.columns:
                field.profile = None
    data: Dataset = {}
    notes = []
    for table in ordered_tables(genome, set(plan.entities)):
        spec = plan.entities[table.name]
        columns = {c.name: c for c in table.columns}
        if spec.rules.keys() - columns.keys():
            raise PlanError(f"Unknown rule columns in {table.name}")
        if any(c.generated for c in table.columns):
            raise PlanError(f"Computed columns unsupported in v1: {table.name}")
        unsupported = [c for c in table.columns if column_type(c.sql_type).family is None]
        if unsupported:
            raise PlanError(
                f"Unsupported SQL type: {unsupported[0].sql_type} "
                f"on {table.name}.{unsupported[0].name}"
            )
        fk_columns = [c for fk in table.foreign_keys for c in fk.columns]
        if len(fk_columns) != len(set(fk_columns)):
            raise PlanError(f"Overlapping FK columns unsupported in v1: {table.name}")
        if set(fk_columns) & spec.rules.keys():
            raise PlanError("FK values come from parent pools; direct FK overrides are unsupported")
        derived_rules = {
            name: rule.derive for name, rule in spec.rules.items() if rule.derive is not None
        }
        derived_order = order_derivations(table, derived_rules)
        checks = [parse_check(check) for check in table.checks]
        derived = int.from_bytes(
            hashlib.sha256(f"{plan.seed}:{table.name}".encode()).digest(), "big"
        )
        rng = Random(derived)
        faker = Faker("en_US")
        faker.seed_instance(derived)
        ctx = Context(rng, faker, plan.reference_date)
        parent_rows: list[Row | None]
        if spec.fanout:
            fan = spec.fanout
            if not any(
                fk.parent_table == fan.parent and fk.columns == fan.foreign_key
                for fk in table.foreign_keys
            ):
                raise PlanError(f"Fanout must identify a real FK on {table.name}")
            parent_rows = []
            for fan_row in data[fan.parent]:
                count = rng.randint(fan.minimum, fan.maximum)
                if len(parent_rows) + count > plan.max_rows:
                    raise PlanError("Fanout exceeds max_rows")
                parent_rows.extend([fan_row] * count)
        else:
            if (spec.rows or 0) > plan.max_rows:
                raise PlanError("Requested rows exceed max_rows")
            parent_rows = [None] * (spec.rows or 0)
        count = len(parent_rows)
        if count + sum(len(rows) for rows in data.values()) > plan.max_rows:
            raise PlanError("Total rows exceed max_rows")
        key_positions = _candidate_positions(
            table,
            {c.name for c in table.columns if c.name not in fk_columns} - derived_rules.keys(),
        )
        quotas: dict[str, list[Scalar]] = {}
        nulls: dict[str, set[int]] = {}
        for column in table.columns:
            if (
                column.name not in spec.rules
                and column.name not in fk_columns
                and column.nullable
                and column.profile
                and column.profile.sampled_rows
            ):
                nulls[column.name] = set(
                    rng.sample(range(count), math.floor(count * column.profile.null_rate + 0.5))
                )
        for name, rule in spec.rules.items():
            if rule.proportion is not None:
                quota = math.floor(count * rule.proportion + 0.5)
                values = [rule.value] * quota + [rule.otherwise] * (count - quota)
                rng.shuffle(values)
                quotas[name] = values
            if rule.null_rate:
                if not columns[name].nullable:
                    raise PlanError(f"Cannot inject nulls into required column {table.name}.{name}")
                nulls[name] = set(
                    rng.sample(range(count), math.floor(count * rule.null_rate + 0.5))
                )
        keys = [key for key in [table.primary_key, *table.unique] if key]
        seen: list[set[tuple[Scalar, ...]]] = [set() for _ in keys]
        rows: list[Row] = []
        for index, fan_parent in enumerate(parent_rows):
            first: Row | None = None
            reason: str | None = None
            duplicate: list[str] | None = None
            for _attempt in range(ATTEMPTS):
                row: Row = {}
                for column in table.columns:
                    name = column.name
                    if name in fk_columns or name in derived_rules:
                        continue
                    rule = spec.rules.get(name, Rule())
                    row[name] = (
                        quotas[name][index]
                        if name in quotas
                        else None
                        if index in nulls.get(name, set())
                        else _primitive(
                            column, rule, index, count, ctx, registry, key_positions.get(name)
                        )
                    )
                for fk in table.foreign_keys:
                    pool = data[fk.parent_table]
                    if not pool:
                        raise PlanError(f"No generated parents for {table.name}: {fk.parent_table}")
                    parent = (
                        fan_parent
                        if spec.fanout and fk.columns == spec.fanout.foreign_key
                        else rng.choice(pool)
                    )
                    assert parent is not None
                    row.update(
                        {
                            child: parent[target]
                            for child, target in zip(fk.columns, fk.parent_columns, strict=True)
                        }
                    )
                for name in derived_order:
                    row[name] = derive(derived_rules[name], row, rng)
                tuples = [tuple(row[c] for c in key) for key in keys]
                reason = _row_error(table, row, checks)
                duplicate = (
                    next(
                        (
                            key
                            for key, value, taken in zip(keys, tuples, seen, strict=True)
                            if None not in value and value in taken
                        ),
                        None,
                    )
                    if reason is None
                    else None
                )
                if reason is None and duplicate is None:
                    for value, seen_pool in zip(tuples, seen, strict=True):
                        seen_pool.add(value)
                    rows.append(row)
                    break
                if first is None:
                    first = row
            else:
                advice = (
                    "Every attempt produced identical values, so retrying cannot help: a plan "
                    "rule contradicts the constraint."
                    if row == first
                    else "Widen or relax the conflicting rule."
                )
                raise GenerationError(
                    f"Cannot satisfy constraints for {table.name} row {index + 1} after "
                    f"{ATTEMPTS} attempts: {reason or f'duplicate candidate key {duplicate}'}. "
                    f"{advice} No output was written."
                )
        data[table.name] = rows
        if any(c.default for c in table.columns):
            notes.append(f"{table.name}: explicit synthetic values replace database defaults")
    validate_dataset(genome, data)

    def digest(value: str) -> str:
        return hashlib.sha256(value.encode()).hexdigest()

    receipt = Receipt(
        genome_hash=genome.fingerprint(),
        genome_artifact_hash=digest(original_genome.model_dump_json()),
        plan_hash=digest(plan.model_dump_json()),
        data_hash=digest(json.dumps(data, sort_keys=True)),
        seed=plan.seed,
        versions={
            "python": platform.python_version(),
            **{
                name: version(name)
                for name in ("dataloom", "faker", "pydantic", "sqlglot", "sqlalchemy")
            },
            **{f"pack:{name}": pack.version for name, pack in registry.packs.items()},
        },
        row_counts={name: len(rows) for name, rows in data.items()},
        notes=notes,
    )
    return data, receipt
