"""Explainable semantic inference with optional, cached LLM disambiguation."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from dataloom.genome import Classification, Genome, Model

if TYPE_CHECKING:
    from dataloom.providers import Provider

ALIASES = {
    "email": "email",
    "email_address": "email",
    "phone": "us_phone",
    "phone_number": "us_phone",
    "first_name": "first_name",
    "last_name": "last_name",
    "ssn": "ssn",
    "npi": "npi",
    "provider_npi": "npi",
    "icd10_code": "icd10_code",
    "diagnosis_code": "icd10_code",
    "loinc_code": "loinc_code",
}


class Labels(Model):
    """Provider classifications keyed by qualified column name."""

    labels: dict[str, str]


def classify(
    genome: Genome,
    provider: Provider | None = None,
    refresh: bool = False,
    semantic_types: list[str] | None = None,
) -> Genome:
    """Classify unlabelled columns; persisted labels act as the local cache."""
    result = genome.model_copy(deep=True)
    pending = {}
    allowed = set(semantic_types or ALIASES.values())
    for table in result.tables:
        for column in table.columns:
            if column.classification and (not refresh or column.classification.source == "manual"):
                continue
            column.classification = None
            label = ALIASES.get(column.name.lower())
            if label and label in allowed:
                column.classification = Classification(
                    semantic_type=label, source="name", evidence=f"Exact alias: {column.name}"
                )
            elif column.profile and column.profile.pattern == r"^\d{3}\-\d{2}\-\d{4}$":
                column.classification = Classification(
                    semantic_type="ssn", source="pattern", evidence="Observed 3-2-4 digit shape"
                )
            else:
                pending[f"{table.name}.{column.name}"] = column
    if provider and pending:
        metadata = {
            key: {"sql_type": col.sql_type, "pattern": col.profile.pattern if col.profile else None}
            for key, col in pending.items()
        }
        labels = provider.structured(
            f"Classify only confident matches using {sorted(allowed)}; omit unknowns. "
            f"Schema metadata: {json.dumps(metadata)}",
            Labels,
        )
        for key, label in labels.labels.items():
            if key not in pending or label not in allowed:
                raise ValueError(f"Provider returned an unknown column or semantic type: {key}")
            pending[key].classification = Classification(
                semantic_type=label, source="llm", evidence="Metadata disambiguation"
            )
    return result
