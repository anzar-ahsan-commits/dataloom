# Generation plan reference

Plans are JSON or safe-loaded YAML, validated with Pydantic. Unknown fields fail.

`dataloom generate --auto` (MCP: `auto: true`) synthesizes one from a genome instead
of asking you to write the first draft. It plans every entity so no parent is missing,
gives each table without an outgoing foreign key `--rows` records, and fans every
child out across its identifying parent -- the foreign key inside the child's own
primary key where one exists, otherwise the first declared relationship -- at one to
three children per parent. Columns carrying a supported single-column CHECK also
receive a matching rule: an enumeration becomes `choices`, and comparisons or
`BETWEEN` become bounds, so reflected constraints generate directly instead of
relying on rejection sampling. Terms it does not understand produce no rule rather
than a guess, and key and foreign-key columns are left to the engine. Other column
semantics come from classification. The plan is saved before generation, so it is
an editable starting point rather than a hidden default. Schemas with unsupported types, computed columns,
or self-references are rejected with every offending column named at once.

| Field | Default | Meaning |
|---|---|---|
| `format_version` | `1` | Unknown versions are rejected |
| `seed` | `42` | Local PRNG seed, used to derive separate table streams |
| `reference_date` | `2025-01-01` | Fixed anchor for date/time generation |
| `use_profiles` | `true` | Use numeric quantiles and observed null rates where available |
| `max_rows` | `100000` | Total in-memory row limit, maximum configurable value 2 million |
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
general constraint solver: narrow choices/bounds for restrictive constraints. When
a row cannot be satisfied, the error names the violated CHECK, length, type, or
candidate key, and says whether every attempt produced identical values -- which
means a rule contradicts a constraint and retrying cannot help.

All values are generated explicitly. Stored SQL defaults are explained in the
receipt but not executed. Empty child outputs are permitted. Nonempty children
with empty parent pools fail before export.

Integer and text columns that belong to a candidate key are numbered from the row
index rather than sampled, so uniqueness holds at any row count instead of relying
on rejection sampling. A single-column key counts 1, 2, 3. For a composite key,
each member column DataLoom generates takes one digit of a mixed-radix expansion of
the row index, so every member varies and the tuple stays unique; members supplied
by a foreign key keep the parent value. Sequence numbers are unique across the
table, not restarted per parent. Generation does not inspect existing target IDs.

Semantic and fallback text is truncated to a declared length such as `VARCHAR(20)`.
Truncation keeps generation deterministic instead of failing a row that is otherwise
valid, but it can shorten a structured value; declare a length that fits the
generator, or set an explicit rule, when the exact shape matters.

All output is materialized in memory, then validated before writing. Large row
counts need corresponding memory; the limit is a guard, not a memory guarantee.

## Derived fields

Use `derive` when one field must agree with another. This is a typed rule language,
not SQL or Python execution. It works with every supported output connector and
with schema-free templates. Derived fields can reference other derived fields:
DataLoom resolves the order regardless of YAML or schema column order.

```yaml
rules:
  subtotal:
    derive:
      kind: arithmetic
      operation: multiply
      fields: [units, unit_price]
      decimals: 2
  discount:
    derive:
      kind: case
      source: subtotal
      cases:
        - operator: ge
          value: 100
          then: 10
      otherwise: 0
  total:
    derive:
      kind: arithmetic
      operation: subtract
      fields: [subtotal, discount]
      decimals: 2
  shipped_on:
    derive:
      kind: date_offset
      source: created_on
      minimum_days: 1
      maximum_days: 7
  copied_status:
    derive:
      kind: copy
      source: status
```

Arithmetic supports `add`, `subtract`, and `multiply`, applied left to right to
at least two numeric fields. Computation uses Decimal with half-up rounding
(for example, 1.005 rounds to 1.01 at two decimal places). Output still uses the
engine's JSON scalar representation; arbitrary-precision financial accounting
is not promised. The destination SQL type/precision must accept the result.

Date offsets choose an inclusive whole-day offset using the run's seeded RNG.
They preserve date versus timestamp representation and timestamp UTC offsets.
Positive intervals produce later events; negative offsets are allowed explicitly.
This is calendar-day arithmetic, not business-day calendars or timezone/DST rules.

Cases use the first matching branch; supported operators are `eq`, `ne`, `lt`,
`le`, `gt`, `ge`. Ordered comparisons require numeric values. If no branch matches,
`otherwise` is returned (NULL if omitted). A NULL source does not match an ordered
comparison; use `eq` with `value: null` to handle it explicitly.

Copy, arithmetic and date offsets propagate source NULLs. Derived fields cannot
also specify `null_rate`, choices, bounds, semantic generators, or quotas. Use
the source rule to control its distribution. The final row still must satisfy
nullability, keys, type limits, and SQL CHECK constraints.

References are exact column names in the **same row**, including generated FK
columns. Parent-column lookups, cross-row aggregates, arbitrary expressions, and
cycles are not supported. Invalid references/cycles fail even for zero-row plans.
The new fields are additive to format version 1; older engines reject them rather
than silently ignoring the requested business relationships.
