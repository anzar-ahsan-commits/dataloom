"""Typer commands for CI, local development, and MCP server startup."""

from __future__ import annotations

import os
from pathlib import Path

import typer
from sqlalchemy.exc import SQLAlchemyError

from dataloom.errors import DataLoomError
from dataloom.service import ClassifyInput, GenerateInput, GenomeInput, IntrospectInput, Service

app = typer.Typer(no_args_is_help=True, help="DataLoom: reproducible data, connected by design.")


def _service() -> Service:
    return Service(Path(os.environ.get("DATALOOM_WORKSPACE", ".")))


@app.command()
def introspect(
    ddl: str | None = None,
    database_env: str | None = None,
    output: str = ".dataloom/genome.json",
    schema: str | None = None,
    profile_rows: int = 0,
) -> None:
    """Import a DDL file or reflect a live database into a genome."""
    result = _service().introspect(
        IntrospectInput(
            ddl_file=ddl,
            database_env=database_env,
            output=output,
            schema_name=schema,
            profile_rows=profile_rows,
        )
    )
    typer.echo(result.summary)
    typer.echo(f"Saved: {result.path}")


@app.command()
def classify(
    genome: str = ".dataloom/genome.json", llm: bool = False, refresh: bool = False
) -> None:
    """Classify columns and persist their semantic evidence."""
    typer.echo(
        _service().classify(ClassifyInput(genome_file=genome, use_llm=llm, refresh=refresh)).summary
    )


@app.command()
def generate(
    plan: str | None = None,
    request: str | None = None,
    auto: bool = False,
    rows: int = 50,
    genome: str | None = None,
    template: str | None = None,
    output: str = ".dataloom/output",
    format: str = "json",
    target_database_env: str | None = None,
) -> None:
    """Generate from a plan file, a synthesized default plan, or an LLM request."""
    args = GenerateInput.model_validate(
        {
            "plan_file": plan,
            "request": request,
            "auto": auto,
            "auto_rows": rows,
            "genome_file": genome or (None if template else ".dataloom/genome.json"),
            "template": template,
            "output": output,
            "format": format,
            "target_database_env": target_database_env,
        }
    )
    typer.echo(_service().generate(args).model_dump_json(indent=2))


@app.command()
def explain(genome: str = ".dataloom/genome.json") -> None:
    """Explain a saved genome without reading the source database."""
    typer.echo(_service().explain(GenomeInput(genome_file=genome)).summary)


@app.command("list-domain-packs")
def list_packs() -> None:
    """Show available domain generators and entity templates."""
    typer.echo(_service().list_packs().model_dump_json(indent=2))


@app.command("suggest-gaps")
def suggest_gaps(genome: str = ".dataloom/genome.json") -> None:
    """Show simple evidence-backed coverage suggestions."""
    for suggestion in _service().suggest(GenomeInput(genome_file=genome)).suggestions:
        typer.echo(f"- {suggestion}")


@app.command()
def serve() -> None:
    """Run the official SDK MCP server over stdio."""
    from dataloom.server import main as run_server

    run_server()


def main() -> None:
    """Execute the CLI with concise errors and nonzero failure status."""
    try:
        app()
    except SQLAlchemyError as exc:
        typer.echo(
            f"Database operation failed ({type(exc).__name__}); check target and constraints.",
            err=True,
        )
        raise SystemExit(1) from None
    except (DataLoomError, ValueError, OSError) as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise SystemExit(1) from None
