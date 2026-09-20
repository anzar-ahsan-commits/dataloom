# DataLoom

**Connected data. Repeatable scenarios.**

DataLoom turns a relational schema into an inspectable **schema genome**, then
generates synthetic test datasets from a versioned plan. Ask an MCP-connected
agent for a scenario, review the resulting plan, and replay it in CI without an
LLM. Or write the plan yourself and stay offline from the start.

The practical problem: realistic-looking individual records are easy. Test data
with valid relationships, deliberate edge cases, repeatable distributions, and
an explanation of what was exercised is harder. DataLoom puts those requirements
in one small, extensible Python library.

This is an early Phase 1 implementation, not a claim of universal SQL support
or clinical realism. The engine is domain-neutral; healthcare is the first
domain pack. All examples are fictional and independently designed.

## Try it

Requires Python 3.11+ and an internet connection for the initial dependency
installation. From a checkout, run this on Windows, macOS, or Linux:

```sh
python examples/run_demo.py
```

The script creates an isolated `.demo-venv`, installs the core package, and runs
locally using SQLite. No API key, Docker, account, or database setup is needed.
Installation time depends on your connection; subsequent runs reuse the environment.
`make demo` and `sh examples/run_demo.sh` are alternatives on Unix systems.

The demo reflects a fictional patients → orders → lab_results schema, classifies
its columns, creates 50 patients with 3–5 orders each, flags exactly 10% of results
(rounded to the nearest row), inserts everything into SQLite, and verifies both
foreign keys and deterministic replay. It prints the counts, dataset hash, and
coverage suggestions. Each run retains JSON data, its plan/genome, a manifest,
a SQLite database, and sample HL7 messages under `.dataloom/demo/run-*`.

## Install and use

```sh
python -m venv .venv
# Unix: source .venv/bin/activate
# PowerShell: .venv\Scripts\Activate.ps1
python -m pip install -e .

dataloom introspect --ddl examples/demo_schema.sql
dataloom classify
dataloom explain
dataloom generate --plan examples/plan.yaml --output out/baseline
dataloom suggest-gaps
```

Optional extras: `.[mcp]`, `.[anthropic]`, `.[postgres]`, `.[parquet]`, or `.[all]`.
For development, install `.[dev]`. `python -m dataloom` works wherever the `dataloom`
executable is not on PATH.

Output directories must be new. Choose another path to run again; DataLoom does
not replace existing datasets. A bundle contains:

- `manifest.json`: row counts, hashes, versions, and table-to-file mapping.
- `genome.json` and `plan.json`: the exact inputs for replay.
- One data file per table. Table names are UTF-8 hex-encoded to avoid path and
  filename collisions; use the manifest to find them.

Replay a bundle:

```sh
dataloom generate --genome out/baseline/genome.json \
  --plan out/baseline/plan.json --output out/replay
```

Compare `receipt.data_hash` in the two manifests. See
[the reproducibility contract](docs/determinism.md).

## Plans are the product

```yaml
format_version: 1
seed: 42
reference_date: '2025-01-01'
entities:
  patients:
    rows: 50
  orders:
    fanout:
      parent: patients
      foreign_key: [patient_id]
      minimum: 3
      maximum: 5
    rules:
      priority:
        choices: [routine, urgent]
```

Include every required parent. Each entity specifies either `rows` or `fanout`.
Rules support semantic generators, choices, numeric bounds, null quotas, and
exact value proportions. See [the complete example](examples/plan.yaml) and
[plan reference](docs/plans.md). Unknown fields and conflicting rules fail validation.

To generate without an existing schema, use a domain template:

```sh
dataloom list-domain-packs
# Supply a plan with a patients entity and row count:
dataloom generate --template healthcare:patients --plan patients.yaml --output out/patients
```

For natural language, install `.[anthropic]`, set `ANTHROPIC_API_KEY` and
`DATALOOM_MODEL` to a model available in your account, then run:

```sh
dataloom generate --request "50 patients, 3 to 5 orders each, 10 percent abnormal lab results" \
  --output out/scenario
```

This authors and saves `.dataloom/authored-plan.json`, then executes it. LLM-authored
plans receive the same validation as hand-written plans. Providers only receive
schema metadata; profiling values are not included in the prompts. For a review
step before execution, a client can author a plan through the library's
`author_plan` function, inspect/save it, then invoke offline generation.

## Live databases and exports

Put the connection URL in an environment variable, for example `SOURCE_DATABASE_URL`
containing `postgresql+psycopg://user:password@localhost/database`.

