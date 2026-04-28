#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from datetime import datetime
from pathlib import Path


KEEP_CHECKPOINT_FILES = {"MANIFEST.md", "artifacts.json"}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def move_path(source: Path, dest: Path) -> dict:
    dest.parent.mkdir(parents=True, exist_ok=True)
    if source.is_file():
        size_bytes = source.stat().st_size
        checksum = sha256_file(source)
        shutil.move(str(source), str(dest))
        return {
            "kind": "file",
            "name": source.name,
            "archived_path": str(dest),
            "size_bytes": size_bytes,
            "sha256": checksum,
        }
    total_size = sum(item.stat().st_size for item in source.rglob("*") if item.is_file())
    file_count = sum(1 for item in source.rglob("*") if item.is_file())
    shutil.move(str(source), str(dest))
    return {
        "kind": "directory",
        "name": source.name,
        "archived_path": str(dest),
        "size_bytes": total_size,
        "file_count": file_count,
    }


def archive_checkpoints(repo_root: Path, archive_root: Path) -> list[dict]:
    results: list[dict] = []
    checkpoints_root = repo_root / "checkpoints"
    for checkpoint_dir in sorted(path for path in checkpoints_root.iterdir() if path.is_dir()):
        items = [item for item in checkpoint_dir.iterdir() if item.name not in KEEP_CHECKPOINT_FILES]
        if not items:
            continue
        checkpoint_archive_root = archive_root / "checkpoints" / checkpoint_dir.name
        archived_items: list[dict] = []
        for item in items:
            archived_items.append(move_path(item, checkpoint_archive_root / item.name))
        artifacts_path = checkpoint_dir / "artifacts.json"
        payload = {
            "checkpoint": checkpoint_dir.name,
            "archived_at": datetime.now().isoformat(),
            "archive_root": str(checkpoint_archive_root),
            "items": archived_items,
        }
        artifacts_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        results.append(payload)
    return results


def archive_web_builds(repo_root: Path, archive_root: Path, *, include_current_next: bool) -> list[dict]:
    results: list[dict] = []
    web_root = repo_root / "web"
    for build_dir in sorted(web_root.glob(".next*")):
        if build_dir.name == ".next" and not include_current_next:
            continue
        payload = move_path(build_dir, archive_root / "web_builds" / build_dir.name)
        payload["archived_at"] = datetime.now().isoformat()
        results.append(payload)
    return results


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Archive non-source checkpoint artifacts and stale web build directories."
    )
    parser.add_argument(
        "--repo-root",
        default=str(Path(__file__).resolve().parents[2]),
        help="Project root",
    )
    parser.add_argument(
        "--archive-root",
        default="",
        help="Archive destination root. Defaults to tmp/archive/<timestamp>.",
    )
    parser.add_argument(
        "--include-current-next",
        action="store_true",
        help="Archive the active web/.next build output too.",
    )
    args = parser.parse_args()

    repo_root = Path(args.repo_root).expanduser().resolve()
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    archive_root = (
        Path(args.archive_root).expanduser().resolve()
        if args.archive_root
        else repo_root / "tmp" / "archive" / timestamp
    )
    archive_root.mkdir(parents=True, exist_ok=True)

    checkpoint_results = archive_checkpoints(repo_root, archive_root)
    web_build_results = archive_web_builds(
        repo_root,
        archive_root,
        include_current_next=args.include_current_next,
    )

    summary = {
        "repo_root": str(repo_root),
        "archive_root": str(archive_root),
        "archived_at": datetime.now().isoformat(),
        "checkpoint_archives": checkpoint_results,
        "web_build_archives": web_build_results,
    }
    summary_path = archive_root / "archive_summary.json"
    summary_path.write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
