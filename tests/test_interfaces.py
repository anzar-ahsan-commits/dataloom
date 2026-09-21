"""CLI and official SDK tool contracts share the same service behavior."""

import asyncio
import json
from pathlib import Path

import pytest
from pydantic import ValidationError
from typer.testing import CliRunner

from dataloom.cli.app import app
from dataloom.errors import ConfigurationError
from dataloom.server import create_server
from dataloom.service import DEFAULT_GENOME, GenerateInput, Service


def test_cli_offline_workflow(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATALOOM_WORKSPACE", str(tmp_path))
    (tmp_path / "schema.sql").write_text("CREATE TABLE things(id INT PRIMARY KEY, email TEXT)")
    (tmp_path / "plan.yaml").write_text("seed: 42\nentities:\n  things:\n    rows: 4\n")
    runner = CliRunner()
    for args in (
        ["introspect", "--ddl", "schema.sql"],
        ["classify"],
        ["explain"],
        ["generate", "--plan", "plan.yaml"],
        ["suggest-gaps"],
        ["list-domain-packs"],
    ):
        result = runner.invoke(app, args)
        assert result.exit_code == 0, (result.output, result.exception)
    assert (tmp_path / ".dataloom/output/plan.json").exists()


def test_mcp_schemas_and_tool_execution(tmp_path: Path) -> None:
    async def exercise() -> None:
        service = Service(tmp_path)
        server = create_server(service)
        tools = await server.list_tools()
        assert {tool.name for tool in tools} == {
            "introspect_schema",
            "classify_columns",
            "generate_dataset",
            "explain_schema_genome",
            "list_domain_packs",
            "suggest_gaps",
        }
        assert all(tool.input_schema and tool.output_schema for tool in tools)
        (tmp_path / "schema.sql").write_text("CREATE TABLE things(id INT PRIMARY KEY)")
        result = await server.call_tool("introspect_schema", {"args": {"ddl_file": "schema.sql"}})
        assert result
        resources = await server.list_resources()
        assert str(resources[0].uri) == "genome://current"
        content = await server.read_resource("genome://current")
        assert json.loads(next(iter(content)).content)["format_version"] == 1

    asyncio.run(exercise())


def test_template_and_workspace_boundary(tmp_path: Path) -> None:
    service = Service(tmp_path)
    with pytest.raises(ConfigurationError, match="workspace"):
        service.path("../outside.json")
    (tmp_path / "plan.yaml").write_text("entities:\n  patients:\n    rows: 3\n")
    result = service.generate(GenerateInput(template="healthcare:patients", plan_file="plan.yaml"))
    assert result.receipt.row_counts == {"patients": 3}


def test_mcp_generate_needs_no_explicit_genome(tmp_path: Path) -> None:
    """An agent calling generate_dataset with only `auto` must get a dataset."""

    async def exercise() -> None:
        service = Service(tmp_path)
        server = create_server(service)
        (tmp_path / "schema.sql").write_text(
            "CREATE TABLE things(id INT PRIMARY KEY, customer_email TEXT)", encoding="utf-8"
        )
        await server.call_tool("introspect_schema", {"args": {"ddl_file": "schema.sql"}})
        result = await server.call_tool(
            "generate_dataset", {"args": {"auto": True, "auto_rows": 4, "output": "out"}}
        )
        assert result

    asyncio.run(exercise())
    assert (tmp_path / "out/plan.json").is_file()


def test_schema_source_defaults_and_conflicts() -> None:
    assert GenerateInput(auto=True).genome_file == DEFAULT_GENOME
    assert GenerateInput(template="healthcare:patients", auto=True).genome_file is None
    with pytest.raises(ValidationError, match="not both"):
        GenerateInput(genome_file="g.json", template="healthcare:patients", auto=True)
