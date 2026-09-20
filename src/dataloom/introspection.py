"""SQLAlchemy reflection and non-executing PostgreSQL DDL import."""

from __future__ import annotations

from typing import TYPE_CHECKING

import sqlglot
from sqlalchemy import inspect
from sqlglot import exp

from dataloom.errors import SchemaIntrospectionError
from dataloom.genome import Column, ForeignKey, Genome, Table

if TYPE_CHECKING:
    from sqlalchemy import Engine


def reflect(engine: Engine, schema: str | None = None) -> Genome:
    """Reflect tables and constraints without reading application rows."""
    inspector = inspect(engine)
    tables = []
    for name in sorted(inspector.get_table_names(schema=schema)):
        qualified = f"{schema}.{name}" if schema else name
        foreign_keys = []
        for fk in inspector.get_foreign_keys(name, schema=schema):
            parent_schema = fk.get("referred_schema")
            if parent_schema == inspector.default_schema_name and schema is None:
                parent_schema = None
            parent = fk["referred_table"]
            foreign_keys.append(
                ForeignKey(
                    columns=fk["constrained_columns"],
                    parent_table=f"{parent_schema}.{parent}" if parent_schema else parent,
                    parent_columns=fk["referred_columns"],
                )
            )
        unique = [u["column_names"] for u in inspector.get_unique_constraints(name, schema=schema)]
        for index in inspector.get_indexes(name, schema=schema):
            if index["unique"] and not index.get("duplicates_constraint"):
                if any(c is None for c in index["column_names"]) or index.get("dialect_options"):
                    raise SchemaIntrospectionError("Expression/partial unique indexes unsupported")
                key = [str(c) for c in index["column_names"]]
                if key not in unique:
                    unique.append(key)
        tables.append(
            Table(
                name=qualified,
                columns=[
                    Column(
                        name=c["name"],
                        sql_type=str(c["type"]),
                        nullable=c["nullable"],
                        default=c.get("default"),
                        generated=bool(c.get("computed")),
                    )
                    for c in inspector.get_columns(name, schema=schema)
                ],
                primary_key=inspector.get_pk_constraint(name, schema=schema)["constrained_columns"],
                foreign_keys=foreign_keys,
                unique=unique,
                checks=[c["sqltext"] for c in inspector.get_check_constraints(name, schema=schema)],
            )
        )
    return Genome(dialect=engine.dialect.name, tables=tables)


def _reference(node: exp.Reference, columns: list[str]) -> ForeignKey:
    target = node.this
    if not isinstance(target, exp.Schema):
        raise SchemaIntrospectionError("REFERENCES must explicitly name parent columns")
    return ForeignKey(
        columns=columns,
        parent_table=_table_name(target.this),
        parent_columns=[c.name for c in target.expressions],
    )


def _table_name(node: exp.Expression) -> str:
    if not isinstance(node, exp.Table) or node.catalog:
        raise SchemaIntrospectionError("Expected a table, optionally schema-qualified")
    return f"{node.db}.{node.name}" if node.db else node.name


def _constraint(
    node: exp.Expression,
    primary: list[str],
    unique: list[list[str]],
    checks: list[str],
    foreign: list[ForeignKey],
    field: str | None = None,
) -> None:
    if isinstance(node, exp.Constraint):
        for child in node.expressions:
            _constraint(child, primary, unique, checks, foreign)
    elif isinstance(node, exp.PrimaryKey):
        primary.extend(c.name for c in node.expressions)
    elif isinstance(node, exp.PrimaryKeyColumnConstraint) and field:
        primary.append(field)
    elif isinstance(node, exp.UniqueColumnConstraint):
        unique.append([field] if field else [c.name for c in node.this.expressions])
    elif isinstance(node, exp.CheckColumnConstraint):
        checks.append(node.this.sql(dialect="postgres"))
    elif isinstance(node, exp.ForeignKey):
        foreign.append(_reference(node.args["reference"], [c.name for c in node.expressions]))
    elif isinstance(node, exp.Reference) and field:
        foreign.append(_reference(node, [field]))
    else:
        raise SchemaIntrospectionError(f"Unsupported constraint: {node.sql()}")


def parse_ddl(sql: str) -> Genome:
    """Parse CREATE TABLE DDL without executing user SQL.

    Supports scalar columns, defaults, PK/FK/UNIQUE/CHECK constraints.
    Other statements and column constraints fail rather than disappear.
    """
    tables = []
    try:
        statements = sqlglot.parse(sql, read="postgres")
        for statement in statements:
            if statement is None:
                continue
            if not isinstance(statement, exp.Create) or statement.args.get("kind") != "TABLE":
                raise SchemaIntrospectionError("Only CREATE TABLE statements are supported")
            if statement.args.get("properties") or statement.args.get("expression"):
                raise SchemaIntrospectionError("CREATE TABLE properties/AS SELECT unsupported")
            definition = statement.this
            if not isinstance(definition, exp.Schema):
                raise SchemaIntrospectionError("CREATE TABLE requires explicit columns")
            columns: list[Column] = []
            primary: list[str] = []
            unique: list[list[str]] = []
            checks: list[str] = []
            foreign: list[ForeignKey] = []

            for node in definition.expressions:
                if isinstance(node, exp.ColumnDef):
                    column = Column(name=node.name, sql_type=node.args["kind"].sql("postgres"))
                    for wrapper in node.args.get("constraints", []):
                        item = wrapper.kind
                        if isinstance(item, exp.NotNullColumnConstraint):
                            column.nullable = False
                        elif isinstance(item, exp.DefaultColumnConstraint):
                            column.default = item.this.sql("postgres")
                        else:
                            _constraint(item, primary, unique, checks, foreign, column.name)
                    columns.append(column)
                else:
                    _constraint(node, primary, unique, checks, foreign)
            tables.append(
                Table(
                    name=_table_name(definition.this),
                    columns=columns,
                    primary_key=primary,
                    unique=unique,
                    checks=checks,
                    foreign_keys=foreign,
                )
            )
        return Genome(tables=tables)
    except (sqlglot.errors.ParseError, ValueError, KeyError) as exc:
        raise SchemaIntrospectionError(f"Invalid or unsupported DDL: {exc}") from exc
