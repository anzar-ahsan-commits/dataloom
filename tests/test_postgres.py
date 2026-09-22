"""Real PostgreSQL reflection and insertion; CI provisions an isolated service."""

import os
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, text

from dataloom.autoplan import synthesize
from dataloom.connectors import DatabaseConnector
from dataloom.constraints import evaluate, parse_check
from dataloom.engine import generate
from dataloom.introspection import reflect
from dataloom.plan import EntityPlan, Plan
from dataloom.sqltypes import column_type


@pytest.mark.integration
def test_postgres_reflection_and_transaction() -> None:
    url = os.environ.get("DATALOOM_TEST_POSTGRES")
    if not url:
        pytest.skip("Set DATALOOM_TEST_POSTGRES to an isolated PostgreSQL database")
    engine = create_engine(url)
    schema = "dataloom_test_" + uuid4().hex
    try:
        with engine.begin() as connection:
            connection.exec_driver_sql(f'CREATE SCHEMA "{schema}"')
            connection.exec_driver_sql(
                f'CREATE TABLE "{schema}".parents (region INT, id INT, PRIMARY KEY(region,id))'
            )
            connection.exec_driver_sql(
                f'CREATE TABLE "{schema}".children '
                "(id INT PRIMARY KEY, region INT NOT NULL, parent_id INT NOT NULL,"
                f' FOREIGN KEY(region,parent_id) REFERENCES "{schema}".parents(region,id))'
            )
        genome = reflect(engine, schema)
        plan = Plan(
            entities={
                f"{schema}.parents": EntityPlan(rows=4),
                f"{schema}.children": EntityPlan(rows=12),
            }
        )
        data, receipt = generate(genome, plan)
        DatabaseConnector(engine).write(genome, data, receipt)
        with engine.connect() as connection:
            assert (
                connection.exec_driver_sql(f'SELECT count(*) FROM "{schema}".children').scalar()
                == 12
            )
    finally:
        with engine.begin() as connection:
            connection.exec_driver_sql(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')
        engine.dispose()


WIDE = """
CREATE TABLE {s}.customers (
  id INT PRIMARY KEY,
  full_name VARCHAR(80) NOT NULL,
  email VARCHAR(120) UNIQUE,
  balance NUMERIC(10,2) CHECK (balance >= 0),
  ratio DOUBLE PRECISION,
  active BOOLEAN NOT NULL,
  ref UUID,
  signed_up DATE,
  created_at TIMESTAMP,
  seen_at TIMESTAMP WITH TIME ZONE,
  tier SMALLINT CHECK (tier IN (1, 2, 3))
);
CREATE TABLE {s}.orders (
  id BIGSERIAL PRIMARY KEY,
  customer_id INT NOT NULL,
  amount NUMERIC(8,2),
  FOREIGN KEY (customer_id) REFERENCES {s}.customers(id)
);
"""


@pytest.mark.integration
def test_every_supported_type_and_normalized_check_round_trips() -> None:
    """PostgreSQL rewrites simple checks, so reflected text must still generate."""
    url = os.environ.get("DATALOOM_TEST_POSTGRES")
    if not url:
        pytest.skip("Set DATALOOM_TEST_POSTGRES to an isolated PostgreSQL database")
    engine = create_engine(url)
    schema = "dataloom_test_" + uuid4().hex
    try:
        with engine.begin() as connection:
            connection.exec_driver_sql(f'CREATE SCHEMA "{schema}"')
            for statement in WIDE.format(s=f'"{schema}"').split(";"):
                if statement.strip():
                    connection.exec_driver_sql(statement)
        genome = reflect(engine, schema)
        customers = next(t for t in genome.tables if t.name.endswith(".customers"))
        assert all(column_type(c.sql_type).family for c in customers.columns)

        plan = synthesize(genome, rows=12)
        rules = plan.entities[f"{schema}.customers"].rules
        assert rules["tier"].choices == [1, 2, 3]
        assert rules["balance"].minimum == 0.0

        data, receipt = generate(genome, plan)
        DatabaseConnector(engine).write(genome, data, receipt)
        with engine.connect() as connection:
            assert (
                connection.exec_driver_sql(
                    f'SELECT count(*) FROM "{schema}".customers'
                    " WHERE balance >= 0 AND tier IN (1,2,3)"
                ).scalar()
                == 12
            )
            assert (
                connection.exec_driver_sql(
                    f'SELECT count(DISTINCT email) FROM "{schema}".customers'
                ).scalar()
                == 12
            )
    finally:
        with engine.begin() as connection:
            connection.exec_driver_sql(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')
        engine.dispose()


@pytest.mark.integration
@pytest.mark.parametrize(
    ("expression", "value"),
    [
        ("x = 'false'::boolean", True),
        ("x = 'off'::boolean", False),
        ("x = 1.8::integer", 2),
        ("x = (-1.5)::integer", -2),
        ("x = 9007199254740993::bigint", 9007199254740993),
        ("x = true::text", "true"),
    ],
)
def test_supported_cast_results_match_postgres(expression: str, value: object) -> None:
    """Compare CHECK evaluation with PostgreSQL, not another implementation copy."""
    url = os.environ.get("DATALOOM_TEST_POSTGRES")
    if not url:
        pytest.skip("Set DATALOOM_TEST_POSTGRES to an isolated PostgreSQL database")
    engine = create_engine(url)
    try:
        with engine.connect() as connection:
            actual = connection.execute(
                text(f"SELECT {expression} FROM (SELECT :value AS x) AS input"),
                {"value": value},
            ).scalar_one()
        assert evaluate(parse_check(expression), {"x": value}) is actual
    finally:
        engine.dispose()
