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
)


def parse_check(sql: str) -> exp.Expression:
    """Preflight supported syntax so unknown constraints never silently pass."""
    tree = sqlglot.parse_one(sql, read="postgres")
    for node in tree.walk():
        if type(node) not in _BINARY and not isinstance(node, _SUPPORTED):
            raise PlanError(f"Unsupported CHECK expression: {sql} ({type(node).__name__})")
    return tree


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
    if isinstance(node, (exp.Neg, exp.Not)):
        value = evaluate(node.this, row)
        return None if value is None else -value if isinstance(node, exp.Neg) else not value
    left = evaluate(node.this, row)
    if isinstance(node, exp.Between):
        low, high = evaluate(node.args["low"], row), evaluate(node.args["high"], row)
        return None if None in (left, low, high) else low <= left <= high
    if isinstance(node, exp.In):
        values = [evaluate(v, row) for v in node.expressions]
        return (
            True
            if left is not None and left in values
            else (None if left is None or None in values else False)
        )
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
