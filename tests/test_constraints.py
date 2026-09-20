"""SQL NULL logic and rejection of unsupported expressions."""

import pytest

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
