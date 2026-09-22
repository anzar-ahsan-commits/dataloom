"""Schema-only default plans, their boundaries, and the offline CLI path."""

from pathlib import Path

import pytest
from pydantic import ValidationError
from typer.testing import CliRunner

from dataloom.autoplan import synthesize
from dataloom.cli.app import app
from dataloom.engine import generate
from dataloom.errors import PlanError
from dataloom.introspection import parse_ddl
from dataloom.service import GenerateInput

DDL = """
CREATE TABLE customers (id INTEGER PRIMARY KEY, full_name VARCHAR(80), city VARCHAR(40));
CREATE TABLE orders (id INTEGER PRIMARY KEY, customer_id INTEGER NOT NULL,
  amount NUMERIC(10,2) CHECK(amount >= 0),
  FOREIGN KEY(customer_id) REFERENCES customers(id));
CREATE TABLE order_lines (order_id INTEGER NOT NULL, line_no INTEGER NOT NULL,
  units INTEGER, PRIMARY KEY(order_id, line_no),
  FOREIGN KEY(order_id) REFERENCES orders(id));
"""


def test_every_entity_is_planned_with_an_identifying_parent() -> None:
    plan = synthesize(parse_ddl(DDL), rows=10)
    assert set(plan.entities) == {"customers", "orders", "order_lines"}
    assert plan.entities["customers"].rows == 10
    orders = plan.entities["orders"].fanout
    lines = plan.entities["order_lines"].fanout
    assert orders is not None and orders.parent == "customers"
    assert lines is not None and lines.parent == "orders"
    assert lines.foreign_key == ["order_id"]


def test_synthesized_plan_generates_and_replays() -> None:
    genome = parse_ddl(DDL)
    plan = synthesize(genome, rows=10)
    data, receipt = generate(genome, plan)
    assert receipt.row_counts["customers"] == 10
    assert receipt.row_counts["orders"] >= 10
    assert generate(genome, plan) == (data, receipt)


def test_multiple_parents_prefer_the_identifying_relationship() -> None:
    genome = parse_ddl("""
        CREATE TABLE carts (id INTEGER PRIMARY KEY);
        CREATE TABLE products (id INTEGER PRIMARY KEY);
        CREATE TABLE cart_items (product_id INTEGER NOT NULL, cart_id INTEGER NOT NULL,
          PRIMARY KEY(cart_id, product_id),
          FOREIGN KEY(product_id) REFERENCES products(id),
          FOREIGN KEY(cart_id) REFERENCES carts(id));
    """)
    fanout = synthesize(genome).entities["cart_items"].fanout
    assert fanout is not None and fanout.parent == "products"
    generate(genome, synthesize(genome, rows=5))


@pytest.mark.parametrize(
    ("ddl", "match"),
    [
        ("CREATE TABLE t(id INT PRIMARY KEY, payload JSONB, tags INTEGER[])", "outside the sup"),
        ("CREATE TABLE t(id INT PRIMARY KEY, parent INT REFERENCES t(id))", "Self-referencing"),
    ],
)
def test_unsupported_schemas_fail_before_a_plan_is_written(ddl: str, match: str) -> None:
    with pytest.raises(PlanError, match=match):
        synthesize(parse_ddl(ddl))


def test_unsupported_columns_are_all_reported_at_once() -> None:
    genome = parse_ddl("CREATE TABLE t(id INT PRIMARY KEY, payload JSONB, window INTERVAL)")
    with pytest.raises(PlanError) as error:
        synthesize(genome)
    assert "t.payload (JSONB)" in str(error.value) and "t.window (INTERVAL)" in str(error.value)


def test_plan_sources_stay_mutually_exclusive() -> None:
    with pytest.raises(ValidationError, match="exactly one of plan_file, request, or auto"):
        GenerateInput(genome_file="g.json", auto=True, plan_file="p.yaml")
    with pytest.raises(ValidationError, match="exactly one of plan_file, request, or auto"):
        GenerateInput(genome_file="g.json")
    assert GenerateInput(genome_file="g.json", auto=True).auto_rows == 50


def test_cli_generates_from_a_schema_alone(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATALOOM_WORKSPACE", str(tmp_path))
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    (tmp_path / "shop.sql").write_text(DDL, encoding="utf-8")
    runner = CliRunner()
    for args in (["introspect", "--ddl", "shop.sql"], ["classify"]):
        assert runner.invoke(app, args).exit_code == 0
    result = runner.invoke(app, ["generate", "--auto", "--rows", "8", "--output", "out"])
    assert result.exit_code == 0, (result.output, result.exception)
    assert (tmp_path / ".dataloom/authored-plan.json").is_file()
    assert (tmp_path / "out/plan.json").is_file()
    assert '"customers": 8' in result.output


@pytest.mark.parametrize(
    ("constraint", "expected"),
    [
        ("x >= 5000", (5000, 6000)),
        ("x <= -5", (-1005, -5)),
        ("x > 1.5 AND x < 2.5", (2, 2)),
        ("x BETWEEN -8 AND -3", (-8, -3)),
    ],
)
def test_auto_numeric_bounds_cover_valid_nondefault_ranges(
    constraint: str, expected: tuple[int, int]
) -> None:
    genome = parse_ddl(f"CREATE TABLE t(id INT PRIMARY KEY, x INT CHECK({constraint}))")
    plan = synthesize(genome, rows=12)
    data, _ = generate(genome, plan)
    assert all(expected[0] <= row["x"] <= expected[1] for row in data["t"])


def test_impossible_integer_check_explains_the_column() -> None:
    genome = parse_ddl("CREATE TABLE t(id INT PRIMARY KEY, x INT CHECK(x > 1 AND x < 2))")
    with pytest.raises(PlanError, match=r"t\.x"):
        synthesize(genome)
