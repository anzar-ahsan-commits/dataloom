"""Business invariants hold across seeds, dependency orders, and export paths."""

from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from random import Random

import pytest
from pydantic import ValidationError
from sqlalchemy import create_engine

from dataloom.connectors import DatabaseConnector
from dataloom.derivations import Arithmetic, Branch, Case, Copy, DateOffset, derive
from dataloom.engine import generate
from dataloom.errors import PlanError
from dataloom.introspection import parse_ddl
from dataloom.plan import EntityPlan, Plan, Rule
from dataloom.service import GenerateInput, IntrospectInput, Service

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("seed", [0, 42, 999])
def test_business_invariants_and_replay(seed: int) -> None:
    genome = parse_ddl((ROOT / "examples/business_rules.sql").read_text())
    plan = Plan.load(ROOT / "examples/business_rules.yaml")
    plan.seed = seed
    data, receipt = generate(genome, plan)
    assert generate(genome, plan) == (data, receipt)
    for row in data["fulfillments"]:
        assert Decimal(str(row["subtotal"])) == row["units"] * Decimal(str(row["unit_price"]))
        assert row["discount"] == (10 if row["subtotal"] >= 100 else 0)
        assert Decimal(str(row["total"])) == Decimal(str(row["subtotal"])) - row["discount"]
        days = (date.fromisoformat(row["shipped_on"]) - date.fromisoformat(row["created_on"])).days
        assert 1 <= days <= 7
        assert row["service_tier"] == ("bulk" if row["units"] >= 5 else "standard")
    plan.entities["fulfillments"].rules = dict(
        reversed(list(plan.entities["fulfillments"].rules.items()))
    )
    assert generate(genome, plan)[0] == data


def test_decimal_rounding_nulls_and_conditional_precedence() -> None:
    genome = parse_ddl("CREATE TABLE t(a NUMERIC(6,3), b INT, product NUMERIC(6,2), label TEXT)")
    plan = Plan(
        entities={
            "t": EntityPlan(
                rows=2,
                rules={
                    "a": Rule(choices=[1.005]),
                    "b": Rule(choices=[1]),
                    "product": Rule(derive=Arithmetic(operation="multiply", fields=["a", "b"])),
                    "label": Rule(
                        derive=Case(
                            source="product",
                            cases=[
                                Branch(operator="ge", value=1, then="first"),
                                Branch(operator="ge", value=0, then="second"),
                            ],
                            otherwise="none",
                        )
                    ),
                },
            )
        }
    )
    data, _ = generate(genome, plan)
    assert all(r["product"] == 1.01 and r["label"] == "first" for r in data["t"])
    plan.entities["t"].rules["a"] = Rule(null_rate=1)
    assert all(
        r["product"] is None and r["label"] == "none" for r in generate(genome, plan)[0]["t"]
    )


def test_copy_from_fk_and_timestamp_offset() -> None:
    genome = parse_ddl("""
        CREATE TABLE parents(id INT PRIMARY KEY);
        CREATE TABLE children(id INT PRIMARY KEY, parent_id INT REFERENCES parents(id),
            mirrored_id INT, start_time TIMESTAMP WITH TIME ZONE,
            end_time TIMESTAMP WITH TIME ZONE);
    """)
    plan = Plan(
        entities={
            "parents": EntityPlan(rows=2),
            "children": EntityPlan(
                rows=5,
                rules={
                    "mirrored_id": Rule(derive=Copy(source="parent_id")),
                    "end_time": Rule(
                        derive=DateOffset(source="start_time", minimum_days=2, maximum_days=2)
                    ),
                },
            ),
        }
    )
    for row in generate(genome, plan)[0]["children"]:
        assert row["parent_id"] == row["mirrored_id"]
        start = datetime.fromisoformat(row["start_time"])
        end = datetime.fromisoformat(row["end_time"])
        assert (end - start).days == 2 and end.utcoffset() == start.utcoffset()


@pytest.mark.parametrize(
    "rules",
    [
        {"a": Rule(derive=Copy(source="missing"))},
        {"a": Rule(derive=Copy(source="b")), "b": Rule(derive=Copy(source="a"))},
        {"a": Rule(derive=Copy(source="a"))},
        {"a": Rule(derive=Arithmetic(operation="multiply", fields=["b", "text"]))},
        {"a": Rule(derive=DateOffset(source="b"))},
    ],
)
def test_invalid_dependencies_fail_even_for_empty_output(rules: dict[str, Rule]) -> None:
    genome = parse_ddl("CREATE TABLE t(a INT, b INT, text TEXT)")
    with pytest.raises(PlanError):
        generate(genome, Plan(entities={"t": EntityPlan(rows=0, rules=rules)}))


def test_ambiguous_rules_rejected() -> None:
    with pytest.raises(ValidationError):
        Rule(derive=Copy(source="a"), minimum=0)
    with pytest.raises(ValidationError):
        Rule(derive=Copy(source="a"), null_rate=0.1)
    with pytest.raises(ValidationError):
        DateOffset(source="date", minimum_days=5, maximum_days=1)
    with pytest.raises(ValidationError):
        Rule.model_validate({"derive": {"kind": "python", "code": "print('no')"}})


def test_service_exports_replayable_derived_plan(tmp_path: Path) -> None:
    (tmp_path / "schema.sql").write_text((ROOT / "examples/business_rules.sql").read_text())
    (tmp_path / "plan.yaml").write_text((ROOT / "examples/business_rules.yaml").read_text())
    service = Service(tmp_path)
    service.introspect(IntrospectInput(ddl_file="schema.sql"))
    first = service.generate(
        GenerateInput(genome_file=".dataloom/genome.json", plan_file="plan.yaml", output="first")
    )
    replay = service.generate(
        GenerateInput(genome_file="first/genome.json", plan_file="first/plan.json", output="replay")
    )
    assert first.receipt == replay.receipt


def test_null_branches_and_boolean_comparisons_are_explicit() -> None:
    rule = Case(
        source="value",
        cases=[
            Branch(operator="eq", value=True, then="boolean"),
            Branch(operator="eq", value=None, then="missing"),
        ],
        otherwise="other",
    )
    assert derive(rule, {"value": None}, Random(1)) == "missing"
    assert derive(rule, {"value": True}, Random(1)) == "boolean"
    assert derive(rule, {"value": 1}, Random(1)) == "other"


@pytest.mark.parametrize("value", [float("nan"), float("inf"), True])
def test_invalid_arithmetic_values_raise_domain_errors(value: float | bool) -> None:
    with pytest.raises(PlanError, match="finite numbers"):
        derive(Arithmetic(operation="multiply", fields=["a", "b"]), {"a": value, "b": 0}, Random(1))


def test_business_rows_insert_with_database_constraints() -> None:
    ddl = (ROOT / "examples/business_rules.sql").read_text()
    genome = parse_ddl(ddl)
    plan = Plan.load(ROOT / "examples/business_rules.yaml")
    data, receipt = generate(genome, plan)
    engine = create_engine("sqlite://")
    try:
        with engine.begin() as connection:
            connection.exec_driver_sql(ddl)
        DatabaseConnector(engine).write(genome, data, receipt)
        with engine.connect() as connection:
            assert connection.exec_driver_sql("SELECT count(*) FROM fulfillments").scalar() == 100
            assert (
                connection.exec_driver_sql(
                    "SELECT count(*) FROM fulfillments WHERE shipped_on <= created_on "
                    "OR abs(total - (units * unit_price - discount)) > 0.000001"
                ).scalar()
                == 0
            )
    finally:
        engine.dispose()
