#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
ARCHIVE_ROOT="${FORMAI_EXTERNAL_ARCHIVE_DIR:-$HOME/Desktop/formai_external_archive}"
STAMP="$(date +"%Y%m%d_%H%M%S")"
TARGET_DIR="${ARCHIVE_ROOT}/generated_artifacts_${STAMP}"

mkdir -p "${TARGET_DIR}/web_builds"

move_if_exists() {
  local path="$1"
  if compgen -G "${path}" > /dev/null; then
    for item in ${path}; do
      local name
      name="$(basename "${item}")"
      mv "${item}" "${TARGET_DIR}/web_builds/${name}"
      echo "archived ${item} -> ${TARGET_DIR}/web_builds/${name}"
    done
  fi
}

move_if_exists "${ROOT_DIR}/web/.next.broken.*"
move_if_exists "${ROOT_DIR}/web/.next.cleanrestart.*"

echo "archive_root=${TARGET_DIR}"
