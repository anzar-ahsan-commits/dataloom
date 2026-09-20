"""Public-standard healthcare primitives; all generated identities are fictional."""

from __future__ import annotations

from typing import TYPE_CHECKING

from dataloom.classification import classify
from dataloom.domains import Context, DomainPack
from dataloom.introspection import parse_ddl

if TYPE_CHECKING:
    from dataloom.genome import Genome

# Curated identifiers only; attribution and scope are in THIRD_PARTY_NOTICES.md.
ICD10_CODES = ("I10", "E11.9", "J45.909", "R51.9", "Z00.00")
LOINC_CODES = ("718-7", "2345-7")


def npi_check_digit(body: str) -> str:
    """Compute the CMS check digit, including the implicit 80840 issuer prefix."""
    if len(body) != 9 or not body.isascii() or not body.isdigit() or body[0] not in "12":
        raise ValueError("NPI body must have nine ASCII digits and begin with 1 or 2")
    total = 24
    for index, char in enumerate(reversed(body)):
        value = int(char) * (2 if index % 2 == 0 else 1)
        total += value // 10 + value % 10
    return str((-total) % 10)


def valid_npi(value: str) -> bool:
    """Validate format and checksum, without claiming NPPES registration."""
    try:
        return len(value) == 10 and npi_check_digit(value[:9]) == value[9]
    except ValueError:
        return False


def generate_npi(context: Context) -> str:
    """Generate a checksum-valid identifier, not a real provider identity."""
    body = str(context.rng.randint(100000000, 299999999))
    return body + npi_check_digit(body)


def patient_template() -> Genome:
    """Return a fictional minimal patient entity for schema-free generation."""
    return classify(
        parse_ddl("""
        CREATE TABLE patients (
            id INTEGER PRIMARY KEY, first_name VARCHAR(80) NOT NULL,
            last_name VARCHAR(80) NOT NULL, email VARCHAR(120),
            provider_npi VARCHAR(10), diagnosis_code VARCHAR(10)
        );
    """)
    )


PACK = DomainPack(
    "healthcare",
    "1",
    {
        "npi": generate_npi,
        "icd10_code": lambda c: c.rng.choice(ICD10_CODES),
        "loinc_code": lambda c: c.rng.choice(LOINC_CODES),
    },
    {"patients": patient_template},
)
