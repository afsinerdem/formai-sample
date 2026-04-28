#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path

import fitz


def main() -> int:
    parser = argparse.ArgumentParser(description="Convert PDF pages to PNG images.")
    parser.add_argument("pdf", help="Path to PDF")
    parser.add_argument("output_dir", help="Directory for rendered images")
    parser.add_argument("--dpi", type=int, default=300, help="Raster DPI")
    args = parser.parse_args()

    pdf_path = Path(args.pdf).expanduser().resolve()
    output_dir = Path(args.output_dir).expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    scale = max(args.dpi, 72) / 72.0

    document = fitz.open(str(pdf_path))
    try:
        for index, page in enumerate(document, start=1):
            pix = page.get_pixmap(matrix=fitz.Matrix(scale, scale), alpha=False)
            out = output_dir / f"page_{index}.png"
            pix.save(out)
            print(out)
    finally:
        document.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
