# Implementation milestones

1. Schema genome, DDL/reflection, profiling, classification — in progress.
2. Domain plugins and healthcare generators — pending.
3. Deterministic generation, connectors, coverage — pending.
4. MCP and CLI — pending.
5. Demo, documentation, packaging and CI — pending.

## Architectural decisions

- Domain-neutral schema and plan models; domain knowledge enters through plugins.
- Versioned artifacts reject unknown versions. Structural fingerprints exclude profiles.
- DDL is parsed, never executed. Unsupported statements fail explicitly.
- Generation uses local seeded randomness and a fixed reference date.
- Cyclic FK graphs fail with an actionable error in v1.
- LLMs author plans and classify metadata; execution never calls a provider.
- Profiling is opt-in. Sample values are not sent to providers.
