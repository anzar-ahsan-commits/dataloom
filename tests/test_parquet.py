"""Parquet retains schema types even for empty datasets."""

from datetime import date
from decimal import Decimal
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from dataloom.connectors import FileConnector
from dataloom.engine import generate
from dataloom.introspection import parse_ddl
from dataloom.plan import EntityPlan, Plan, Rule


def test_parquet_temporal_decimal_and_empty_schema(tmp_path: Path) -> None:
    genome = parse_ddl("CREATE TABLE t(id INT PRIMARY KEY, amount NUMERIC(5,2), created DATE)")
    for count in (0, 3):
        plan = Plan(
            entities={"t": EntityPlan(rows=count, rules={"amount": Rule(minimum=1, maximum=10)})}
        )
        data, receipt = generate(genome, plan)
        paths = FileConnector(tmp_path / str(count), "parquet").write(genome, data, receipt)
        table = pq.read_table(paths[0])
        assert table.schema.field("id").type == pa.int32()
        assert not table.schema.field("id").nullable
        assert table.schema.field("amount").type == pa.decimal128(5, 2)
        assert table.schema.field("created").type == pa.date32()
        rows = table.to_pylist()
        assert len(rows) == count
        if rows:
            assert rows[0]["amount"] == Decimal(str(data["t"][0]["amount"]))
            assert rows[0]["created"] == date.fromisoformat(data["t"][0]["created"])
