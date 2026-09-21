"""Pure seeded generation, tuple-aware relationships, and validation receipts."""

from __future__ import annotations

import hashlib
import json
import math
import platform
import re
from datetime import date, datetime, timedelta
from decimal import Decimal
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

if TYPE_CHECKING:
    from sqlglot.expressions import Expression

Row = dict[str, Scalar]
Dataset = dict[str, list[Row]]


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


def _primitive(
    column: Column, rule: Rule, index: int, ctx: Context, registry: Registry, primary: bool
) -> Scalar:
    if rule.choices is not None:
        return ctx.rng.choice(rule.choices)
    semantic = rule.semantic_type or (
        column.classification.semantic_type if column.classification else None
    )
    if semantic and rule.minimum is None and rule.maximum is None:
        if semantic not in registry.generators:
            raise PlanError(f"Unknown semantic type: {semantic}")
        return registry.generators[semantic](ctx)
    kind = column.sql_type.upper()
    low = rule.minimum if rule.minimum is not None else 0
    high = rule.maximum if rule.maximum is not None else 1000
    if low > high:
        raise PlanError(f"Invalid effective bounds for {column.name}")
    if (
        column.profile
        and column.profile.quantiles
        and rule.minimum is None
        and rule.maximum is None
    ):
        points = column.profile.quantiles
        bucket = ctx.rng.randrange(len(points) - 1)
        observed = ctx.rng.uniform(points[bucket], points[bucket + 1])
        if not primary and ("INT" in kind or "SERIAL" in kind):
            return round(observed)
        if any(t in kind for t in ("NUMERIC", "DECIMAL", "REAL", "FLOAT", "DOUBLE")):
            scale = re.search(r"\(\d+,\s*(\d+)\)", kind)
            return round(observed, int(scale[1]) if scale else 2)
    if "INT" in kind or "SERIAL" in kind:
        if math.ceil(low) > math.floor(high):
            raise PlanError(f"No integer exists within bounds for {column.name}")
        return (
            index + 1
            if primary and rule.minimum is None and rule.maximum is None
            else (ctx.rng.randint(math.ceil(low), math.floor(high)))
        )
    if any(t in kind for t in ("NUMERIC", "DECIMAL", "REAL", "FLOAT", "DOUBLE")):
        scale = re.search(r"\(\d+,\s*(\d+)\)", kind)
        return round(ctx.rng.uniform(low, high), int(scale[1]) if scale else 2)
    if "BOOL" in kind:
        return bool(ctx.rng.getrandbits(1))
    if "TIMESTAMP" in kind or "DATETIME" in kind:
        timestamp = (
            ctx.reference_date - timedelta(days=ctx.rng.randrange(3650))
        ).isoformat() + "T12:00:00"
        return (
            timestamp + "+00:00" if "WITH TIME ZONE" in kind or kind == "TIMESTAMPTZ" else timestamp
        )
    if kind == "DATE":
        return (ctx.reference_date - timedelta(days=ctx.rng.randrange(3650))).isoformat()
    if kind == "UUID":
        return str(UUID(int=ctx.rng.getrandbits(128), version=4))
    if any(t in kind for t in ("CHAR", "TEXT")):
        length = re.search(r"\((\d+)\)", kind)
        limit = int(length[1]) if length else 40
        value = str(index + 1) if primary else f"test-{ctx.rng.getrandbits(64):016x}"
        return value[:limit]
    raise PlanError(
        f"Unsupported SQL type {column.sql_type} for {column.name}; add an explicit rule"
    )


