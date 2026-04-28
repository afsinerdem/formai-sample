#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from itertools import combinations
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description="Check bounding box overlap and minimum sizes.")
    parser.add_argument("fields_json", help="JSON file containing fields with box/rect info")
    args = parser.parse_args()

    path = Path(args.fields_json).expanduser().resolve()
    payload = json.loads(path.read_text(encoding="utf-8"))
    fields = payload if isinstance(payload, list) else payload.get("fields", [])

    normalized = []
    for field in fields:
        name = field.get("name") or field.get("label") or "unknown"
        box = field.get("box") or field.get("rect")
        if not box:
            continue
        if isinstance(box, dict):
            left = float(box["left"])
            top = float(box["top"])
            right = float(box["right"])
            bottom = float(box["bottom"])
            page_number = int(box.get("page_number", field.get("page_number", 1)))
        else:
            left, top, right, bottom = [float(value) for value in box]
            page_number = int(field.get("page_number", 1))
        normalized.append((name, page_number, left, top, right, bottom))

    overlap_count = 0
    tiny = []
    for name, _, left, top, right, bottom in normalized:
        if (right - left) < 15 or (bottom - top) < 8:
            tiny.append(name)
    for left_field, right_field in combinations(normalized, 2):
        left_name, left_page, lx0, ly0, lx1, ly1 = left_field
        right_name, right_page, rx0, ry0, rx1, ry1 = right_field
        if left_page != right_page:
            continue
        inter_left = max(lx0, rx0)
        inter_top = max(ly0, ry0)
        inter_right = min(lx1, rx1)
        inter_bottom = min(ly1, ry1)
        if max(0.0, inter_right - inter_left) * max(0.0, inter_bottom - inter_top) > 0:
            overlap_count += 1
            print(f"OVERLAP {left_name} <-> {right_name}")

    if tiny:
        print("TINY:", ", ".join(sorted(set(tiny))))
    print(f"overlap_count={overlap_count}")
    return 0 if overlap_count == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
