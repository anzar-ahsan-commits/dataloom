# Implementation milestones

1. Schema genome, DDL/reflection, profiling, classification — complete; 6 tests at checkpoint, commit `a92f690`.
2. Domain plugins and healthcare generators — complete; 10 tests at checkpoint, commit `8ae0839`.
3. Deterministic generation, connectors, coverage — complete; 23 tests at checkpoint, commit `cb6c4d9`.
4. MCP and CLI — complete; 26 tests at checkpoint, commit `0d389f9`.
5. Demo, documentation, packaging and CI — complete; final evidence below.

## Initial Phase 1 local validation

Windows, Python 3.12.10, September 20, 2026:

- Full suite: **45 passed, 1 skipped**, **86%** combined statement/branch coverage.
- Ruff lint/format and strict mypy passed.
- Actual MCP stdio initialization, tool discovery, and tool execution passed.
- Mocked Anthropic response validation and offline replay of authored plans passed.
  No live LLM API call was made.
- Fresh bootstrap demo passed with core dependencies only.
- Demo generated **50 patients, 205 orders, 310 lab results, 31 abnormal results**.
  Referential integrity, SQLite database constraints, and exact replay all passed.
- Wheel/source distribution builds and Twine metadata checks passed.
- Clean wheel installation passed; the demo ran from the installed wheel and
  bundled attribution was verified present.
- Bundled ICD-10-CM identifiers were verified against the public CDC FY2026 archive.

The skipped test is live PostgreSQL; Docker's daemon was unavailable locally.
An isolated PostgreSQL 16 CI job is configured. GitHub Actions has not been run
from this workspace; Python 3.11/3.13 and Linux are configured in CI, not claimed
as locally verified. At that milestone, nothing had been published to GitHub or PyPI.

See [scope.md](scope.md) for the supported SQL subset and explicit limitations.

## First-run quality review — 0.1.0.dev2

A review of the alpha found the engine contracts sound but the first-run experience
thin: a dataset required either hand-written YAML naming exact columns or a provider
key, and only five semantic generators existed, so most text columns produced
`test-<hex>`. Three correctness issues surfaced alongside it.

Addressed in this release:

- Default plans. `synthesize` derives a plan from a genome, saved before execution
  so it stays reviewable. Unsupported types, computed columns, and self-references
  are reported together instead of one at a time.
- Column semantics. 19 core generators, with exact, token-span, and camelCase name
  matching. Generic words are excluded from subspan matching by design, so
  `product_name` stays unlabelled rather than becoming a person.
- Composite keys. Every generated member column of a candidate key took the same
  row ordinal, so a `(region, id)` key produced `(1,1), (2,2), (3,3)`. Members now
  take separate digits of a mixed-radix expansion of the row index.
- Unique columns. A unique integer column fell back to the default 0-1000 bounds
  and could not satisfy uniqueness past roughly 500 rows. Verified at 2,500 rows.
- Type dispatch. `INTERVAL` matched the `INT` substring and was validated as an
  integer. One exact type-family module now backs generation, validation, Parquet
  typing, derivations, and profiling.
- Diagnosis. A bounds rule contradicting a CHECK spent 500 attempts and then
  advised narrowing the bounds. The error now names the violated constraint and
  distinguishes contradiction from bad luck.
- Suggestions. `suggest_gaps` emitted one fanout line per FK unconditionally. It
  now reports only uncovered shapes, and adds boolean-branch and orphan-parent gaps.

Validation on Windows, Python 3.12.10: **100 passed, 1 skipped** (live PostgreSQL),
**88%** combined statement/branch coverage. Ruff lint/format and strict mypy passed.
Both offline demos passed with unchanged row counts (50 patients, 205 orders, 310
lab results, 31 abnormal) and a changed dataset hash, as expected from new generator
values. Measured throughput rose from about 52,000 to about 87,000 rows per second
on a two-table schema. GitHub Actions still has not run from this workspace: the
3.11/3.13, Linux, and PostgreSQL 16 matrix remains configured rather than verified.

## Live PostgreSQL verification — 0.1.0.dev2

