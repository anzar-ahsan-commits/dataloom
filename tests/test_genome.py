"""Schema ingestion, profiling and classification contracts."""

from pathlib import Path

import pytest
from sqlalchemy import create_engine

from dataloom.classification import classify
from dataloom.errors import GenomeError, SchemaIntrospectionError
from dataloom.genome import Genome
from dataloom.introspection import parse_ddl, reflect
from dataloom.profiling import mine_pattern, profile

DDL = """
CREATE TABLE accounts (region INTEGER, id INTEGER, email VARCHAR(100) UNIQUE,
  PRIMARY KEY(region,id));
CREATE TABLE orders (id INTEGER PRIMARY KEY, region INTEGER NOT NULL,
  account_id INTEGER NOT NULL, amount NUMERIC DEFAULT 0 CHECK(amount >= 0),
  FOREIGN KEY(region,account_id) REFERENCES accounts(region,id));
"""


def test_ddl_constraints_and_artifact(tmp_path: Path) -> None:
    genome = parse_ddl(DDL)
    assert genome.tables[1].foreign_keys[0].columns == ["region", "account_id"]
    assert genome.tables[1].checks == ["amount >= 0"]
    assert genome.tables[0].unique == [["email"]]
    path = tmp_path / "genome.json"
    genome.save(path)
    assert Genome.load(path) == genome
    assert classify(genome).fingerprint() == genome.fingerprint()
    path.write_text('{"format_version": 99}', encoding="utf-8")
    with pytest.raises(GenomeError):
        Genome.load(path)


def test_reflection_and_profile() -> None:
    engine = create_engine("sqlite://")
    with engine.begin() as connection:
        for statement in DDL.split(";"):
            if statement.strip():
                connection.exec_driver_sql(statement)
        connection.exec_driver_sql("INSERT INTO accounts VALUES (1,1,'fiction@example.test')")
        connection.exec_driver_sql("INSERT INTO accounts VALUES (1,2,NULL)")
    genome = reflect(engine)
    assert genome.tables[1].foreign_keys == parse_ddl(DDL).tables[1].foreign_keys
    observed = profile(genome, engine)
    stats = observed.tables[0].columns[2].profile
    assert stats is not None and stats.null_rate == 0.5 and stats.cardinality == 1
    assert classify(observed).tables[0].columns[2].classification.semantic_type == "email"
    assert mine_pattern(["123-45-6789", "987-65-4321"]) == r"^\d{3}\-\d{2}\-\d{4}$"
    engine.dispose()


@pytest.mark.parametrize("sql", ["DROP TABLE secret", "CREATE TABLE x AS SELECT 1", ""])
def test_unsupported_ddl_fails(sql: str) -> None:
    with pytest.raises(SchemaIntrospectionError):
        parse_ddl(sql)
