# Changelog

This project is in alpha. Entries describe implemented source changes, not a
promise of a published package or compatibility beyond the documented scope.

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
