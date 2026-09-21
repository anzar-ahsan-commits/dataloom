"""Shared application services used by CLI and MCP adapters."""

from __future__ import annotations

import os
import sqlite3
from typing import TYPE_CHECKING, Any, Literal, Self

from pydantic import Field, model_validator
from sqlalchemy import create_engine

from dataloom.autoplan import synthesize
from dataloom.classification import classify
from dataloom.connectors import DatabaseConnector, FileConnector
from dataloom.coverage import CoverageStore
from dataloom.domains import Registry
from dataloom.engine import Receipt, generate
from dataloom.errors import ConfigurationError
from dataloom.genome import Genome, Model
from dataloom.introspection import parse_ddl, reflect
from dataloom.plan import Plan, author_plan
from dataloom.profiling import profile
from dataloom.providers import AnthropicProvider, Provider

if TYPE_CHECKING:
    from pathlib import Path


class IntrospectInput(Model):
    """Choose exactly one schema source; database credentials stay in environment."""

    ddl_file: str | None = None
    database_env: str | None = None
    schema_name: str | None = None
    profile_rows: int = Field(default=0, ge=0, le=100000)
    output: str = ".dataloom/genome.json"

    @model_validator(mode="after")
    def validate_source(self) -> Self:
        """Require one source and reject profiling without a database."""
        if (self.ddl_file is None) == (self.database_env is None):
            raise ValueError("Specify exactly one of ddl_file or database_env")
        if self.ddl_file and self.profile_rows:
            raise ValueError("Profiling requires a live database")
        return self


DEFAULT_GENOME = ".dataloom/genome.json"


class GenomeInput(Model):
    """Reference a persisted genome within the workspace."""

    genome_file: str = DEFAULT_GENOME


class ClassifyInput(GenomeInput):
    """Optional provider assistance and explicit cache refresh."""

    use_llm: bool = False
    refresh: bool = False


class GenerateInput(Model):
    """Generate from a plan, a request, or a synthesized default plan."""

    genome_file: str | None = None
    template: str | None = None
    plan_file: str | None = None
    request: str | None = None
    auto: bool = False
    auto_rows: int = Field(default=50, ge=0, le=100000)
    output: str = ".dataloom/output"
    format: Literal["json", "csv", "parquet", "postgres"] = "json"
    target_database_env: str | None = None
    authored_plan_file: str = ".dataloom/authored-plan.json"

    @model_validator(mode="before")
    @classmethod
    def default_schema_source(cls, data: Any) -> Any:
        """Fall back to the workspace genome so every adapter behaves alike."""
        if isinstance(data, dict) and data.get("genome_file") is None and not data.get("template"):
            return {**data, "genome_file": DEFAULT_GENOME}
        return data

    @model_validator(mode="after")
    def validate_sources(self) -> Self:
        """Reject ambiguous schema and plan sources."""
        if self.genome_file is not None and self.template is not None:
            raise ValueError("Specify genome_file or template, not both")
        if (self.plan_file is not None) + (self.request is not None) + self.auto != 1:
            raise ValueError("Specify exactly one of plan_file, request, or auto")
        if self.format == "postgres" and not self.target_database_env:
            raise ValueError("Postgres output requires target_database_env")
        return self


class GenomeResult(Model):
    """Saved artifact location, structural fingerprint, and schema summary."""

    path: str
    fingerprint: str
    summary: str


class GenerateResult(Model):
    """Published outputs and a deterministic validation receipt."""

    paths: list[str]
    receipt: Receipt
    plan_file: str
    warnings: list[str] = Field(default_factory=list)


class Suggestions(Model):
    """Plain-language observations from local run history."""

    suggestions: list[str]


class PackInfo(Model):
    """Discoverable domain-pack capabilities."""

    name: str
    version: str
    semantic_types: list[str]
    templates: list[str]


class PackList(Model):
    """Installed and enabled packs."""

    packs: list[PackInfo]


def explain(genome: Genome) -> str:
    """Describe relationships, semantics, and profiling scope without sample values."""
    lines = [
        f"DataLoom genome v{genome.format_version} | {len(genome.tables)} entities",
        f"Structure: {genome.fingerprint()[:16]}",
    ]
    for table in genome.tables:
        lines.append(f"\n{table.name}: {len(table.columns)} columns; PK {table.primary_key}")
        for column in table.columns:
            label = column.classification
            semantic = f" -> {label.semantic_type} ({label.source})" if label else ""
            observed = f"; sampled {column.profile.sampled_rows} rows" if column.profile else ""
            lines.append(f"  {column.name}: {column.sql_type}{semantic}{observed}")
        for fk in table.foreign_keys:
            lines.append(f"  {fk.columns} -> {fk.parent_table}{fk.parent_columns}")
        for check in table.checks:
            lines.append(f"  CHECK {check}")
    return "\n".join(lines)


