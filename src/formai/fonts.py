from __future__ import annotations

from pathlib import Path


def resolve_preferred_font_path(font_family: str = "noto_sans") -> Path | None:
    family = (font_family or "").strip().lower()
    repo_root = Path(__file__).resolve().parents[2]
    candidates = []
    if family == "noto_sans":
        candidates.extend(
            [
                repo_root / "src" / "formai" / "fonts" / "NotoSans-Regular.ttf",
                repo_root / "web" / "app" / "fonts" / "Arial-Regular.ttf",
                Path("/System/Library/Fonts/Supplemental/Arial Unicode.ttf"),
                Path("/System/Library/Fonts/Supplemental/Arial Unicode MS.ttf"),
                Path("/Library/Fonts/Arial Unicode.ttf"),
                Path("/Library/Fonts/Arial Unicode MS.ttf"),
            ]
        )
    candidates.extend(
        [
            repo_root / "web" / "app" / "fonts" / "Arial-Regular.ttf",
            Path("/Library/Fonts/Arial.ttf"),
            Path("/System/Library/Fonts/Supplemental/Arial.ttf"),
            Path("/System/Library/Fonts/Supplemental/Arial Unicode.ttf"),
        ]
    )
    seen: set[Path] = set()
    for candidate in candidates:
        if candidate in seen:
            continue
        seen.add(candidate)
        if candidate.exists():
            return candidate
    return None
