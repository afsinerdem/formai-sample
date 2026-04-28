#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path

from formai.pdf.inspector import inspect_pdf_fields


def main() -> int:
    parser = argparse.ArgumentParser(description="Check whether a PDF has fillable form fields.")
    parser.add_argument("pdf", help="Path to PDF")
    args = parser.parse_args()

    pdf_path = Path(args.pdf).expanduser().resolve()
    fields = inspect_pdf_fields(pdf_path)
    if fields:
        print(f"{pdf_path} has fillable form fields ({len(fields)} field(s)).")
        return 0
    print(f"{pdf_path} does not have fillable form fields.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
