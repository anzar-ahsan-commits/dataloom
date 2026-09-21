"""Single source of truth for the supported SQL type families."""

from __future__ import annotations

import re
from functools import lru_cache
from typing import Literal, NamedTuple

Family = Literal["integer", "decimal", "boolean", "date", "timestamp", "uuid", "text"]

_INTEGER = {"SMALLINT", "INT", "INTEGER", "BIGINT", "SMALLSERIAL", "SERIAL", "BIGSERIAL"}
_DECIMAL = {"NUMERIC", "DECIMAL", "REAL", "FLOAT", "DOUBLE", "DOUBLE PRECISION"}
_BOOLEAN = {"BOOL", "BOOLEAN"}
_TEXT = {"CHAR", "CHARACTER", "VARCHAR", "CHARACTER VARYING", "TEXT"}
_TIMESTAMP = {
    "DATETIME",
    "TIMESTAMP",
    "TIMESTAMPTZ",
    "TIMESTAMP WITH TIME ZONE",
    "TIMESTAMP WITHOUT TIME ZONE",
}
_ZONED = {"TIMESTAMPTZ", "TIMESTAMP WITH TIME ZONE"}


class ColumnType(NamedTuple):
    """A parsed declaration; `family` is None for every unsupported type."""

    family: Family | None
    bits: int = 32
    length: int | None = None
    digits: int | None = None
    scale: int | None = None
    zoned: bool = False

    @property
    def numeric(self) -> bool:
        """Report whether arithmetic and ordered comparison apply."""
        return self.family in ("integer", "decimal")

    @property
    def temporal(self) -> bool:
        """Report whether values are ISO date or timestamp strings."""
        return self.family in ("date", "timestamp")

    @property
    def places(self) -> int:
        """Get the rounding scale to use when a declaration omits precision."""
        return self.scale if self.scale is not None else 2


@lru_cache(maxsize=1024)
def column_type(sql_type: str) -> ColumnType:
    """Classify a declaration by exact family name, never by substring."""
    kind = " ".join(sql_type.upper().split())
    base = " ".join(re.sub(r"\([^)]*\)", "", kind).split())
    if base in _INTEGER:
        return ColumnType("integer", 16 if "SMALL" in base else 64 if "BIG" in base else 32)
    if base in _DECIMAL:
        precision = re.search(r"\((\d+)\s*,\s*(\d+)\)", kind)
        return ColumnType(
            "decimal",
            digits=int(precision[1]) if precision else None,
            scale=int(precision[2]) if precision else None,
        )
    if base in _BOOLEAN:
        return ColumnType("boolean")
    if base == "DATE":
        return ColumnType("date")
    if base in _TIMESTAMP:
        return ColumnType("timestamp", zoned=base in _ZONED)
    if base == "UUID":
        return ColumnType("uuid")
    if base in _TEXT:
        size = re.search(r"\((\d+)\)", kind)
        return ColumnType("text", length=int(size[1]) if size else None)
    return ColumnType(None)
