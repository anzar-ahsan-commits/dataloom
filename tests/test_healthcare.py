"""Independent checksum and field-position tests for public standards."""

from datetime import date
from random import Random

import pytest
from faker import Faker

from dataloom.domains import Context, DomainPack, Registry
from dataloom.domains.healthcare import generate_npi, npi_check_digit, valid_npi
from dataloom.domains.hl7 import build_message
from dataloom.errors import DomainPackError


def context() -> Context:
    faker = Faker()
    faker.seed_instance(42)
    return Context(Random(42), faker, date(2025, 1, 1))


def test_npi_cms_example_and_independent_luhn() -> None:
    assert npi_check_digit("123456789") == "3"
    assert valid_npi("1234567893")
    assert not valid_npi("1234567890")
    ctx = context()
    for _ in range(1000):
        npi = generate_npi(ctx)
        digits = [int(d) for d in "80840" + npi]
        total = sum(
            (d * 2 - 9 if d > 4 else d * 2) if i % 2 else d for i, d in enumerate(reversed(digits))
        )
        assert total % 10 == 0


@pytest.mark.parametrize("kind", ["ADT^A01", "ORU^R01"])
def test_hl7_required_fields(kind: str) -> None:
    message = build_message(context(), kind, "42", "A|B", "C^D")
    segments = [s.split("|") for s in message.rstrip("\r").split("\r")]
    assert segments[0][1] == "^~\\&"
    assert segments[0][8].startswith(kind)
    assert segments[0][10:12] == ["T", "2.5"]
    pid = next(s for s in segments if s[0] == "PID")
    assert pid[3] == "42^^^DATALOOM^MR"
    assert pid[5] == "C\\S\\D^A\\F\\B"
    names = [s[0] for s in segments]
    if kind == "ADT^A01":
        assert names == ["MSH", "EVN", "PID", "PV1"]
        assert segments[-1][2] == "I"
    else:
        assert names == ["MSH", "PID", "OBR", "OBX"]
        assert segments[-2][4].endswith("^LN")
        assert segments[-1][2] == "NM"
        assert float(segments[-1][5]) == 14
        assert segments[-1][11] == "F"
    assert build_message(context(), kind, "42", "A|B", "C^D") == message


def test_registry_rejects_collisions_and_offers_template() -> None:
    registry = Registry.builtin()
    assert registry.packs["healthcare"].templates["patients"]().tables[0].name == "patients"
    with pytest.raises(DomainPackError):
        registry.register(DomainPack("another", "1", {"npi": generate_npi}))
