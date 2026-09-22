# Changelog

This project is in alpha. Entries describe implemented source changes, not a
promise of a published package or compatibility beyond the documented scope.

## 0.1.0.dev4

- Fixed automatic plans for negative, high, and fractional integer CHECK bounds;
  impossible integer intervals now report the affected table and column.
- Fixed overlapping candidate-key generation so a composite primary key plus a
  narrower UNIQUE constraint does not repeat deterministic values.
- Limited built-in string-semantic heuristics to text columns, preserving numeric
  identifiers such as `company_id`; classifier cache/provenance now uses version 3.
- Corrected Boolean literal casts, integer rounding/range checks, and integer
  literal precision in CHECK evaluation. Numeric/Boolean casts of column-dependent
  expressions now fail explicitly because their source-type semantics are not
  modeled. Added comparisons against live PostgreSQL for supported cast behavior.
- Added 25 regression cases. Validation: 140 tests passed including PostgreSQL 16;
  88% combined coverage, Ruff, and strict mypy passed on Windows/Python 3.12.

Generated values and classifier artifacts can change for the corrected cases.
Preserve the earlier engine and artifacts when replaying earlier receipts.

## 0.1.0.dev3

**Breaking:** the MCP extra now requires mcp 2.2 or newer. The official SDK renamed
`FastMCP` to `MCPServer` in 2.x and dropped the 1.x module, so `.[mcp]` moved from
`>=1.28,<2.0` to `>=2.2.0,<3.0`. Reinstall the extra when upgrading. The six tools,
their typed `args` objects, the `genome://current` resource, and the stdio transport
are unchanged; only the SDK import and a few of its response attribute names moved.

- Migrated the MCP adapter to the `MCPServer` API.
- `generate_dataset` no longer requires `genome_file`. It falls back to the workspace
  genome exactly as the CLI already did, so an agent can call it with `auto` alone.
  Specifying both `genome_file` and `template` is still rejected. The defaulting now
  lives in the shared input model rather than the CLI adapter.

## 0.1.0.dev2

- Added `--auto` (MCP `auto`) to synthesize a reviewable default plan from a genome,
  so a first dataset needs neither a hand-written plan nor a provider key. Entities
  without a parent take a row count; children fan out from their identifying parent.
- Grew the core semantic generators from 5 to 19 (full names, companies, job titles,
  street addresses, cities, states, postcodes, countries, usernames, URLs, IPv4,
  currency codes, descriptions) inside ranges reserved for documentation and testing.
- Matched column names by token span and camelCase, so `customer_email` and
  `billingCity` classify while generic names such as `product_name` stay unlabelled.
- Composite candidate keys now vary every member column instead of repeating one
  ordinal. Unique integer and text columns are numbered, so they no longer exhaust
  rejection sampling above the default numeric bounds.
- Truncated generated text to declared column lengths rather than failing the row.
- Replaced substring SQL type matching with one exact type-family module: `INTERVAL`
  is no longer treated as an integer, and generation is about 1.7x faster.
- Constraint failures now name the violated CHECK, length, type, or candidate key,
  and state whether every attempt was identical, which means retrying cannot help.
- Coverage suggestions report only shapes no recorded run has covered, group NULL
  gaps per entity, and add boolean-branch and unreferenced-parent gaps.
- Lowered the `max_rows` ceiling to 2,000,000 to match in-memory generation, and
  documented measured throughput and per-row memory.
- Accepted the forms PostgreSQL rewrites simple CHECK constraints into, so a
  reflected `amount >= 0` (stored as `amount >= 0::numeric`) and `tier IN (1,2,3)`
  (stored as `tier = ANY (ARRAY[1, 2, 3])`) no longer fail generation. Casts to
  numeric, text, and boolean are evaluated; other cast targets and non-equality
  `ANY` forms are still rejected rather than guessed at.
- `--auto` now reads supported single-column CHECK terms into `choices` or bounds,
  so enumerated and ranged columns reflected from a live database generate directly.

Generated values change in this release, so replay hashes recorded under
0.1.0.dev1 do not carry over. Plan format version 1 is unchanged and existing plan
files remain valid.

## 0.1.0.dev1

- Added typed same-row derivations: copy, arithmetic, case, and date offsets.
- Resolve field dependencies and reject invalid references and cycles before
  generation, including zero-row plans.
- Added a business-consistency demo and tests for totals, conditional rules,
  dates, null propagation, and deterministic replay.
- Prepared public repository metadata, contribution and security guidance,
  issue templates, and CI configuration.

## 0.1.0.dev0

- Added versioned schema genomes, supported PostgreSQL DDL ingestion, SQLAlchemy
  reflection, optional bounded profiling, and semantic classification.
- Added deterministic relational generation, supported constraint validation,
  reproducibility receipts, JSON/CSV/Parquet export, and database insertion.
- Added core and healthcare domain primitives and local generation history.
- Added a CLI, six MCP tools, a genome resource, and optional Anthropic adapters.
- Added fictional offline demos, documentation, tests, and packaging configuration.
