"""The public demo must work without credentials or external services."""

import json
import shutil
from pathlib import Path

from dataloom.demo import run_business_demo, run_demo


def test_demo(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[1]
    shutil.copytree(root / "examples", tmp_path / "examples")
    output = run_demo(tmp_path)
    summary = json.loads((output / "summary.json").read_text())
    assert summary["row_counts"]["patients"] == 50
    assert summary["validated"]
    assert (output / "ADT_A01.hl7").read_bytes().endswith(b"\r")


def test_business_demo(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[1]
    shutil.copytree(root / "examples", tmp_path / "examples")
    output = run_business_demo(tmp_path)
    manifest = json.loads((output / "dataset/manifest.json").read_text())
    assert manifest["receipt"]["row_counts"] == {"fulfillments": 100}
