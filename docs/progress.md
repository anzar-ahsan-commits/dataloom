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
as locally verified. Nothing has been published to GitHub or PyPI.

See [scope.md](scope.md) for the supported SQL subset and explicit limitations.

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
