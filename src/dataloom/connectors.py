"""Output adapters consume validated datasets without changing engine logic."""

from __future__ import annotations

import csv
import hashlib
import json
import tempfile
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import TYPE_CHECKING, Protocol

from sqlalchemy import Date, DateTime, MetaData, Table

from dataloom.engine import Dataset, Receipt, ordered_tables, validate_dataset
from dataloom.errors import ConnectorError
from dataloom.sqltypes import column_type

if TYPE_CHECKING:
    from sqlalchemy import Engine

    from dataloom.genome import Genome
    from dataloom.genome import Table as Entity
    from dataloom.plan import Plan


class Connector(Protocol):
    """Extension point for file, database, MLLP, or Kafka transports."""

    def write(self, genome: Genome, data: Dataset, receipt: Receipt) -> list[str]:
        """Write a validated dataset and return output identifiers."""
        ...


def _filename(name: str) -> str:
    return name.encode().hex()


def _validate_receipt(genome: Genome, data: Dataset, receipt: Receipt) -> None:
    validate_dataset(genome, data)
    if (
        receipt.genome_hash != genome.fingerprint()
        or receipt.genome_artifact_hash
        != hashlib.sha256(genome.model_dump_json().encode()).hexdigest()
        or receipt.data_hash
        != hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()
        or receipt.row_counts != {name: len(rows) for name, rows in data.items()}
    ):
        raise ConnectorError("Receipt does not match the supplied genome and dataset")


def _write_parquet(entity: Entity, rows: list[dict[str, object]], path: Path) -> None:
    import pyarrow as pa
    import pyarrow.parquet as pq

    fields = []
    arrays = []
    for column in entity.columns:
        kind = column_type(column.sql_type)
        values = [row[column.name] for row in rows]
        arrow_type = pa.string()
        if kind.family == "integer":
            arrow_type = {16: pa.int16(), 64: pa.int64()}.get(kind.bits, pa.int32())
        elif kind.family == "boolean":
            arrow_type = pa.bool_()
        elif kind.family == "decimal":
            if kind.digits is not None and kind.scale is not None:
                arrow_type = pa.decimal128(kind.digits, kind.scale)
                values = [Decimal(str(v)) if v is not None else None for v in values]
            else:
                arrow_type = pa.float64()
        elif kind.family == "date":
            arrow_type = pa.date32()
            values = [date.fromisoformat(str(v)) if v is not None else None for v in values]
        elif kind.family == "timestamp":
            arrow_type = pa.timestamp("us", tz="UTC" if kind.zoned else None)
            values = [datetime.fromisoformat(str(v)) if v is not None else None for v in values]
        fields.append(pa.field(column.name, arrow_type, nullable=column.nullable))
        arrays.append(pa.array(values, type=arrow_type))
    pq.write_table(pa.Table.from_arrays(arrays, schema=pa.schema(fields)), path)


class FileConnector:
    """Stage all files then publish a new directory; existing outputs are protected."""

    def __init__(self, directory: Path, format: str = "json", plan: Plan | None = None) -> None:
        if format not in {"json", "csv", "parquet"}:
            raise ConnectorError(f"Unknown output format: {format}")
        self.directory = directory
        self.format = format
        self.plan = plan

    def write(self, genome: Genome, data: Dataset, receipt: Receipt) -> list[str]:
        """Export data, replay artifacts, and content hashes in one new directory."""
        _validate_receipt(genome, data, receipt)
        if (
            self.plan
            and hashlib.sha256(self.plan.model_dump_json().encode()).hexdigest()
            != receipt.plan_hash
        ):
            raise ConnectorError("Plan does not match the supplied receipt")
        destination = self.directory.resolve()
        if destination.exists():
            raise ConnectorError(f"Output already exists: {destination}; choose a new directory")
        destination.parent.mkdir(parents=True, exist_ok=True)
        paths = []
        manifest = {}
        with tempfile.TemporaryDirectory(dir=destination.parent) as temporary:
            stage = Path(temporary) / "dataset"
            stage.mkdir()
            for table in genome.tables:
                if table.name not in data:
                    continue
                rows = data[table.name]
                filename = _filename(table.name) + "." + self.format
                path = stage / filename
                if self.format == "json":
                    path.write_text(json.dumps(rows, indent=2) + "\n", encoding="utf-8")
                elif self.format == "csv":
                    with path.open("w", newline="", encoding="utf-8") as stream:
                        writer = csv.DictWriter(stream, fieldnames=[c.name for c in table.columns])
                        writer.writeheader()
                        writer.writerows(rows)
                else:
                    _write_parquet(table, [dict(row) for row in rows], path)
                manifest[table.name] = {
                    "file": filename,
                    "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                }
                paths.append(str(destination / filename))
            (stage / "manifest.json").write_text(
                json.dumps(
                    {
                        "receipt": receipt.model_dump(),
                        "tables": manifest,
                    },
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )
            genome.save(stage / "genome.json")
            if self.plan:
                self.plan.save(stage / "plan.json")
            stage.rename(destination)
        return paths


class DatabaseConnector:
    """Insert into existing tables using a single all-or-nothing transaction."""

    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    def write(self, genome: Genome, data: Dataset, receipt: Receipt) -> list[str]:
        """Insert parent-first; target constraints remain authoritative."""
        _validate_receipt(genome, data, receipt)
        written = []
        with self.engine.begin() as connection:
            for entity in ordered_tables(genome, set(data)):
                schema, _, name = entity.name.rpartition(".")
                table = Table(name, MetaData(), schema=schema or None, autoload_with=connection)
                rows = []
                for original in data[entity.name]:
                    row: dict[str, object] = dict(original)
                    for column in table.columns:
                        value = row[column.name]
                        if isinstance(value, str):
                            if isinstance(column.type, DateTime):
                                row[column.name] = datetime.fromisoformat(value)
                            elif isinstance(column.type, Date):
                                row[column.name] = date.fromisoformat(value)
                    rows.append(row)
                if rows:
                    connection.execute(table.insert(), rows)
                written.append(entity.name)
        return written
