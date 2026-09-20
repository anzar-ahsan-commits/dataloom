"""Offline demo: reflect, classify, generate, validate, replay, and inspect gaps."""

from __future__ import annotations

import json
import tempfile
from datetime import date
from pathlib import Path
from random import Random

from faker import Faker
from sqlalchemy import create_engine

from dataloom.classification import classify
from dataloom.connectors import DatabaseConnector, FileConnector
from dataloom.coverage import CoverageStore
from dataloom.domains import Context
from dataloom.domains.hl7 import build_message
from dataloom.engine import generate
from dataloom.introspection import reflect
from dataloom.plan import Plan
from dataloom.profiling import profile
from dataloom.service import explain


def run_demo(root: Path) -> Path:
    """Run the bundled fictional schema end-to-end and retain inspectable artifacts."""
    output_root = root / ".dataloom" / "demo"
    output_root.mkdir(parents=True, exist_ok=True)
    run = Path(tempfile.mkdtemp(prefix="run-", dir=output_root))
    engine = create_engine("sqlite:///" + (run / "demo.sqlite").as_posix())
    try:
        with engine.begin() as connection:
            connection.exec_driver_sql("PRAGMA foreign_keys=ON")
            ddl = (root / "examples/demo_schema.sql").read_text(encoding="utf-8")
            for statement in ddl.split(";"):
                if statement.strip():
                    connection.exec_driver_sql(statement)
        genome = classify(profile(reflect(engine), engine))
        plan = Plan.load(root / "examples/plan.yaml")
        data, receipt = generate(genome, plan)
        replay, replay_receipt = generate(genome, plan)
        if data != replay or receipt != replay_receipt:
            raise RuntimeError("Deterministic replay failed")
        FileConnector(run / "dataset", plan=plan).write(genome, data, receipt)
        DatabaseConnector(engine).write(genome, data, receipt)
        with engine.connect() as connection:
            if connection.exec_driver_sql("PRAGMA foreign_key_check").all():
                raise RuntimeError("Database FK validation failed")
        history = CoverageStore(run / "coverage.sqlite")
        history.record(genome, plan, data, receipt)
        faker = Faker()
        faker.seed_instance(plan.seed)
        context = Context(Random(plan.seed), faker, date(2025, 1, 1))
        for kind in ("ADT^A01", "ORU^R01"):
            message = build_message(context, kind, "SYNTHETIC-1", "Example", "Patient")
            (run / (kind.replace("^", "_") + ".hl7")).write_bytes(message.encode())
        print("\nDATALOOM | Connected data. Repeatable scenarios.\n")
        print(explain(genome))
        print("\nBEFORE -> AFTER")
        for table, count in receipt.row_counts.items():
            print(f"  {table:16} 0 -> {count} rows")
        abnormal = sum(bool(row["abnormal"]) for row in data["lab_results"])
        print(f"\nAbnormal results: {abnormal}/{len(data['lab_results'])} (10%, nearest row)")
        print("Integrity: PASS | Database constraints: PASS | Exact replay: PASS")
        print(f"Dataset SHA-256: {receipt.data_hash}")
        print("\nWHAT TO TEST NEXT")
        for suggestion in history.suggest(genome):
            print(f"  - {suggestion}")
        print(f"\nArtifacts: {run}")
        (run / "summary.json").write_text(
            json.dumps(receipt.model_dump(), indent=2), encoding="utf-8"
        )
        return run
    finally:
        engine.dispose()
