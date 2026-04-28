#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import shutil
from datetime import datetime
from pathlib import Path


KEEP_CHECKPOINT_FILES = {"MANIFEST.md", "artifacts.json"}
STALE_WEB_DIR_PREFIXES = (".next.broken", ".next.cleanrestart")


def main() -> int:
    root = Path.cwd()
    archive_root = root / "tmp" / "archive"
    archive_root.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    run_root = archive_root / timestamp
    checkpoint_archive_root = run_root / "checkpoints"
    web_archive_root = run_root / "web-builds"
    checkpoint_archive_root.mkdir(parents=True, exist_ok=True)
    web_archive_root.mkdir(parents=True, exist_ok=True)

    checkpoint_reports = []
    for checkpoint_dir in sorted((root / "checkpoints").iterdir()):
        if not checkpoint_dir.is_dir():
            continue
        moved = _normalize_checkpoint(root, checkpoint_dir, checkpoint_archive_root)
        if moved is not None:
            checkpoint_reports.append(moved)

    stale_web_reports = []
    for child in sorted((root / "web").iterdir()):
        if not child.is_dir():
            continue
        if not child.name.startswith(STALE_WEB_DIR_PREFIXES):
            continue
        destination = web_archive_root / child.name
        if destination.exists():
            shutil.rmtree(destination)
        shutil.move(str(child), str(destination))
        stale_web_reports.append(
            {
                "name": child.name,
                "archive_path": str(destination.relative_to(root)),
                "size_bytes": _dir_size(destination),
            }
        )

    summary = {
        "archived_at": datetime.now().isoformat(),
        "run_root": str(run_root.relative_to(root)),
        "checkpoint_reports": checkpoint_reports,
        "stale_web_reports": stale_web_reports,
    }
    summary_path = run_root / "summary.json"
    summary_path.write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    latest_path = archive_root / "latest_summary.json"
    latest_path.write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(summary_path)
    return 0


def _normalize_checkpoint(root: Path, checkpoint_dir: Path, archive_root: Path):
    files_to_move = [
        path
        for path in sorted(checkpoint_dir.iterdir())
        if path.is_file() and path.name not in KEEP_CHECKPOINT_FILES
    ]
    if not files_to_move:
        return None

    target_dir = archive_root / checkpoint_dir.name
    target_dir.mkdir(parents=True, exist_ok=True)
    moved_files = []
    for file_path in files_to_move:
        destination = target_dir / file_path.name
        if destination.exists():
            if destination.is_dir():
                shutil.rmtree(destination)
            else:
                destination.unlink()
        shutil.move(str(file_path), str(destination))
        moved_files.append(
            {
                "kind": "file",
                "name": file_path.name,
                "archived_path": str(destination.resolve()),
                "size_bytes": destination.stat().st_size,
                "sha256": _sha256(destination),
            }
        )

    artifacts_path = checkpoint_dir / "artifacts.json"
    payload = {
        "checkpoint": checkpoint_dir.name,
        "archived_at": datetime.now().isoformat(),
        "archive_root": str(target_dir.resolve()),
        "items": moved_files,
    }
    artifacts_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return {
        "checkpoint": checkpoint_dir.name,
        "moved_file_count": len(moved_files),
        "archive_root": str(target_dir.relative_to(root)),
    }


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _dir_size(path: Path) -> int:
    total = 0
    for child in path.rglob("*"):
        if child.is_file():
            total += child.stat().st_size
    return total


if __name__ == "__main__":
    raise SystemExit(main())