class Service:
    """Workspace-scoped operations; adapters contain no generation business logic."""

    def __init__(
        self, workspace: Path, provider: Provider | None = None, registry: Registry | None = None
    ) -> None:
        self.workspace = workspace.resolve()
        self.provider = provider
        self.registry = registry or Registry.builtin(discover=True)

    def path(self, value: str) -> Path:
        """Resolve paths within the configured workspace, including symlink checks."""
        path = (self.workspace / value).resolve()
        if not path.is_relative_to(self.workspace):
            raise ConfigurationError("Artifact paths must remain within the configured workspace")
        return path

    def llm(self) -> Provider:
        """Get injected provider or lazily configure the default Anthropic adapter."""
        if self.provider is not None:
            return self.provider
        model = os.environ.get("DATALOOM_MODEL")
        if not model or not os.environ.get("ANTHROPIC_API_KEY"):
            raise ConfigurationError("Set DATALOOM_MODEL and ANTHROPIC_API_KEY, or use a plan file")
        return AnthropicProvider(model)

    def database_url(self, name: str) -> str:
        """Read a connection URL by environment-variable name without logging it."""
        value = os.environ.get(name)
        if not value:
            raise ConfigurationError(f"Database environment variable is unset: {name}")
        return value

    def introspect(self, args: IntrospectInput) -> GenomeResult:
        """Import and persist a schema, with optional bounded profiling."""
        if args.ddl_file:
            genome = parse_ddl(self.path(args.ddl_file).read_text(encoding="utf-8"))
        else:
            assert args.database_env is not None
            engine = create_engine(self.database_url(args.database_env))
            try:
                genome = reflect(engine, args.schema_name)
                if args.profile_rows:
                    genome = profile(genome, engine, args.profile_rows)
            finally:
                engine.dispose()
        return self._save(genome, args.output)

    def _save(self, genome: Genome, output: str) -> GenomeResult:
        path = self.path(output)
        genome.save(path)
        return GenomeResult(
            path=str(path), fingerprint=genome.fingerprint(), summary=explain(genome)
        )

    def classify(self, args: ClassifyInput) -> GenomeResult:
        """Classify and cache semantics in the referenced artifact."""
        genome = classify(
            Genome.load(self.path(args.genome_file)),
            self.llm() if args.use_llm else None,
            args.refresh,
            sorted(self.registry.generators),
        )
        return self._save(genome, args.genome_file)

    def explain(self, args: GenomeInput) -> GenomeResult:
        """Inspect a stored genome without mutation."""
        path = self.path(args.genome_file)
        genome = Genome.load(path)
        return GenomeResult(
            path=str(path), fingerprint=genome.fingerprint(), summary=explain(genome)
        )

    def generate(self, args: GenerateInput) -> GenerateResult:
        """Synthesize, author, or load a plan, execute offline, publish, record coverage."""
        if args.genome_file:
            genome = Genome.load(self.path(args.genome_file))
        else:
            templates = {
                f"{pack.name}:{name}": factory
                for pack in self.registry.packs.values()
                for name, factory in pack.templates.items()
            }
            if args.template not in templates:
                raise ConfigurationError(
                    f"Unknown template: {args.template}; options: {list(templates)}"
                )
            genome = templates[args.template]()
        if args.plan_file:
            plan = Plan.load(self.path(args.plan_file))
            plan_path = args.plan_file
        else:
            if args.auto:
                plan = synthesize(genome, args.auto_rows)
            else:
                assert args.request is not None
                plan = author_plan(
                    args.request, genome, self.llm(), sorted(self.registry.generators)
                )
            plan_path = args.authored_plan_file
            plan.save(self.path(plan_path))
        data, receipt = generate(genome, plan, self.registry)
        if args.format == "postgres":
            assert args.target_database_env is not None
            engine = create_engine(self.database_url(args.target_database_env))
            try:
                if engine.dialect.name != "postgresql":
                    raise ConfigurationError("postgres output requires a PostgreSQL target")
                paths = DatabaseConnector(engine).write(genome, data, receipt)
            finally:
                engine.dispose()
        else:
            directory = self.path(args.output)
            paths = FileConnector(directory, args.format, plan).write(genome, data, receipt)
        warnings = []
        try:
            CoverageStore(self.path(".dataloom/coverage.sqlite")).record(
                genome, plan, data, receipt
            )
        except (OSError, sqlite3.Error):
            warnings.append("Output succeeded, but coverage history could not be saved")
        return GenerateResult(paths=paths, receipt=receipt, plan_file=plan_path, warnings=warnings)

    def list_packs(self) -> PackList:
        """List enabled generators and schema-free templates."""
        return PackList(
            packs=[
                PackInfo(
                    name=p.name,
                    version=p.version,
                    semantic_types=sorted(p.generators),
                    templates=sorted(p.templates),
                )
                for p in self.registry.packs.values()
            ]
        )

    def suggest(self, args: GenomeInput) -> Suggestions:
        """Inspect coverage for this exact structural schema fingerprint."""
        genome = Genome.load(self.path(args.genome_file))
        return Suggestions(
            suggestions=CoverageStore(self.path(".dataloom/coverage.sqlite")).suggest(genome)
        )