Run against PostgreSQL 16 in Docker, matching the CI service definition. The
pre-existing integration test covered only INT columns and a composite foreign key
and passed immediately; a wider probe covering every supported type family found
that **no reflected CHECK constraint worked at all**. PostgreSQL rewrites checks
when it stores them, so `balance >= 0` returns as `balance >= 0::numeric` and
`tier IN (1,2,3)` as `tier = ANY (ARRAY[1, 2, 3])`. Both were rejected by the
expression allowlist, which meant the documented live-database workflow failed on
any table with an ordinary check.

Both normalized forms are now supported, with casts limited to numeric, text, and
boolean targets and `ANY` limited to equality against an explicit array; everything
else still fails closed. `--auto` additionally reads those terms into `choices` and
bounds rules, so an enumerated column generates directly rather than exhausting
rejection sampling. All eleven supported type families reflected and round-tripped
correctly, including `NUMERIC(10, 2)`, `TIMESTAMP WITH TIME ZONE`, `BIGSERIAL`,
`UUID`, and `CHARACTER VARYING`.

A wide integration test now covers the full type range, the normalized check forms,
the derived rules, and insertion, so the gap cannot reopen silently. Unit tests
cover the same expression forms without needing a database.

Validation with the live service: **113 passed, 0 skipped**, 88% combined
statement/branch coverage; ruff and strict mypy clean; both offline demos unchanged.

Known limitations left open, in priority order:

- Sequence columns inside a composite key are numbered across the table, not
  restarted per parent, so `order_lines.line_no` runs 1..N globally instead of
  1..k within each order. A per-parent counter for keys whose other members cover
  the fanout foreign key would fix it.
- Generation remains fully in memory and hashes the whole dataset as one string.
- Unlabelled text still falls back to `test-<hex>`; low-cardinality columns such as
  `status` need an explicit `choices` rule.
- CHECK terms spanning two columns (`a > b`), disjunctions, and function calls are
  understood by neither the evaluator nor the default planner.
- GitHub Actions has still never run from this workspace.

## Architectural decisions

- Domain-neutral schema and plan models; domain knowledge enters through plugins.
- Versioned artifacts reject unknown versions. Structural fingerprints exclude profiles.
- DDL is parsed, never executed. Unsupported statements fail explicitly.
- Generation uses local seeded randomness and a fixed reference date.
- Cyclic FK graphs fail with an actionable error in v1.
- LLMs author plans and classify metadata; execution never calls a provider.
- Profiling is opt-in. Sample values are not sent to providers.
- Numeric quantiles and observed null rates can guide generation; top string values
  are descriptive and are not copied into generated rows.
- Classification caches include abstentions and invalidate on metadata changes.
- Exact percentages use shuffled quotas, rounded to the nearest row.
- File exports validate receipt provenance and stage bundles before publication.
  Parquet retains declared column types even when a table has no rows.

## Business consistency enhancement — 0.1.0.dev1

Independent field sampling could produce totals, flags, or event dates that were
individually valid but contradicted each other. Added domain-neutral declarative
derivations: copy, ordered arithmetic, conditional branches, and seeded date
offsets. A stable field dependency graph resolves chains and rejects unknown
references and cycles, including for empty datasets. No expression evaluation,
network call, or new runtime dependency is involved.

The ordinary CLI/MCP generation paths accept these rules through plan files and
LLM-authored plans. Rules are additive to format v1; replay still requires matching
engine/dependency versions. Existing plan behavior remains supported.

Validation: **63 tests passed, 1 live-PostgreSQL test skipped; 87% overall coverage**.
Ruff and strict mypy passed. New checks cover business arithmetic across three
seeds, decimal rounding, conditional precedence, null propagation, invalid inputs,
FK-field references, timestamps, export/replay, and SQLite insertion constraints.

`python examples/run_demo.py --business-rules` passed in the isolated core-only
environment. Its 100 fictional fulfillments have balancing totals, policy-based
discounts, shipping 1–7 days after creation, and identical replay. See
[the example plan](../examples/business_rules.yaml) and [rule reference](plans.md#derived-fields).
