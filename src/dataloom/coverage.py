"""Local observations and modest, evidence-backed coverage suggestions."""

from __future__ import annotations

import json
import sqlite3
from collections import Counter
from contextlib import closing
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

    from dataloom.engine import Dataset, Receipt
    from dataloom.genome import Genome
    from dataloom.plan import Plan


class CoverageStore:
    """SQLite history stores aggregate fingerprints, not generated identities."""

    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        with closing(sqlite3.connect(path)) as connection, connection:
            connection.execute(
                "CREATE TABLE IF NOT EXISTS runs ("
                "id INTEGER PRIMARY KEY, genome_hash TEXT NOT NULL, "
                "fingerprint TEXT NOT NULL)"
            )

    def record(self, genome: Genome, plan: Plan, data: Dataset, receipt: Receipt) -> None:
        """Record observed numeric ranges, nulls, fanout, and requested rules."""
        entities = {}
        for table in genome.tables:
            if table.name not in data:
                continue
            rows = data[table.name]
            ranges = {}
            nulls = {}
            for column in table.columns:
                numbers = [
                    float(value)
                    for r in rows
                    if isinstance(value := r[column.name], (int, float))
                    and not isinstance(value, bool)
                ]
                if numbers:
                    ranges[column.name] = [min(numbers), max(numbers)]
                nulls[column.name] = sum(r[column.name] is None for r in rows)
            fanout = {}
            for fk in table.foreign_keys:
                counts = Counter(tuple(row[c] for c in fk.columns) for row in rows)
                fanout[",".join(fk.columns)] = max(counts.values(), default=0)
            entities[table.name] = {
                "rows": len(rows),
                "ranges": ranges,
                "nulls": nulls,
                "fanout_max": fanout,
                "semantics": sorted(
                    {c.classification.semantic_type for c in table.columns if c.classification}
                ),
                "rules": plan.entities[table.name].model_dump(mode="json"),
            }
        with closing(sqlite3.connect(self.path)) as connection, connection:
            connection.execute(
                "INSERT INTO runs(genome_hash, fingerprint) VALUES (?, ?)",
                (receipt.genome_hash, json.dumps(entities)),
            )

    def suggest(self, genome: Genome) -> list[str]:
        """Compare only runs of this schema; suggestions are observations, not proof."""
        with closing(sqlite3.connect(self.path)) as connection:
            history = [
                json.loads(row[0])
                for row in connection.execute(
                    "SELECT fingerprint FROM runs WHERE genome_hash = ?", (genome.fingerprint(),)
                )
            ]
        if not history:
            return ["No recorded runs for this schema. Generate a baseline dataset first."]
        suggestions = []
        for table in genome.tables:
            observed = [run[table.name] for run in history if table.name in run]
            if not observed or not any(item["rows"] for item in observed):
                suggestions.append(f"No rows recorded for {table.name}.")
                continue
            for column in table.columns:
                if column.nullable and not any(item["nulls"][column.name] for item in observed):
                    suggestions.append(f"No NULL recorded for {table.name}.{column.name}.")
            for fk in table.foreign_keys:
                maximum = max(item["fanout_max"][",".join(fk.columns)] for item in observed)
                suggestions.append(
                    f"Recorded {table.name} fanout via {','.join(fk.columns)} "
                    f"has never exceeded {maximum} children per {fk.parent_table}. "
                    "Consider a higher-fanout scenario if the application permits it."
                )
        return suggestions or ["No gaps detected by the basic entity, NULL, and fanout checks."]
