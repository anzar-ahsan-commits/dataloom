"""Bounded local profiling: observed sample statistics, never population claims."""

from __future__ import annotations

import math
import re
from collections import Counter
from datetime import date, datetime
from decimal import Decimal
from itertools import groupby
from typing import TYPE_CHECKING

from sqlalchemy import MetaData, Table, select

from dataloom.genome import Genome, Profile, Scalar
from dataloom.sqltypes import column_type

if TYPE_CHECKING:
    from sqlalchemy import Engine


def scalar(value: object) -> Scalar:
    """Normalize database scalar values to JSON-safe values."""
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    return str(value)


def mine_pattern(values: list[str]) -> str | None:
    """Identify a shared character shape, requiring at least two observations."""
    if len(values) < 2:
        return None

    def shape(value: str) -> str:
        tokens = [
            r"\d"
            if c.isascii() and c.isdigit()
            else "[A-Z]"
            if "A" <= c <= "Z"
            else "[a-z]"
            if "a" <= c <= "z"
            else re.escape(c)
            for c in value
        ]
        parts = []
        for token, group in groupby(tokens):
            size = len(list(group))
            parts.append(token + (f"{{{size}}}" if size > 1 else ""))
        return "^" + "".join(parts) + "$"

    patterns = {shape(v) for v in values}
    return next(iter(patterns)) if len(patterns) == 1 else None


def profile(genome: Genome, engine: Engine, limit: int = 1000, top_n: int = 5) -> Genome:
    """Profile up to limit rows per table; PK ordering makes samples stable."""
    if limit < 1 or top_n < 1:
        raise ValueError("Profiling limits must be positive")
    result = genome.model_copy(deep=True)
    with engine.connect() as connection:
        for entity in result.tables:
            schema, _, name = entity.name.rpartition(".")
            table = Table(name, MetaData(), schema=schema or None, autoload_with=engine)
            query = select(table).limit(limit)
            if entity.primary_key:
                query = query.order_by(*(table.c[c] for c in entity.primary_key))
            rows = connection.execute(query).mappings().all()
            for column in entity.columns:
                values = [scalar(row[column.name]) for row in rows if row[column.name] is not None]
                counts = Counter(values)
                numeric = sorted(
                    float(v)
                    for v in values
                    if isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)
                )
                kind = column_type(column.sql_type)
                numeric_date = kind.numeric or kind.temporal
                ordered = sorted(values, key=lambda v: v if isinstance(v, (int, float)) else str(v))
                column.profile = Profile(
                    sampled_rows=len(rows),
                    cardinality=len(counts),
                    null_rate=1 - len(values) / len(rows) if rows else 0,
                    minimum=ordered[0] if numeric_date and ordered else None,
                    maximum=ordered[-1] if numeric_date and ordered else None,
                    top_values=counts.most_common(top_n),
                    pattern=mine_pattern([str(v) for v in values]) if values else None,
                    quantiles=[numeric[round(i * (len(numeric) - 1) / 10)] for i in range(11)]
                    if numeric
                    else [],
                )
    return result
