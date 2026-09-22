"""Key distribution, length fitting, type families, and failure diagnosis."""

import pytest

from dataloom.engine import generate
from dataloom.errors import GenerationError
from dataloom.genome import Classification
from dataloom.introspection import parse_ddl
from dataloom.plan import EntityPlan, Plan, Rule
from dataloom.sqltypes import column_type


@pytest.mark.parametrize(
    ("sql_type", "family", "detail"),
    [
        ("INTERVAL", None, {}),
        ("JSONB", None, {}),
        ("INTEGER[]", None, {}),
        ("SMALLINT", "integer", {"bits": 16}),
        ("BIGSERIAL", "integer", {"bits": 64}),
        ("NUMERIC(10,2)", "decimal", {"digits": 10, "scale": 2}),
        ("CHARACTER VARYING(5)", "text", {"length": 5}),
        ("TIMESTAMPTZ", "timestamp", {"zoned": True}),
        ("TIMESTAMP WITHOUT TIME ZONE", "timestamp", {"zoned": False}),
    ],
)
def test_types_are_classified_by_family_not_substring(
    sql_type: str, family: str | None, detail: dict[str, object]
) -> None:
    kind = column_type(sql_type)
    assert kind.family == family
    for name, expected in detail.items():
        assert getattr(kind, name) == expected
    assert column_type("INTERVAL").numeric is False


def test_composite_keys_vary_every_member_column() -> None:
    genome = parse_ddl("CREATE TABLE regions(region INTEGER, id INTEGER, PRIMARY KEY(region,id))")
    rows = generate(genome, Plan(entities={"regions": EntityPlan(rows=12)}))[0]["regions"]
    assert len({(r["region"], r["id"]) for r in rows}) == 12
    assert len({r["region"] for r in rows}) > 1
    assert any(r["region"] != r["id"] for r in rows)


def test_single_column_keys_still_start_at_one() -> None:
    genome = parse_ddl("CREATE TABLE items(id INTEGER PRIMARY KEY, label TEXT)")
    rows = generate(genome, Plan(entities={"items": EntityPlan(rows=4)}))[0]["items"]
    assert [row["id"] for row in rows] == [1, 2, 3, 4]


def test_unique_columns_scale_past_the_default_numeric_bounds() -> None:
    genome = parse_ddl(
        "CREATE TABLE t(id INT PRIMARY KEY, code INT UNIQUE, label VARCHAR(6) UNIQUE)"
    )
    rows = generate(genome, Plan(entities={"t": EntityPlan(rows=2500)}))[0]["t"]
    assert len({r["code"] for r in rows}) == 2500
    assert len({r["label"] for r in rows}) == 2500


def test_semantic_values_are_fitted_to_declared_length() -> None:
    genome = parse_ddl("CREATE TABLE p(id INT PRIMARY KEY, town VARCHAR(6))")
    genome.tables[0].columns[1].classification = Classification(
        semantic_type="city", source="manual", evidence="fixture"
    )
    rows = generate(genome, Plan(entities={"p": EntityPlan(rows=20)}))[0]["p"]
    assert all(isinstance(r["town"], str) and 0 < len(r["town"]) <= 6 for r in rows)


def test_failure_names_the_violated_check_and_advises_widening() -> None:
    genome = parse_ddl("CREATE TABLE t(id INT PRIMARY KEY, amount INT CHECK(amount > 100))")
    plan = Plan(entities={"t": EntityPlan(rows=2, rules={"amount": Rule(minimum=1, maximum=50)})})
    with pytest.raises(GenerationError) as error:
        generate(genome, plan)
    assert "CHECK (amount > 100) is false" in str(error.value)
    assert "Widen or relax" in str(error.value)


def test_fully_determined_rows_report_that_retrying_cannot_help() -> None:
    genome = parse_ddl("CREATE TABLE t(id INT PRIMARY KEY, label TEXT UNIQUE)")
    plan = Plan(entities={"t": EntityPlan(rows=2, rules={"label": Rule(choices=["same"])})})
    with pytest.raises(GenerationError, match="retrying cannot help"):
        generate(genome, plan)


def test_length_violations_are_explained_not_just_rejected() -> None:
    genome = parse_ddl("CREATE TABLE t(id INT PRIMARY KEY, code VARCHAR(2))")
    plan = Plan(entities={"t": EntityPlan(rows=1, rules={"code": Rule(choices=["toolong"])})})
    with pytest.raises(GenerationError, match="over VARCHAR\\(2\\)"):
        generate(genome, plan)


@pytest.mark.parametrize(
    "keys",
    ["PRIMARY KEY(a,b), UNIQUE(a)", "PRIMARY KEY(a,b), UNIQUE(b,c)"],
)
def test_overlapping_candidate_keys_can_generate_distinct_rows(keys: str) -> None:
    genome = parse_ddl(f"CREATE TABLE t(a INT, b INT, c INT, {keys})")
    plan = Plan(entities={"t": EntityPlan(rows=20)})
    data, receipt = generate(genome, plan)
    assert len(data["t"]) == 20
    assert generate(genome, plan) == (data, receipt)
