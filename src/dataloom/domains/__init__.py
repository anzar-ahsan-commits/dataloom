"""Domain plugins register generators and portable entity templates."""

from __future__ import annotations

from dataclasses import dataclass, field
from importlib.metadata import entry_points
from typing import TYPE_CHECKING, Protocol

from dataloom.errors import DomainPackError

if TYPE_CHECKING:
    from collections.abc import Callable
    from datetime import date
    from random import Random

    from faker import Faker

    from dataloom.genome import Genome, Scalar

# ISO 4217 codes only; no rates, amounts, or market data are implied.
CURRENCIES = ("USD", "EUR", "GBP", "JPY", "CAD", "AUD", "CHF")


@dataclass
class Context:
    """Per-run randomness; plugins must not use global RNGs or wall-clock time."""

    rng: Random
    faker: Faker
    reference_date: date


class Generator(Protocol):
    """A primitive semantic generator driven solely by its context."""

    def __call__(self, context: Context) -> Scalar:
        """Produce one value."""
        ...


@dataclass
class DomainPack:
    """Versioned plugin containing semantic generators and schema factories."""

    name: str
    version: str
    generators: dict[str, Generator]
    templates: dict[str, Callable[[], Genome]] = field(default_factory=dict)


# Identifier-shaped values stay inside ranges reserved for documentation and
# testing: example.test (RFC 6761), 202-555-01xx, 198.51.100.0/24 (RFC 5737),
# and the never-issued 000 SSN area number. Names and places come from Faker,
# which is pinned because its datasets are part of the replay contract.
CORE = DomainPack(
    "core",
    "2",
    {
        "email": lambda c: f"synthetic-{c.rng.getrandbits(64):016x}@example.test",
        "username": lambda c: f"user{c.rng.getrandbits(32):08x}",
        "url": lambda c: f"https://example.test/{c.rng.getrandbits(32):08x}",
        "ipv4": lambda c: f"198.51.100.{c.rng.randint(1, 254)}",
        "us_phone": lambda c: f"202-555-{c.rng.randint(100, 199):04d}",
        "ssn": lambda c: f"000-{c.rng.randint(1, 99):02d}-{c.rng.randint(1, 9999):04d}",
        "first_name": lambda c: str(c.faker.first_name()),
        "last_name": lambda c: str(c.faker.last_name()),
        "full_name": lambda c: str(c.faker.name()),
        "job_title": lambda c: str(c.faker.job()),
        "company": lambda c: str(c.faker.company()),
        "street_address": lambda c: str(c.faker.street_address()),
        "city": lambda c: str(c.faker.city()),
        "us_state": lambda c: str(c.faker.state()),
        "us_state_abbr": lambda c: str(c.faker.state_abbr()),
        "postcode": lambda c: str(c.faker.postcode()),
        "country": lambda c: str(c.faker.country()),
        "currency_code": lambda c: c.rng.choice(CURRENCIES),
        "description": lambda c: str(c.faker.sentence(nb_words=8)),
    },
)


class Registry:
    """Explicit registry: duplicate semantic names fail instead of overriding."""

    def __init__(self) -> None:
        self.packs: dict[str, DomainPack] = {}
        self.generators: dict[str, Generator] = {}

    def register(self, pack: DomainPack) -> None:
        """Register a trusted installed plugin, rejecting collisions."""
        overlap = self.generators.keys() & pack.generators.keys()
        if pack.name in self.packs or overlap:
            raise DomainPackError(f"Duplicate pack or semantic types: {pack.name}, {overlap}")
        self.packs[pack.name] = pack
        self.generators.update(pack.generators)

    @classmethod
    def builtin(cls, discover: bool = False) -> Registry:
        """Load built-ins; external entry-point code requires explicit discovery."""
        from dataloom.domains.healthcare import PACK

        registry = cls()
        registry.register(CORE)
        registry.register(PACK)
        if discover:
            for entry in entry_points(group="dataloom.domain_packs"):
                if entry.name == "healthcare" and entry.value == "dataloom.domains.healthcare:PACK":
                    continue
                pack = entry.load()
                if not isinstance(pack, DomainPack):
                    raise DomainPackError(f"{entry.name} must export a DomainPack")
                registry.register(pack)
        return registry
