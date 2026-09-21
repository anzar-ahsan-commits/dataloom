"""Local observations and modest, evidence-backed coverage suggestions."""

from __future__ import annotations

import json
import sqlite3
from collections import Counter
from contextlib import closing
from typing import TYPE_CHECKING, Any

from dataloom.sqltypes import column_type

if TYPE_CHECKING:
    from pathlib import Path

    from dataloom.engine import Dataset, Receipt
    from dataloom.genome import Genome, Table
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
        """Record observed ranges, nulls, fanout, orphans, and boolean branches."""
        entities = {}
        for table in genome.tables:
            if table.name not in data:
                continue
            rows = data[table.name]
            ranges = {}
            nulls = {}
            booleans = {}
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
                if column_type(column.sql_type).family == "boolean":
                    booleans[column.name] = sorted(
                        {bool(r[column.name]) for r in rows if isinstance(r[column.name], bool)}
                    )
            fanout = {}
            orphans = {}
            for fk in table.foreign_keys:
                counts = Counter(tuple(row[c] for c in fk.columns) for row in rows)
                label = ",".join(fk.columns)
                fanout[label] = max(counts.values(), default=0)
                orphans[label] = max(len(data.get(fk.parent_table, [])) - len(counts), 0)
            entities[table.name] = {
                "rows": len(rows),
                "ranges": ranges,
                "nulls": nulls,
                "booleans": booleans,
                "fanout_max": fanout,
                "fanout_orphans": orphans,
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
        """Compare only runs of this schema; report shapes history has never covered."""
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
            suggestions.extend(_entity_gaps(table, observed))
        return suggestions or ["No gaps detected by the entity, NULL, branch, and fanout checks."]


def _entity_gaps(table: Table, observed: list[dict[str, Any]]) -> list[str]:
    """Report only the cases this schema's recorded runs have never exercised."""
    gaps = []
    never_null = [
        column.name
        for column in table.columns
        if column.nullable and not any(item["nulls"].get(column.name) for item in observed)
    ]
    if never_null:
        gaps.append(
            f"No NULL recorded in {table.name} for {len(never_null)} nullable "
            f"column(s): {', '.join(never_null)}. Add null_rate rules to cover them."
        )
    for column in table.columns:
        if column_type(column.sql_type).family != "boolean":
            continue
        values = {v for item in observed for v in item.get("booleans", {}).get(column.name, [])}
        if len(values) < 2:
            seen = " and ".join(str(v) for v in sorted(values)) or "no"
            gaps.append(
                f"{table.name}.{column.name} has only recorded {seen} values. "
                "Exercise both branches with a proportion rule."
            )
    for fk in table.foreign_keys:
        label = ",".join(fk.columns)
        maximum = max(item["fanout_max"].get(label, 0) for item in observed)
        orphans = max(item.get("fanout_orphans", {}).get(label, 0) for item in observed)
        if maximum <= 1:
            gaps.append(
                f"No {fk.parent_table} row has recorded more than {maximum} related "
                f"{table.name} rows via {label}. Raise the fanout maximum to cover "
                "collection handling."
            )
        if not orphans:
            gaps.append(
                f"Every {fk.parent_table} row has recorded related {table.name} rows via "
                f"{label}. Lower the fanout minimum to zero to cover unreferenced parents."
            )
    return gaps
