# Phase 1 support boundaries

## Schema ingestion

- Live reflection uses SQLAlchemy's Inspector for table/column types, defaults,
  nullability, PK/FK tuples, unique constraints/indexes, and CHECK text.
- A selected database schema must include all referenced tables. Cross-schema
  references outside that selection fail validation.
- DDL import parses PostgreSQL `CREATE TABLE` definitions without executing SQL.
  Inline/named PK, FK, UNIQUE, and CHECK clauses are supported; REFERENCES must
  explicitly name parent columns. ALTER, DML, functions, extensions, and CREATE AS
  SELECT are not supported.
- Expression/partial unique indexes are rejected during reflection. SQLAlchemy
  reflection is not a complete database dump: permissions, triggers, policies,
  partitions, collations, and vendor-specific behavior are not modeled.
- Version 1 artifacts reject unknown versions. No migration framework is shipped.

## Generation

Supported type families: integers, floating/numeric values, booleans, character
strings, dates, timestamps, and UUIDs. Generated/computed columns and advanced
types such as arrays, ranges, JSON, enums, geometry, and binary data are rejected.
Precision, length, required fields, keys and relationships are checked before export.

CHECK support is intentionally bounded: literals, column references, comparison,
AND/OR/NOT, NULL/IS, IN, BETWEEN, parentheses, unary minus and basic +/−/* arithmetic.
SQL NULL logic is preserved: an UNKNOWN CHECK does not reject a row. Casts,
functions, regex checks, subqueries and backend-specific operators are rejected.
PostgreSQL may normalize simple checks into unsupported expressions; the error
identifies the expression. The target database remains authoritative on insertion.

Cyclic and self-referential graphs, overlapping FK columns, and existing-parent
lookups are not implemented. Parent pools use complete tuples, preventing composite
key mixing. All generation is in memory. This is not a streaming or constraint-SMT
engine and makes no learned cross-column statistical realism guarantee. Explicit
cross-column business relationships are supported through typed copy, arithmetic,
conditional, and date-offset derivations; see [plans.md](plans.md#derived-fields).

Profiling samples at most the requested rows per table, ordered by primary key
where available. This is a bounded sample, not a random population sample. Tables
without a primary key have backend-dependent sample order. No snapshot-consistency
guarantee is made across concurrently changing tables. The genome stores local
observations including frequent values; review it before sharing.

## Output and coverage

New file bundles are staged before directory publication. CSV represents NULL as
an empty field and therefore cannot distinguish NULL from an empty string; use
JSON or Parquet when that distinction matters. JSON temporal values are ISO strings.
PostgreSQL insertion is transactional, uses explicit generated IDs, and does not
create tables, clear data, or adjust sequences.

Coverage stores aggregate observations by structural schema fingerprint, including
ranges, null counts, semantic labels, fanout, and plan rules. Suggestions only
inspect missing entities, missing nulls, and observed fanout maxima. They do not
claim application code coverage, clinical validity, or completeness.

The masking and subsetting modules are explicit future-phase stubs. There is no
masking, extraction, de-identification, MLLP, or Kafka implementation in Phase 1.