def _valid_row(table: Table, row: Row, checks: list[Expression]) -> bool:
    for column in table.columns:
        value = row[column.name]
        if value is None:
            if not column.nullable:
                return False
            continue
        kind = column.sql_type.upper()
        if ("INT" in kind or "SERIAL" in kind) and (
            not isinstance(value, int) or isinstance(value, bool)
        ):
            return False
        if "INT" in kind or "SERIAL" in kind:
            bits = 16 if "SMALL" in kind else 64 if "BIG" in kind else 32
            if not isinstance(value, int) or not -(2 ** (bits - 1)) <= value < 2 ** (bits - 1):
                return False
        if any(t in kind for t in ("NUMERIC", "DECIMAL", "REAL", "FLOAT", "DOUBLE")) and (
            not isinstance(value, (int, float))
            or isinstance(value, bool)
            or not math.isfinite(value)
        ):
            return False
        if "BOOL" in kind and not isinstance(value, bool):
            return False
        precision = re.search(r"(?:NUMERIC|DECIMAL)\((\d+),\s*(\d+)\)", kind)
        if precision:
            digits, scale = int(precision[1]), int(precision[2])
            number = Decimal(str(value))
            if abs(number) >= Decimal(10) ** (digits - scale):
                return False
            if number != number.quantize(Decimal(10) ** -scale):
                return False
        if kind == "DATE" or "TIMESTAMP" in kind or kind == "DATETIME" or kind == "UUID":
            if not isinstance(value, str):
                return False
            try:
                if kind == "DATE":
                    date.fromisoformat(value)
                elif kind == "UUID":
                    UUID(value)
                else:
                    datetime.fromisoformat(value)
            except ValueError:
                return False
        if any(t in kind for t in ("CHAR", "TEXT")):
            if not isinstance(value, str):
                return False
            length = re.search(r"\((\d+)\)", kind)
            if length and len(value) > int(length[1]):
                return False
    try:
        return all(evaluate(check, row) is not False for check in checks)
    except (TypeError, ArithmeticError) as exc:
        raise PlanError(f"CHECK types are incompatible in {table.name}: {exc}") from exc


def validate_dataset(genome: Genome, data: Dataset) -> None:
    """Independently check rows, candidate keys, and composite FK membership."""
    for table in ordered_tables(genome, set(data)):
        checks = [parse_check(check) for check in table.checks]
        keys = [key for key in [table.primary_key, *table.unique] if key]
        seen: list[set[tuple[Scalar, ...]]] = [set() for _ in keys]
        for row in data[table.name]:
            if set(row) != {c.name for c in table.columns} or not _valid_row(table, row, checks):
                raise GenerationError(f"Invalid row in {table.name}")
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
        allowed_types = {
            "SMALLINT",
            "BIGINT",
            "INTEGER",
            "INT",
            "SERIAL",
            "BIGSERIAL",
            "SMALLSERIAL",
            "NUMERIC",
            "DECIMAL",
            "REAL",
            "FLOAT",
            "DOUBLE PRECISION",
            "BOOLEAN",
            "BOOL",
            "DATE",
            "DATETIME",
            "TIMESTAMP",
            "UUID",
            "VARCHAR",
            "CHAR",
            "CHARACTER",
            "CHARACTER VARYING",
            "TEXT",
            "TIMESTAMP WITH TIME ZONE",
            "TIMESTAMP WITHOUT TIME ZONE",
            "TIMESTAMPTZ",
        }
        for column in table.columns:
            base = re.sub(r"\([^)]*\)", "", column.sql_type.upper()).strip()
            if base not in allowed_types:
                raise PlanError(
                    f"Unsupported SQL type: {column.sql_type} on {table.name}.{column.name}"
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
            for _attempt in range(500):
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
                            column, rule, index, ctx, registry, name in table.primary_key
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
                if _valid_row(table, row, checks) and all(
                    None in value or value not in pool
                    for value, pool in zip(tuples, seen, strict=True)
                ):
                    for value, seen_pool in zip(tuples, seen, strict=True):
                        seen_pool.add(value)
                    rows.append(row)
                    break
            else:
                raise GenerationError(
                    f"Cannot satisfy constraints for {table.name} row {index + 1} "
                    "after 500 attempts. "
                    "Narrow choices/bounds or reduce row count; no output was written."
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
