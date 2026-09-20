"""Real PostgreSQL reflection and insertion; CI provisions an isolated service."""

import os
from uuid import uuid4

import pytest
from sqlalchemy import create_engine

from dataloom.connectors import DatabaseConnector
from dataloom.engine import generate
from dataloom.introspection import reflect
from dataloom.plan import EntityPlan, Plan


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