```sh
dataloom introspect --database-env SOURCE_DATABASE_URL --profile-rows 1000
dataloom classify
dataloom generate --plan examples/plan.yaml --format parquet --output out/parquet
dataloom generate --plan examples/plan.yaml --format csv --output out/csv
dataloom generate --plan examples/plan.yaml --format postgres --target-database-env TARGET_DATABASE_URL
```

Profiling is optional and bounded per table. It records sample cardinality,
null rates, extrema, common values, numeric quantiles, and consistent string
shapes. Numeric generation can interpolate observed quantiles; null quotas can
follow observed rates. It does not learn cross-column correlations or copy
observed string values into generated rows. Profiled genomes can contain real
sample values: review them before committing or sharing.

Database output inserts into **existing tables** in one transaction. It neither
creates schemas nor clears existing rows. Key conflicts cause rollback. Target
sequences are not advanced to match explicitly inserted synthetic IDs; use a
dedicated test database and manage subsequent application inserts accordingly.

## MCP

Install `.[mcp]`. DataLoom uses the official Python SDK's FastMCP v1 API with a
`<2` dependency bound. Configure a stdio server in Claude Desktop using absolute
paths (on Windows, JSON paths require doubled backslashes):

```json
{
  "mcpServers": {
    "dataloom": {
      "command": "/absolute/path/to/dataloom/.venv/bin/python",
      "args": ["-m", "dataloom.server"],
      "env": {"DATALOOM_WORKSPACE": "/absolute/path/to/dataloom"}
    }
  }
}
```

The same stdio command can be registered with Claude Code or another MCP client.
The server exposes `introspect_schema`, `classify_columns`, `generate_dataset`,
`explain_schema_genome`, `list_domain_packs`, and `suggest_gaps`. Every tool accepts
a typed `args` object and returns structured output. `genome://current` exposes
the default `.dataloom/genome.json` artifact.

Artifact paths are constrained to `DATALOOM_WORKSPACE`, including resolved symlinks.
Installed domain entry points execute trusted Python code. The server is local
stdio only; do not treat it as a hosted multi-user service.

## Architecture

```mermaid
flowchart LR
  DDL[DDL file] --> Genome[Versioned schema genome]
  DB[SQLAlchemy reflection] --> Genome
  Profile[Optional bounded profiling] --> Genome
  Classify[Heuristics + optional provider] --> Genome
  Request[Natural language] --> Provider[Provider interface]
  Provider --> Plan[Versioned plan]
  YAML[Hand-authored YAML / JSON] --> Plan
  Genome --> Engine[Seeded relational engine]
  Plan --> Engine
  Packs[Domain generators / templates] --> Engine
  Engine --> Validate[Constraint validation + receipt]
  Validate --> Outputs[CSV / JSON / Parquet / PostgreSQL]
  Validate --> Coverage[Local coverage observations]
```

`service.py` coordinates these components. CLI and MCP are thin adapters. Domain
packs register semantic generators and entity templates; output connectors consume
validated datasets. See [CONTRIBUTING](CONTRIBUTING.md) for extension examples.

## Scope and checks

Phase 1 supports scalar relational schemas, composite foreign keys, acyclic parent
ordering, PK/unique constraints, and a documented SQL CHECK subset. Unsupported
types or checks fail explicitly. Cycles, overlapping foreign keys, computed columns,
advanced PostgreSQL types, arbitrary SQL expressions, masking, and subsetting are
outside the generation scope. DDL import accepts `CREATE TABLE`, not migration
scripts. See [support boundaries](docs/scope.md).

Healthcare includes CMS-checksum-valid NPIs, small ICD-10-CM and LOINC identifier
subsets, and minimal HL7 v2.5 ADT/ORU builders. These are test primitives, not a
clinical simulation or registry of real providers. Standards attribution and terms
are in [THIRD_PARTY_NOTICES](THIRD_PARTY_NOTICES.md).

```sh
python -m pytest
python -m ruff check src tests examples
python -m ruff format --check src tests examples
python -m mypy src/dataloom
```

CI runs these checks on Python 3.11–3.13 on Windows and Linux, plus a PostgreSQL 16
integration job. Local PostgreSQL tests require `DATALOOM_TEST_POSTGRES` pointing
to a disposable database with permission to create/drop test schemas. The standard
suite needs no live LLM. [Milestone evidence](docs/progress.md).

MIT licensed. Public, fictional examples only. Contributions from other domains
are welcome through the documented plugin interfaces.
