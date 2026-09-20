# Generation plan reference

Plans are JSON or safe-loaded YAML, validated with Pydantic. Unknown fields fail.

| Field | Default | Meaning |
|---|---|---|
| `format_version` | `1` | Unknown versions are rejected |
| `seed` | `42` | Local PRNG seed, used to derive separate table streams |
| `reference_date` | `2025-01-01` | Fixed anchor for date/time generation |
| `use_profiles` | `true` | Use numeric quantiles and observed null rates where available |
| `max_rows` | `100000` | Total in-memory row limit, maximum configurable value 10 million |
| `entities` | required | Table names mapped to row/fanout specifications |

Each entity requires exactly one of `rows` (nonnegative integer) or `fanout`.
A fanout names a `parent`, the ordered child `foreign_key` columns, and inclusive
`minimum`/`maximum` counts. For composite keys, column order matters. Include all
parents in the plan; DataLoom does not read existing parent rows in Phase 1.

Rules are keyed by column name. Choose at most one generation mode:

```yaml
rules:
  priority:
    choices: [routine, urgent]
  amount:
    minimum: 10
    maximum: 100
  contact:
    semantic_type: email
    null_rate: 0.05
  abnormal:
    proportion: 0.1
    value: true
    otherwise: false
```

- `choices`: uniform selection from the supplied nonempty list.
- `minimum`/`maximum`: inclusive numeric bounds; omitted sides default to 0/1000.
- `semantic_type`: a registered core or domain generator.
- `proportion`, `value`, `otherwise`: exact shuffled quota; `floor(rows*p+0.5)`.
- `null_rate`: exact shuffled null quota; invalid on nonnullable columns. Cannot
  combine with `proportion`. Explicit rules suppress observed null rates.

Rules override semantic inference for choices and bounds. Numeric profiles apply
when no explicit bounds or semantic generator applies. Set `use_profiles: false`
to disable all observed distributions. Sample top values are descriptive and are
not automatically copied into generated records.

Foreign-key overrides are rejected: values come from real generated parent tuples.
FK columns currently receive no injected nulls. Uniqueness and CHECK constraints
are handled with bounded rejection sampling (500 attempts per row). This is not a
general constraint solver: narrow choices/bounds for restrictive constraints.

All values are generated explicitly. Stored SQL defaults are explained in the
receipt but not executed. Integer primary keys start at 1; generation does not
inspect existing target IDs. Empty child outputs are permitted. Nonempty children
with empty parent pools fail before export.

All output is materialized in memory, then validated before writing. Large row
counts need corresponding memory; the limit is a guard, not a memory guarantee.
