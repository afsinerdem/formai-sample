from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path

from formai.errors import IntegrationUnavailable
from formai.models import RenderedPage


class TesseractOCRReader:
    def __init__(self, binary_path: str = "tesseract", lang: str = "eng"):
        self.binary_path = binary_path
        self.lang = lang

    def is_available(self) -> bool:
        if Path(self.binary_path).is_absolute():
            return Path(self.binary_path).exists()
        return shutil.which(self.binary_path) is not None

    def extract_text(self, page: RenderedPage, psm: int = 6) -> str:
        if not self.is_available():
            raise IntegrationUnavailable(
                f"Tesseract binary is not available: {self.binary_path}"
            )

        with tempfile.TemporaryDirectory(prefix="formai_tesseract_") as temp_dir:
            image_path = Path(temp_dir) / "crop.png"
            image_path.write_bytes(page.image_bytes)
            command = [
                self.binary_path,
                str(image_path),
                "stdout",
                "--psm",
                str(psm),
                "-l",
                self.lang,
            ]
            completed = subprocess.run(
                command,
                capture_output=True,
                text=True,
                check=False,
            )
            if completed.returncode != 0:
                detail = (completed.stderr or completed.stdout or "").strip()
                raise IntegrationUnavailable(
                    f"Tesseract OCR failed with exit code {completed.returncode}: {detail}"
                )
            return completed.stdout.strip()
