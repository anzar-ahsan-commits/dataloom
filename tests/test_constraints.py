"""SQL NULL logic and rejection of unsupported expressions."""

import pytest

from dataloom.autoplan import synthesize
from dataloom.constraints import evaluate, parse_check
from dataloom.engine import generate
from dataloom.errors import PlanError
from dataloom.introspection import parse_ddl
from dataloom.plan import EntityPlan, Plan, Rule


@pytest.mark.parametrize(
    ("sql", "value", "expected"),
    [
        ("x > 0", None, None),
        ("x IS NULL", None, True),
        ("x IN (1, NULL)", 2, None),
        ("x BETWEEN 1 AND 3", 2, True),
        ("x > 0 AND x < 5", 8, False),
        ("x IS NULL OR x > 0", None, True),
    ],
)
def test_sql_three_valued_logic(sql: str, value: int | None, expected: bool | None) -> None:
    assert evaluate(parse_check(sql), {"x": value}) is expected


def test_unsupported_checks_and_invalid_rules_fail() -> None:
    with pytest.raises(PlanError, match="Unsupported CHECK"):
        parse_check("length(name) > 2")
    genome = parse_ddl("CREATE TABLE t (id INT PRIMARY KEY, value INT NOT NULL)")
    with pytest.raises(PlanError, match="Cannot inject nulls"):
        generate(
            genome, Plan(entities={"t": EntityPlan(rows=2, rules={"value": Rule(null_rate=0.5)})})
        )
    with pytest.raises(PlanError, match="max_rows"):
        generate(genome, Plan(max_rows=1, entities={"t": EntityPlan(rows=2)}))


@pytest.mark.parametrize(
    ("sql", "value", "expected"),
    [
        ("balance >= 0::numeric", 5, True),
        ("balance >= 0::numeric", -1, False),
        ("balance >= 0::numeric", None, None),
        ("tier = ANY (ARRAY[1, 2, 3])", 2, True),
        ("tier = ANY (ARRAY[1, 2, 3])", 9, False),
        ("tier = ANY (ARRAY[1, 2, 3])", None, None),
        ("label = ANY (ARRAY['a', 'b'])", "b", True),
        ("flag = true::boolean", True, True),
    ],
)
def test_postgres_normalized_checks_are_understood(
    sql: str, value: object, expected: bool | None
) -> None:
    column = sql.split(" ")[0]
    assert evaluate(parse_check(sql), {column: value}) is expected


def test_unsupported_cast_targets_and_any_forms_still_fail() -> None:
    with pytest.raises(PlanError, match="cast target"):
        parse_check("created_at >= now()::timestamp")
    with pytest.raises(PlanError, match="Only equality against ANY"):
        parse_check("tier <> ANY (ARRAY[1, 2])")


def test_reflected_checks_become_choices_and_bounds() -> None:
    genome = parse_ddl(
        "CREATE TABLE t (id INT PRIMARY KEY, tier INT, balance NUMERIC(8,2), qty INT)"
    )
    genome.tables[0].checks = [
        "tier = ANY (ARRAY[1, 2, 3])",
        "balance >= 0::numeric",
        "qty > 4 AND qty <= 9",
    ]
    rules = synthesize(genome, rows=25).entities["t"].rules
    assert rules["tier"].choices == [1, 2, 3]
    assert rules["balance"].minimum == 0.0
    assert (rules["qty"].minimum, rules["qty"].maximum) == (5.0, 9.0)
    data, _ = generate(genome, Plan(entities={"t": synthesize(genome, rows=25).entities["t"]}))
    assert all(r["tier"] in (1, 2, 3) and 5 <= r["qty"] <= 9 for r in data["t"])


def test_checks_that_are_not_understood_produce_no_rule() -> None:
    genome = parse_ddl("CREATE TABLE t (id INT PRIMARY KEY, a INT, b INT)")
    genome.tables[0].checks = ["a > b", "length(cast(b as text)) > 1"]
    assert synthesize(genome).entities["t"].rules == {}


@pytest.mark.parametrize(
    ("sql", "row", "expected"),
    [
        ("x = 'false'::boolean", {"x": True}, False),
        ("x = 'false'::boolean", {"x": False}, True),
        ("x = 'off'::boolean", {"x": False}, True),
        ("x = 1.8::integer", {"x": 2}, True),
        ("x = (-1.5)::integer", {"x": -2}, True),
        ("x = 9007199254740993::bigint", {"x": 9007199254740993}, True),
        ("x = true::text", {"x": "true"}, True),
    ],
)
def test_casts_do_not_use_python_truthiness_or_lose_integer_precision(
    sql: str, row: dict, expected: bool
) -> None:
    assert evaluate(parse_check(sql), row) is expected


@pytest.mark.parametrize("sql", ["x = 'not-a-boolean'::boolean", "x = '1.8'::integer"])
def test_invalid_casts_raise_a_domain_error(sql: str) -> None:
    with pytest.raises(PlanError, match="cast"):
        evaluate(parse_check(sql), {"x": 1})


@pytest.mark.parametrize("sql", ["x::integer > 0", "x::boolean = true"])
def test_source_type_dependent_casts_fail_before_generation(sql: str) -> None:
    with pytest.raises(PlanError, match="Only literal"):
        parse_check(sql)
