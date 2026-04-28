from __future__ import annotations

from pathlib import Path

from formai.benchmarks.local_manifest import LocalManifestAdapter


class TurkishHandwrittenAdapter(LocalManifestAdapter):
    dataset_name = "turkish_handwritten"
    fixture_dir_name = "turkish_handwritten"

    def __init__(self, dataset_dir: Path | None = None):
        super().__init__(dataset_dir=dataset_dir)
