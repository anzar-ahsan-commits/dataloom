"""Exception hierarchy for DataLoom.

Every error DataLoom raises on purpose derives from :class:`DataLoomError`, so
callers embedding the library can catch that one type and be sure they are not
swallowing unrelated failures from SQLAlchemy, Pydantic or a vendor SDK.
"""

from __future__ import annotations


class DataLoomError(Exception):
    """Base class for every error raised deliberately by DataLoom."""


class ConfigurationError(DataLoomError):
    """Raised when DataLoom is asked to run with invalid or missing configuration."""


class LLMError(DataLoomError):
    """Base class for failures originating in the LLM provider layer."""


class LLMNotConfiguredError(LLMError):
    """Raised when an LLM-backed code path runs without a configured provider.

    DataLoom treats this as a recoverable, user-facing condition rather than a
    bug: every LLM-backed feature has a documented non-LLM fallback, so the
    message names it.
    """


class LLMResponseError(LLMError):
    """Raised when a provider replies but the reply is unusable.

    Covers a missing structured-output block, malformed JSON, and output that
    fails validation against the requested response model.
    """


class SchemaIntrospectionError(DataLoomError):
    """Raised when a database or DDL file cannot be turned into a schema model."""


class GenomeError(DataLoomError):
    """Raised for invalid, unreadable, or version-incompatible genome artifacts."""


class DomainPackError(DataLoomError):
    """Raised for domain pack registration and lookup failures."""


class PlanError(DataLoomError):
    """Raised when a generation plan is invalid or inconsistent with a genome."""


class GenerationError(DataLoomError):
    """Raised when data generation cannot satisfy the requested plan."""


class ConnectorError(DataLoomError):
    """Raised when an output connector fails to write generated data."""
