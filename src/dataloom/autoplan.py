"""Derive a reviewable default plan from a genome, offline and without a provider."""

from __future__ import annotations

import math
from typing import TYPE_CHECKING

from sqlglot import exp

from dataloom.constraints import evaluate, parse_check
from dataloom.engine import ordered_tables
from dataloom.errors import PlanError
from dataloom.plan import EntityPlan, Fanout, Plan, Rule
from dataloom.sqltypes import column_type

if TYPE_CHECKING:
    from collections.abc import Iterator

    from dataloom.genome import ForeignKey, Genome, Scalar, Table


def _identifying(table: Table) -> ForeignKey | None:
    """Prefer the relationship that forms part of the child's own identity."""
    candidates = [fk for fk in table.foreign_keys if fk.parent_table != table.name]
    if not candidates:
        return None
    primary = set(table.primary_key)
    return next((fk for fk in candidates if set(fk.columns) <= primary), candidates[0])


def _conjuncts(node: exp.Expression) -> Iterator[exp.Expression]:
    """Split a CHECK into the terms that must each hold independently."""
    if isinstance(node, exp.Paren):
        yield from _conjuncts(node.this)
    elif isinstance(node, exp.And):
        yield from _conjuncts(node.this)
        yield from _conjuncts(node.expression)
    else:
        yield node


def _literal(node: exp.Expression) -> Scalar:
    """Read a literal, seeing through the parentheses and casts PostgreSQL adds."""
    if isinstance(node, exp.Paren):
        return _literal(node.this)
    if isinstance(node, exp.Neg):
        value = _literal(node.this)
        return -value if isinstance(value, (int, float)) and not isinstance(value, bool) else None
    if isinstance(node, exp.Cast):
        if any(isinstance(child, exp.Column) for child in node.walk()):
            return None
        value = evaluate(node, {})
        return value if isinstance(value, (str, int, float, bool)) else None
    if isinstance(node, (exp.Boolean, exp.Literal)):
        value = evaluate(node, {})
        return value if isinstance(value, (str, int, float, bool)) else None
    return None


def _column_name(node: exp.Expression) -> str | None:
    while isinstance(node, exp.Paren):
        node = node.this
    return node.name if isinstance(node, exp.Column) else None


def _coerce(value: Scalar, sql_type: str) -> Scalar:
    kind = column_type(sql_type)
    if kind.family == "integer" and isinstance(value, float) and value.is_integer():
        return int(value)
    return value


def _rules_from_checks(table: Table, eligible: set[str]) -> dict[str, Rule]:
    """Read enumerations and numeric bounds straight out of supported CHECK terms.

    Only unambiguous single-column terms are used. Anything else is left alone,
    so a rule is never invented from a constraint that was not understood.
    """
    choices: dict[str, list[Scalar]] = {}
    bounds: dict[str, dict[str, float]] = {}
    for check in table.checks:
        try:
            parsed = parse_check(check)
        except PlanError:
            continue
        for term in _conjuncts(parsed):
            name = _column_name(term.this) if isinstance(term, exp.Expression) else None
            if name is None or name not in eligible:
                continue
            values = None
            if isinstance(term, exp.In):
                values = [_literal(v) for v in term.expressions]
            elif isinstance(term, exp.EQ) and isinstance(term.expression, exp.Any):
                inner = term.expression.this
                while isinstance(inner, exp.Paren):
                    inner = inner.this
                if isinstance(inner, exp.Array):
                    values = [_literal(v) for v in inner.expressions]
            if values is not None:
                if values and all(v is not None for v in values):
                    choices[name] = [_coerce(v, _sql_type(table, name)) for v in values]
                continue
            if isinstance(term, exp.Between):
                low, high = _literal(term.args["low"]), _literal(term.args["high"])
                if isinstance(low, (int, float)) and isinstance(high, (int, float)):
                    limits = bounds.setdefault(name, {})
                    limits["minimum"] = max(limits.get("minimum", float(low)), float(low))
                    limits["maximum"] = min(limits.get("maximum", float(high)), float(high))
                continue
            edge = _literal(term.expression) if isinstance(term, tuple(_COMPARISONS)) else None
            if not isinstance(edge, (int, float)) or isinstance(edge, bool):
                continue
            integral = column_type(_sql_type(table, name)).family == "integer"
            strict = isinstance(term, (exp.GT, exp.LT))
            if strict and not integral:
                continue
            limits = bounds.setdefault(name, {})
            if isinstance(term, (exp.GT, exp.GTE)):
                lower_edge = math.floor(edge) + 1 if strict else float(edge)
                limits["minimum"] = max(limits.get("minimum", -math.inf), lower_edge)
            else:
                upper_edge = math.ceil(edge) - 1 if strict else float(edge)
                limits["maximum"] = min(limits.get("maximum", math.inf), upper_edge)
    rules = {name: Rule(choices=values) for name, values in choices.items()}
    for name, limits in bounds.items():
        if name in rules:
            continue
        lower = limits.get("minimum")
        upper = limits.get("maximum")
        if lower is None:
            lower = min(0.0, upper - 1000.0) if upper is not None else 0.0
        if upper is None:
            upper = max(1000.0, lower + 1000.0)
        kind = column_type(_sql_type(table, name))
        if kind.family == "integer":
            lower = max(math.ceil(lower), -(2 ** (kind.bits - 1)))
            upper = min(math.floor(upper), 2 ** (kind.bits - 1) - 1)
        if lower > upper:
            raise PlanError(f"No supported values satisfy CHECK bounds for {table.name}.{name}")
        rules[name] = Rule(minimum=lower, maximum=upper)
    return rules


