"""Explainable semantic inference with optional, cached LLM disambiguation."""

from __future__ import annotations

import hashlib
import json
import re
from typing import TYPE_CHECKING

from dataloom.genome import Classification, Genome, Model

if TYPE_CHECKING:
    from dataloom.providers import Provider

CLASSIFIER_VERSION = 2

ALIASES = {
    "email": "email",
    "email_address": "email",
    "e_mail": "email",
    "phone": "us_phone",
    "phone_number": "us_phone",
    "telephone": "us_phone",
    "mobile": "us_phone",
    "fax": "us_phone",
    "first_name": "first_name",
    "given_name": "first_name",
    "forename": "first_name",
    "last_name": "last_name",
    "surname": "last_name",
    "family_name": "last_name",
    "full_name": "full_name",
    "name": "full_name",
    "contact_name": "full_name",
    "username": "username",
    "user_name": "username",
    "login": "username",
    "handle": "username",
    "company": "company",
    "company_name": "company",
    "organization": "company",
    "organisation": "company",
    "employer": "company",
    "vendor": "company",
    "supplier": "company",
    "job_title": "job_title",
    "job": "job_title",
    "occupation": "job_title",
    "address": "street_address",
    "street": "street_address",
    "street_address": "street_address",
    "address_line_1": "street_address",
    "city": "city",
    "town": "city",
    "locality": "city",
    "state": "us_state",
    "billing_state": "us_state",
    "shipping_state": "us_state",
    "mailing_state": "us_state",
    "state_code": "us_state_abbr",
    "state_abbr": "us_state_abbr",
    "zip": "postcode",
    "zip_code": "postcode",
    "postal_code": "postcode",
    "postcode": "postcode",
    "country": "country",
    "url": "url",
    "website": "url",
    "homepage": "url",
    "link": "url",
    "ip": "ipv4",
    "ip_address": "ipv4",
    "currency": "currency_code",
    "currency_code": "currency_code",
    "description": "description",
    "notes": "description",
    "comment": "description",
    "comments": "description",
    "summary": "description",
    "remarks": "description",
    "ssn": "ssn",
    "social_security_number": "ssn",
    "npi": "npi",
    "provider_npi": "npi",
    "icd10_code": "icd10_code",
    "icd_code": "icd10_code",
    "diagnosis_code": "icd10_code",
    "loinc_code": "loinc_code",
}

# Generic English words whose meaning depends on the whole column name: `name`
# alone is a person, but `product_name` is not. These never match a subspan.
EXACT_ONLY = {"name", "state"}

SSN_PATTERN = r"^\d{3}\-\d{2}\-\d{4}$"


class Labels(Model):
    """Provider classifications keyed by qualified column name."""

    labels: dict[str, str]


def semantic_for(name: str, allowed: set[str]) -> tuple[str, str] | None:
    """Match a column name exactly, then by its longest recognized token span."""
    split = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", name)
    normalized = re.sub(r"[^a-z0-9]+", "_", split.lower()).strip("_")
    label = ALIASES.get(normalized)
    if label and label in allowed:
        return label, f"Exact alias: {name}"
    tokens = [token for token in normalized.split("_") if token]
    for size in range(len(tokens) - 1, 0, -1):
        for start in range(len(tokens) - size + 1):
            span = "_".join(tokens[start : start + size])
            if span in EXACT_ONLY:
                continue
            candidate = ALIASES.get(span)
            if candidate and candidate in allowed:
                return candidate, f"Name contains the alias '{span}'"
    return None


def classify(
    genome: Genome,
    provider: Provider | None = None,
    refresh: bool = False,
    semantic_types: list[str] | None = None,
) -> Genome:
    """Classify unlabelled columns; persisted labels act as the local cache."""
    result = genome.model_copy(deep=True)
    pending = {}
    cache_keys = {}
    allowed = set(semantic_types or ALIASES.values())
    for table in result.tables:
        for column in table.columns:
            key = f"{table.name}.{column.name}"
            cache_keys[key] = hashlib.sha256(
                json.dumps(
                    {
                        "version": CLASSIFIER_VERSION,
                        "column": key,
                        "type": column.sql_type,
                        "pattern": column.profile.pattern if column.profile else None,
                        "allowed": sorted(allowed),
                    },
                    sort_keys=True,
                ).encode()
            ).hexdigest()
            if column.classification and column.classification.source == "manual":
                continue
            if not refresh and column.classification_cache_key == cache_keys[key]:
                continue
            column.classification = None
            column.classification_cache_key = None
            matched = semantic_for(column.name, allowed)
            if matched:
                label, evidence = matched
                column.classification = Classification(
                    semantic_type=label, source="name", evidence=evidence
                )
                column.classification_cache_key = cache_keys[key]
            elif column.profile and column.profile.pattern == SSN_PATTERN:
                column.classification = Classification(
                    semantic_type="ssn", source="pattern", evidence="Observed 3-2-4 digit shape"
                )
                column.classification_cache_key = cache_keys[key]
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
        for key, column in pending.items():
            column.classification_cache_key = cache_keys[key]
    return result
