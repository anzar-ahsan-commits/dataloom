"""Phase 3 boundary for extracting referentially closed production subsets."""

from dataloom.engine import Dataset
from dataloom.genome import Genome


def subset(genome: Genome, data: Dataset, roots: dict[str, list[str]]) -> Dataset:
    """Eventually expand selected root identifiers into a closed related subset."""
    raise NotImplementedError("Subsetting is Phase 3; no existing records are copied in Phase 1.")
