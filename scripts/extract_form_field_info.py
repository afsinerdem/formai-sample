#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from pathlib import Path

from formai.pdf.inspector import inspect_pdf_fields


def main() -> int:
    parser = argparse.ArgumentParser(description="Extract fillable field metadata from a PDF.")
    parser.add_argument("pdf", help="Path to PDF")
    parser.add_argument("output", help="Path to JSON output")
    args = parser.parse_args()

    pdf_path = Path(args.pdf).expanduser().resolve()
    output_path = Path(args.output).expanduser().resolve()
    fields = inspect_pdf_fields(pdf_path)
    output_path.write_text(json.dumps([asdict(field) for field in fields], indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(output_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
