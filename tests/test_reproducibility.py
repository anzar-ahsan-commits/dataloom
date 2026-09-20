"""Observed distributions, strict validation, and immutable export provenance."""

from pathlib import Path

import pytest
from pydantic import ValidationError
from sqlalchemy import create_engine

from dataloom.connectors import FileConnector
from dataloom.engine import generate, validate_dataset
from dataloom.errors import ConnectorError, GenerationError, PlanError
from dataloom.genome import Profile
from dataloom.introspection import parse_ddl, reflect
from dataloom.plan import EntityPlan, Plan, Rule
from dataloom.profiling import profile


def test_profile_distribution_and_nulls_are_replayed() -> None:
    engine = create_engine("sqlite://")
    with engine.begin() as connection:
        connection.exec_driver_sql("CREATE TABLE readings(id INTEGER PRIMARY KEY, value REAL)")
        connection.exec_driver_sql(
            "INSERT INTO readings VALUES (1, 20), (2, 21), (3, 22), (4, NULL)"
        )
    genome = profile(reflect(engine), engine)
    plan = Plan(entities={"readings": EntityPlan(rows=100)})
    data, receipt = generate(genome, plan)
    values = [r["value"] for r in data["readings"]]
    assert values.count(None) == 25
    assert all(20 <= v <= 22 for v in values if v is not None)
    assert generate(genome, plan) == (data, receipt)
    unprofiled, _ = generate(genome, plan.model_copy(update={"use_profiles": False}))
    assert all(r["value"] is not None for r in unprofiled["readings"])
    assert max(r["value"] for r in unprofiled["readings"]) > 22
    engine.dispose()


def test_stale_receipt_rejected_and_bundle_contains_plan(tmp_path: Path) -> None:
    genome = parse_ddl("CREATE TABLE items(id INT PRIMARY KEY, label TEXT)")
    plan = Plan(entities={"items": EntityPlan(rows=2)})
    data, receipt = generate(genome, plan)
    data["items"][0]["label"] = "changed"
    with pytest.raises(ConnectorError, match="Receipt"):
        FileConnector(tmp_path / "stale").write(genome, data, receipt)
    assert not (tmp_path / "stale").exists()
    data, receipt = generate(genome, plan)
    FileConnector(tmp_path / "valid", plan=plan).write(genome, data, receipt)
    assert Plan.load(tmp_path / "valid/plan.json") == plan
    with pytest.raises(ConnectorError, match="already exists"):
        FileConnector(tmp_path / "valid").write(genome, data, receipt)


@pytest.mark.parametrize("sql_type", ["INTERVAL", "JSONB", "INTEGER[]"])
def test_unsupported_type_is_not_misclassified(sql_type: str) -> None:
    genome = parse_ddl(f"CREATE TABLE items(id INT PRIMARY KEY, value {sql_type})")
    with pytest.raises(PlanError, match="Unsupported SQL type"):
        generate(genome, Plan(entities={"items": EntityPlan(rows=1)}))


@pytest.mark.parametrize(
    ("sql_type", "bad"),
    [
        ("SMALLINT", 40000),
        ("DATE", "not-a-date"),
        ("UUID", "invalid"),
        ("NUMERIC(4,2)", 100.00),
        ("NUMERIC(4,2)", 1.234),
        ("VARCHAR(2)", "abc"),
    ],
)
def test_type_constraints_checked_on_export(sql_type: str, bad: object) -> None:
    genome = parse_ddl(f"CREATE TABLE items(id INT PRIMARY KEY, value {sql_type})")
    with pytest.raises(GenerationError):
        validate_dataset(genome, {"items": [{"id": 1, "value": bad}]})


def test_invalid_statistical_parameters_fail_early() -> None:
    with pytest.raises(ValidationError):
        Profile(sampled_rows=1, cardinality=1, null_rate=0, quantiles=[1])
    with pytest.raises(ValidationError):
        Rule(minimum=float("nan"))
    genome = parse_ddl("CREATE TABLE items(value INT)")
    with pytest.raises(PlanError, match="No integer"):
        generate(
            genome,
            Plan(
                entities={
                    "items": EntityPlan(rows=1, rules={"value": Rule(minimum=0.1, maximum=0.2)})
                }
            ),
        )
