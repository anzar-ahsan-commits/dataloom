"""Phase 2 boundary for preserving relationships while masking existing data."""

from dataloom.engine import Dataset
from dataloom.genome import Genome


def mask_existing(genome: Genome, data: Dataset, seed: int) -> Dataset:
    """Eventually mask sensitive values consistently across related tables."""
    raise NotImplementedError("Masking is Phase 2; Phase 1 generates new synthetic data only.")
