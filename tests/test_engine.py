"""Relational and deterministic invariants, including adversarial plans."""

import json
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError

from dataloom.connectors import DatabaseConnector, FileConnector
from dataloom.coverage import CoverageStore
from dataloom.engine import generate, ordered_tables, validate_dataset
from dataloom.errors import GenerationError, PlanError
from dataloom.introspection import parse_ddl
from dataloom.plan import EntityPlan, Fanout, Plan, Rule

DDL = """
CREATE TABLE parents (region INTEGER, id INTEGER, PRIMARY KEY(region,id));
CREATE TABLE children (id INTEGER PRIMARY KEY, region INTEGER NOT NULL, parent_id INTEGER NOT NULL,
    abnormal BOOLEAN NOT NULL, amount INTEGER CHECK(amount >= 10 AND amount <= 20),
    FOREIGN KEY(region,parent_id) REFERENCES parents(region,id));
"""


def plan() -> Plan:
    return Plan(
        entities={
            "parents": EntityPlan(rows=10),
            "children": EntityPlan(
                fanout=Fanout(
                    parent="parents", foreign_key=["region", "parent_id"], minimum=3, maximum=5
                ),
                rules={
                    "abnormal": Rule(proportion=0.1, value=True, otherwise=False),
                    "amount": Rule(minimum=10, maximum=20),
                },
            ),
        }
    )


def test_replay_composite_fk_and_exact_quota(tmp_path: Path) -> None:
    genome = parse_ddl(DDL)
    original = plan()
    path = tmp_path / "plan.yaml"
    original.save(path)
    data, receipt = generate(genome, Plan.load(path))
    assert generate(genome, original) == (data, receipt)
    children = data["children"]
    assert sum(r["abnormal"] for r in children) == int(len(children) * 0.1 + 0.5)
    for parent in data["parents"]:
        assert (
            3
            <= sum(
                r["parent_id"] == parent["id"] and r["region"] == parent["region"] for r in children
            )
            <= 5
        )
    assert all(10 <= row["amount"] <= 20 for row in children)
    children[0]["parent_id"] = 999
    with pytest.raises(GenerationError, match="Orphan"):
        validate_dataset(genome, data)


def test_cycles_missing_parents_and_impossible_uniqueness() -> None:
    cyclic = parse_ddl("CREATE TABLE t(id INT PRIMARY KEY, parent INT REFERENCES t(id))")
    with pytest.raises(PlanError, match="Cyclic"):
        ordered_tables(cyclic, {"t"})
    with pytest.raises(PlanError, match="requires parent"):
        generate(parse_ddl(DDL), Plan(entities={"children": EntityPlan(rows=1)}))
    genome = parse_ddl("CREATE TABLE t(id INT PRIMARY KEY, label TEXT UNIQUE)")
    with pytest.raises(GenerationError, match="500 attempts"):
        generate(
            genome,
            Plan(entities={"t": EntityPlan(rows=2, rules={"label": Rule(choices=["same"])})}),
        )


@pytest.mark.parametrize("format", ["json", "csv", "parquet"])
def test_outputs_and_history(tmp_path: Path, format: str) -> None:
    genome = parse_ddl(DDL)
    data, receipt = generate(genome, plan())
    directory = tmp_path / format
    paths = FileConnector(directory, format).write(genome, data, receipt)
    assert len(paths) == 2 and all(Path(p).is_file() for p in paths)
    manifest = json.loads((directory / "manifest.json").read_text())
    assert manifest["receipt"]["data_hash"] == receipt.data_hash
    store = CoverageStore(tmp_path / "coverage.sqlite")
    assert "No recorded runs" in store.suggest(genome)[0]
    store.record(genome, plan(), data, receipt)
    assert any("fanout" in suggestion for suggestion in store.suggest(genome))


def test_database_transaction_rollback() -> None:
    engine = create_engine("sqlite://")
    with engine.begin() as connection:
        connection.exec_driver_sql("PRAGMA foreign_keys=ON")
        for sql in DDL.split(";"):
            if sql.strip():
                connection.exec_driver_sql(sql)
        connection.exec_driver_sql("INSERT INTO parents VALUES (99,99)")
        connection.exec_driver_sql("INSERT INTO children VALUES (1,99,99,0,10)")
    genome = parse_ddl(DDL)
    data, receipt = generate(genome, plan())
    with pytest.raises(IntegrityError):
        DatabaseConnector(engine).write(genome, data, receipt)
    with engine.connect() as connection:
        assert connection.exec_driver_sql("SELECT count(*) FROM parents").scalar() == 1
    engine.dispose()
