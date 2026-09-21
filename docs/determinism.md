# Reproducibility contract

The same DataLoom version, genome artifact, plan, plugin implementations, Python
version, and dependency environment produce the same logical records. The DataLoom
version is part of that contract: an engine or domain-pack change can alter generated
values while leaving the plan format untouched, so the receipt records both the
DataLoom version and every pack version. LLM authoring is outside
that contract; save its output and replay the resulting plan offline.

Each table receives a SHA-256-derived RNG seed based on the plan seed and table
name. Faker has an instance-local seed. Parent ordering is stable; dates use a
fixed reference date; core generation uses no wall-clock time, network, global
random seed, or provider call. Faker is pinned because provider data changes can
change output even for the same seed. Plugins must obey the same rules.

The receipt includes structural and full-genome hashes, plan hash, logical data
hash, row counts, dependency versions, and pack versions. File manifests separately
hash the exported bytes. Different exporter versions or platforms may produce
different CSV/Parquet bytes while preserving the same logical data.

Keep an environment lock with long-lived fixtures:

```sh
python -m pip freeze > requirements.lock.txt
```

The project supports a version range for several libraries; the range is not a
promise of identical outputs across every dependency version. Replay in the
recorded environment. Generated identity values are fictional, but some valid
identifier formats (including NPI) have no collision-free fictional namespace.
