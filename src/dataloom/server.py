"""Official MCP SDK FastMCP adapter; stdout is reserved for the protocol."""

from __future__ import annotations

import os
from pathlib import Path

from mcp.server.fastmcp import FastMCP

from dataloom.genome import Genome, Model
from dataloom.service import (
    ClassifyInput,
    GenerateInput,
    GenerateResult,
    GenomeInput,
    GenomeResult,
    IntrospectInput,
    PackList,
    Service,
    Suggestions,
)


class EmptyInput(Model):
    """Explicit empty input for capability discovery."""


def create_server(service: Service) -> FastMCP:
    """Bind six typed tools and a genome resource to shared application services."""
    server = FastMCP("DataLoom")

    @server.tool()
    def introspect_schema(args: IntrospectInput) -> GenomeResult:
        """Import DDL or reflect a database into a saved schema genome."""
        return service.introspect(args)

    @server.tool()
    def classify_columns(args: ClassifyInput) -> GenomeResult:
        """Classify column semantics; LLM assistance is optional and explicit."""
        return service.classify(args)

    @server.tool()
    def generate_dataset(args: GenerateInput) -> GenerateResult:
        """Generate validated data from a reproducible plan or a natural-language request."""
        return service.generate(args)

    @server.tool()
    def explain_schema_genome(args: GenomeInput) -> GenomeResult:
        """Explain stored entities, types, relationships, and semantic evidence."""
        return service.explain(args)

    @server.tool()
    def list_domain_packs(args: EmptyInput) -> PackList:
        """List generators and entity templates from enabled domain packs."""
        args.model_dump()
        return service.list_packs()

    @server.tool()
    def suggest_gaps(args: GenomeInput) -> Suggestions:
        """Suggest basic coverage gaps using observed local history."""
        return service.suggest(args)

    @server.resource("genome://current", mime_type="application/json")
    def current_genome() -> str:
        """Read the default stored genome as a versioned JSON artifact."""
        return Genome.load(service.path(".dataloom/genome.json")).model_dump_json(indent=2)

    return server


def main() -> None:
    """Start a workspace-scoped stdio MCP server."""
    create_server(Service(Path(os.environ.get("DATALOOM_WORKSPACE", ".")))).run()


if __name__ == "__main__":
    main()
