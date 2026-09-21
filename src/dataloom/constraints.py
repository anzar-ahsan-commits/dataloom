"""Small, explicit SQL CHECK evaluator with SQL NULL semantics."""

from __future__ import annotations

import operator
from typing import TYPE_CHECKING, Any

import sqlglot
from sqlglot import exp

from dataloom.errors import PlanError

if TYPE_CHECKING:
    from collections.abc import Callable

    from dataloom.genome import Scalar

_BINARY: dict[type[exp.Expression], Callable[[Any, Any], Any]] = {
    exp.EQ: operator.eq,
    exp.NEQ: operator.ne,
    exp.GT: operator.gt,
    exp.GTE: operator.ge,
    exp.LT: operator.lt,
    exp.LTE: operator.le,
    exp.Add: operator.add,
    exp.Sub: operator.sub,
    exp.Mul: operator.mul,
}
_SUPPORTED = (
    exp.Column,
    exp.Identifier,
    exp.Literal,
    exp.Null,
    exp.Boolean,
    exp.Paren,
    exp.Neg,
    exp.Not,
    exp.And,
    exp.Or,
    exp.Is,
    exp.In,
    exp.Between,
    # PostgreSQL stores `x >= 0` as `x >= 0::numeric` and `x IN (1,2)` as
    # `x = ANY (ARRAY[1,2])`. Reflected checks arrive in those normalized forms.
    exp.Cast,
    exp.DataType,
    exp.Any,
    exp.Array,
)
_CASTABLE = exp.DataType.NUMERIC_TYPES | exp.DataType.TEXT_TYPES | {exp.DataType.Type.BOOLEAN}


def _cast_target(node: exp.Cast) -> exp.DataType.Type:
    target = node.args.get("to")
    if not isinstance(target, exp.DataType):
        raise PlanError(f"Unsupported CHECK cast: {node.sql(dialect='postgres')}")
    kind: exp.DataType.Type = target.this
    return kind


def _any_values(node: exp.Any) -> list[exp.Expression]:
    """Unwrap `ANY (ARRAY[...])` into its literal elements."""
    inner = node.this
    while isinstance(inner, exp.Paren):
        inner = inner.this
    if not isinstance(inner, exp.Array):
        raise PlanError("Only ANY over an explicit ARRAY literal is supported")
    return list(inner.expressions)


def parse_check(sql: str) -> exp.Expression:
    """Preflight supported syntax so unknown constraints never silently pass."""
    tree = sqlglot.parse_one(sql, read="postgres")
    for node in tree.walk():
        if type(node) not in _BINARY and not isinstance(node, _SUPPORTED):
            raise PlanError(f"Unsupported CHECK expression: {sql} ({type(node).__name__})")
        if isinstance(node, exp.Cast) and _cast_target(node) not in _CASTABLE:
            raise PlanError(f"Unsupported CHECK cast target: {sql} ({_cast_target(node).name})")
        if isinstance(node, exp.Any):
            _any_values(node)
            if not isinstance(node.parent, exp.EQ):
                raise PlanError(f"Only equality against ANY is supported: {sql}")
    return tree


def _membership(left: Scalar, values: list[Scalar]) -> bool | None:
    """Apply three-valued IN semantics shared by IN and `= ANY (ARRAY[...])`."""
    if left is not None and left in values:
        return True
    return None if left is None or None in values else False


def evaluate(node: exp.Expression, row: dict[str, Scalar]) -> Any:
    """Evaluate a supported CHECK expression using three-valued SQL logic."""
    if isinstance(node, exp.Column):
        return row[node.name]
    if isinstance(node, exp.Null):
        return None
    if isinstance(node, exp.Boolean):
        return bool(node.this)
    if isinstance(node, exp.Literal):
        return node.this if node.is_string else float(node.this)
    if isinstance(node, exp.Paren):
        return evaluate(node.this, row)
    if isinstance(node, exp.Cast):
        value = evaluate(node.this, row)
        if value is None:
            return None
        kind = _cast_target(node)
        if kind in exp.DataType.NUMERIC_TYPES:
            return bool(value) if isinstance(value, bool) else float(value)
        return str(value) if kind in exp.DataType.TEXT_TYPES else bool(value)
    if isinstance(node, (exp.Neg, exp.Not)):
        value = evaluate(node.this, row)
        return None if value is None else -value if isinstance(node, exp.Neg) else not value
    left = evaluate(node.this, row)
    if isinstance(node, exp.Between):
        low, high = evaluate(node.args["low"], row), evaluate(node.args["high"], row)
        return None if None in (left, low, high) else low <= left <= high
    if isinstance(node, exp.In):
        return _membership(left, [evaluate(v, row) for v in node.expressions])
    if isinstance(node, exp.EQ) and isinstance(node.expression, exp.Any):
        return _membership(left, [evaluate(v, row) for v in _any_values(node.expression)])
    right = evaluate(node.expression, row)
    if isinstance(node, exp.Is):
        return left is right
    if isinstance(node, exp.And):
        return (
            False
            if left is False or right is False
            else (None if left is None or right is None else bool(left and right))
        )
    if isinstance(node, exp.Or):
        return (
            True
            if left is True or right is True
            else (None if left is None or right is None else bool(left or right))
        )
    if left is None or right is None:
        return None
    return _BINARY[type(node)](left, right)
