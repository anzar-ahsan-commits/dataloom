"""Portable schema contracts, independent of database and domain providers."""

from __future__ import annotations

import hashlib
import json
import tempfile
from typing import TYPE_CHECKING, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from dataloom.errors import GenomeError

if TYPE_CHECKING:
    from pathlib import Path

Scalar = str | int | float | bool | None


class Model(BaseModel):
    """Strict artifact base: misspelled fields are errors, never ignored."""

    model_config = ConfigDict(extra="forbid")


class Profile(Model):
    """Statistics over a bounded, explicitly identified sample."""

    sampled_rows: int = Field(ge=0)
    cardinality: int = Field(ge=0)
    null_rate: float = Field(ge=0, le=1)
    minimum: Scalar = None
    maximum: Scalar = None
    top_values: list[tuple[Scalar, int]] = Field(default_factory=list)
    pattern: str | None = None
    quantiles: list[float] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_quantiles(self) -> Self:
        """Require ordered finite quantiles with enough points to interpolate."""
        import math

        if self.quantiles and (
            len(self.quantiles) < 2
            or any(not math.isfinite(v) for v in self.quantiles)
            or self.quantiles != sorted(self.quantiles)
        ):
            raise ValueError("Quantiles must contain at least two ordered finite numbers")
        return self


class Classification(Model):
    """Semantic label with evidence and cache provenance."""

    semantic_type: str
    source: Literal["name", "pattern", "llm", "manual"]
    evidence: str
    classifier_version: str = "1"


class Column(Model):
    """A column's SQL definition and optional observed semantics."""

    name: str
    sql_type: str
    nullable: bool = True
    default: str | None = None
    generated: bool = False
    profile: Profile | None = None
    classification: Classification | None = None
    classification_cache_key: str | None = None


class ForeignKey(Model):
    """Ordered column tuples preserve composite foreign-key semantics."""

    columns: list[str] = Field(min_length=1)
    parent_table: str
    parent_columns: list[str] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_arity(self) -> Self:
        """Reject relationships whose tuple widths differ."""
        if len(self.columns) != len(self.parent_columns):
            raise ValueError("Foreign-key column counts differ")
        return self


class Table(Model):
    """A domain-neutral relational entity."""

    name: str
    columns: list[Column] = Field(min_length=1)
    primary_key: list[str] = Field(default_factory=list)
    foreign_keys: list[ForeignKey] = Field(default_factory=list)
    unique: list[list[str]] = Field(default_factory=list)
    checks: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_columns(self) -> Self:
        """Validate local constraint references and normalize PK nullability."""
        names = {c.name for c in self.columns}
        if len(names) != len(self.columns):
            raise ValueError(f"Duplicate columns in {self.name}")
        for key in [self.primary_key, *self.unique, *(fk.columns for fk in self.foreign_keys)]:
            if not set(key) <= names or len(set(key)) != len(key):
                raise ValueError(f"Invalid constraint columns in {self.name}: {key}")
        for column in self.columns:
            if column.name in self.primary_key:
                column.nullable = False
        return self


class Genome(Model):
    """Versioned schema genome; contains no connection strings or credentials."""

    format_version: Literal[1] = 1
    dialect: str = "postgres"
    tables: list[Table] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_relationships(self) -> Self:
        """Require complete and valid referenced candidate keys."""
        tables = {t.name: t for t in self.tables}
        if len(tables) != len(self.tables):
            raise ValueError("Duplicate table names")
        for table in self.tables:
            for fk in table.foreign_keys:
                parent = tables.get(fk.parent_table)
                if parent is None:
                    raise ValueError(f"Missing referenced table: {fk.parent_table}")
                if fk.parent_columns not in [parent.primary_key, *parent.unique]:
                    raise ValueError(f"Referenced columns are not a candidate key: {fk}")
        return self

    def fingerprint(self) -> str:
        """Hash structural metadata, excluding observations and classifications."""
        structure = self.model_dump(
            exclude={
                "tables": {
                    "__all__": {
                        "columns": {
                            "__all__": {"profile", "classification", "classification_cache_key"}
                        }
                    }
                }
            }
        )
        return hashlib.sha256(json.dumps(structure, sort_keys=True).encode()).hexdigest()

    def save(self, path: Path) -> None:
        """Atomically persist a readable JSON artifact."""
        path.parent.mkdir(parents=True, exist_ok=True)
        from pathlib import Path

        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=path.parent, suffix=".tmp", delete=False
        ) as stream:
            temporary = Path(stream.name)
            stream.write(self.model_dump_json(indent=2) + "\n")
        try:
            temporary.replace(path)
        finally:
            temporary.unlink(missing_ok=True)

    @classmethod
    def load(cls, path: Path) -> Genome:
        """Read an artifact, rejecting corrupt or unsupported versions."""
        try:
            return cls.model_validate_json(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise GenomeError(f"Cannot load genome {path}: {exc}") from exc
