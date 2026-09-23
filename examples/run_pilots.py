"""Run fictional cross-domain pilots, independent business checks, and replay."""

from __future__ import annotations

import json
import math
import tempfile
from datetime import date
from decimal import Decimal
from importlib.metadata import version
from pathlib import Path
from time import perf_counter
from typing import TYPE_CHECKING

from sqlalchemy import create_engine

from dataloom.autoplan import synthesize
from dataloom.classification import classify
from dataloom.connectors import DatabaseConnector, FileConnector
from dataloom.coverage import CoverageStore
from dataloom.engine import generate
from dataloom.errors import DataLoomError
from dataloom.introspection import parse_ddl
from dataloom.plan import Plan

if TYPE_CHECKING:
    from dataloom.engine import Dataset, Receipt
    from dataloom.genome import Genome


def require(condition: bool, message: str) -> None:
    """Keep pilot checks active even when Python assertions are disabled."""
    if not condition:
        raise RuntimeError(message)


def business_checks(domain: str, data: Dataset) -> None:
    """Check application policies independently of engine constraint evaluation."""
    if domain == "commerce":
        for row in data["order_lines"]:
            expected = Decimal(str(row["units"])) * Decimal(str(row["unit_price"]))
            require(Decimal(str(row["line_total"])) == expected, "Line total disagrees with price")
    elif domain == "logistics":
        for row in data["shipments"]:
            created = date.fromisoformat(str(row["created_on"]))
            dispatched = date.fromisoformat(str(row["dispatched_on"]))
            delivered = date.fromisoformat(str(row["delivered_on"]))
            require(0 <= (dispatched - created).days <= 2, "Dispatch outside policy")
            require(1 <= (delivered - dispatched).days <= 5, "Delivery outside policy")
            expected = Decimal(str(row["weight_kg"])) * Decimal(str(row["rate_per_kg"]))
            require(Decimal(str(row["shipping_cost"])) == expected, "Shipping cost mismatch")
    else:
        for row in data["tickets"]:
            target = 60 if row["urgent"] else 240
            require(row["target_minutes"] == target, "Urgency target mismatch")
            overrun = int(str(row["response_minutes"])) - target
            require(row["overrun_minutes"] == overrun, "Response overrun mismatch")
            require(row["breached"] is (overrun > 0), "Breach classification mismatch")


def quota_checks(plan: Plan, data: Dataset) -> None:
    """Check intended null and Boolean quotas against exported logical rows."""
    for table, spec in plan.entities.items():
        rows = data[table]
        for column, rule in spec.rules.items():
            if rule.null_rate:
                require(
                    sum(row[column] is None for row in rows)
                    == math.floor(len(rows) * rule.null_rate + 0.5),
                    f"NULL quota mismatch: {table}.{column}",
                )
            if rule.proportion is not None:
                require(
                    sum(row[column] == rule.value for row in rows)
                    == math.floor(len(rows) * rule.proportion + 0.5),
                    f"Proportion mismatch: {table}.{column}",
                )


def database_checks(ddl: str, genome: Genome, data: Dataset, receipt: Receipt, path: Path) -> None:
    """Insert into actual constrained SQLite tables and verify row counts and FKs."""
    engine = create_engine("sqlite:///" + path.as_posix())
    try:
        with engine.begin() as connection:
            connection.exec_driver_sql("PRAGMA foreign_keys=ON")
            for statement in ddl.split(";"):
                if statement.strip():
                    connection.exec_driver_sql(statement)
        DatabaseConnector(engine).write(genome, data, receipt)
        with engine.connect() as connection:
            require(connection.exec_driver_sql("PRAGMA foreign_keys").scalar() == 1, "FKs disabled")
            require(not connection.exec_driver_sql("PRAGMA foreign_key_check").all(), "Orphan row")
            for table, rows in data.items():
                count = connection.exec_driver_sql(f'SELECT count(*) FROM "{table}"').scalar()
                require(count == len(rows), f"Database row count mismatch: {table}")
    finally:
        engine.dispose()


def run(root: Path) -> Path:
    """Run 18 explicit scenarios and three automatic baselines; retain all evidence."""
    destination = root / ".dataloom/demo"
    destination.mkdir(parents=True, exist_ok=True)
    output = Path(tempfile.mkdtemp(prefix="pilots-", dir=destination))
    results = []
    baselines = []
    for domain in ("commerce", "logistics", "support"):
        ddl = (root / f"examples/pilots/{domain}.sql").read_text(encoding="utf-8")
        genome = classify(parse_ddl(ddl))
        baseline = {"domain": domain}
        try:
            data, receipt = generate(genome, synthesize(genome, rows=12))
            baseline["schema_generation"] = "passed"
            try:
                business_checks(domain, data)
                baseline["business_policy"] = "passed"
            except RuntimeError as exc:
                baseline["business_policy"] = str(exc)
        except DataLoomError as exc:
            baseline["schema_generation"] = str(exc)
            baseline["business_policy"] = "not evaluated"
        baselines.append(baseline)
        for scenario in ("normal", "edge", "scale"):
            for seed in (42, 73):
                plan = Plan.load(root / f"examples/pilots/{domain}.yaml")
                plan.seed = seed
                for spec in plan.entities.values():
                    if spec.rows is not None:
                        spec.rows = 200 if scenario == "scale" else 12
                    if spec.fanout and scenario == "edge":
                        spec.fanout.minimum = 0
                        spec.fanout.maximum = 3
                    if scenario == "edge":
                        for rule in spec.rules.values():
                            if rule.null_rate:
                                rule.null_rate = 0.3
                started = perf_counter()
                data, receipt = generate(genome, plan)
                elapsed = perf_counter() - started
                business_checks(domain, data)
                quota_checks(plan, data)
                replay, replay_receipt = generate(genome, plan)
                require((data, receipt) == (replay, replay_receipt), "Replay mismatch")
                target = output / f"{domain}-{scenario}-{seed}"
                FileConnector(target, plan=plan).write(genome, data, receipt)
                for table, details in json.loads((target / "manifest.json").read_text())[
                    "tables"
                ].items():
                    exported = json.loads((target / details["file"]).read_text())
                    require(exported == data[table], "JSON readback mismatch")
                database_checks(ddl, genome, data, receipt, target / "validation.sqlite")
                history = CoverageStore(output / "coverage.sqlite")
                history.record(genome, plan, data, receipt)
                results.append(
                    {
                        "domain": domain,
                        "scenario": scenario,
                        "seed": seed,
                        "row_counts": receipt.row_counts,
                        "data_hash": receipt.data_hash,
                        "generation_seconds": round(elapsed, 4),
                        "business_checks": "passed",
                        "quotas": "passed",
                        "replay": "passed",
                        "sqlite_constraints": "passed",
                        "json_readback": "passed",
                        "coverage_suggestions": history.suggest(genome),
                    }
                )
                print(f"PASS {domain}/{scenario}/{seed}: {sum(receipt.row_counts.values())} rows")
    report = {"version": version("dataloom"), "auto_baselines": baselines, "runs": results}
    (output / "report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(f"Evidence: {output}")
    return output


if __name__ == "__main__":
    run(Path(__file__).resolve().parents[1])
