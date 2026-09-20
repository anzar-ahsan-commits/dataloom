"""Output adapters consume validated datasets without changing engine logic."""

from __future__ import annotations

import csv
import hashlib
import json
import tempfile
from datetime import date, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Protocol

from sqlalchemy import Date, DateTime, MetaData, Table

from dataloom.engine import Dataset, Receipt, ordered_tables, validate_dataset
from dataloom.errors import ConnectorError

if TYPE_CHECKING:
    from sqlalchemy import Engine

    from dataloom.genome import Genome


class Connector(Protocol):
    """Extension point for file, database, MLLP, or Kafka transports."""

    def write(self, genome: Genome, data: Dataset, receipt: Receipt) -> list[str]:
        """Write a validated dataset and return output identifiers."""
        ...


def _filename(name: str) -> str:
    return name.encode().hex()


class FileConnector:
    """Stage all files then publish a new directory; existing outputs are protected."""

    def __init__(self, directory: Path, format: str = "json") -> None:
        if format not in {"json", "csv", "parquet"}:
            raise ConnectorError(f"Unknown output format: {format}")
        self.directory = directory
        self.format = format

    def write(self, genome: Genome, data: Dataset, receipt: Receipt) -> list[str]:
        """Export data, replay artifacts, and content hashes in one new directory."""
        validate_dataset(genome, data)
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
                    import pyarrow as pa
                    import pyarrow.parquet as pq

                    arrays = {c.name: [r[c.name] for r in rows] for c in table.columns}
                    pq.write_table(pa.table(arrays), path)
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
            stage.rename(destination)
        return paths


class DatabaseConnector:
    """Insert into existing tables using a single all-or-nothing transaction."""

    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    def write(self, genome: Genome, data: Dataset, receipt: Receipt) -> list[str]:
        """Insert parent-first; target constraints remain authoritative."""
        validate_dataset(genome, data)
        if receipt.genome_hash != genome.fingerprint():
            raise ConnectorError("Receipt belongs to a different genome")
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
