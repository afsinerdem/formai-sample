from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Sequence

from formai.benchmarks.models import BenchmarkSample


class DatasetAdapter(ABC):
    dataset_name: str

    @abstractmethod
    def load_samples(self, split: str, max_samples: int | None = None) -> Sequence[BenchmarkSample]:
        raise NotImplementedError