_COMPARISONS = (exp.GT, exp.GTE, exp.LT, exp.LTE)


def _sql_type(table: Table, name: str) -> str:
    return next(c.sql_type for c in table.columns if c.name == name)


def synthesize(genome: Genome, rows: int = 50, minimum: int = 1, maximum: int = 3) -> Plan:
    """Plan every entity: root tables take a fixed count, children fan out from a parent.

    Columns constrained by a supported single-column CHECK receive a matching
    `choices` or bounds rule, so reflected enumerations and ranges generate
    directly instead of relying on rejection sampling.

    Args:
        genome: The schema to cover. Every table is included so that no plan is
            missing a required parent.
        rows: Row count for each table that has no outgoing foreign key.
        minimum: Fewest children generated per parent row.
        maximum: Most children generated per parent row.

    Returns:
        A plan that passes the same validation as a hand-authored one.

    Raises:
        PlanError: If the schema uses types, computed columns, or relationship
            shapes that Phase 1 generation does not support.
    """
    unsupported = [
        f"{table.name}.{column.name} ({column.sql_type})"
        for table in genome.tables
        for column in table.columns
        if column_type(column.sql_type).family is None
    ]
    if unsupported:
        raise PlanError(
            "These columns have types outside the supported set, so no default plan can "
            f"cover them: {', '.join(unsupported)}. Narrow the imported schema, or write a "
            "plan for the entities that are supported."
        )
    computed = [t.name for t in genome.tables if any(c.generated for c in t.columns)]
    if computed:
        raise PlanError(f"Computed columns are unsupported in v1, so cannot plan: {computed}")
    reflexive = [
        t.name for t in genome.tables if any(fk.parent_table == t.name for fk in t.foreign_keys)
    ]
    if reflexive:
        raise PlanError(
            f"Self-referencing foreign keys are unsupported in v1, so cannot plan: {reflexive}"
        )
    entities = {}
    for table in genome.tables:
        keyed = {name for key in [table.primary_key, *table.unique] for name in key}
        keyed.update(column for fk in table.foreign_keys for column in fk.columns)
        rules = _rules_from_checks(table, {c.name for c in table.columns} - keyed)
        parent = _identifying(table)
        entities[table.name] = (
            EntityPlan(
                fanout=Fanout(
                    parent=parent.parent_table,
                    foreign_key=parent.columns,
                    minimum=minimum,
                    maximum=maximum,
                ),
                rules=rules,
            )
            if parent
            else EntityPlan(rows=rows, rules=rules)
        )
    ordered_tables(genome, set(entities))
    return Plan(entities=entities)
