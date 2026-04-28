#!/usr/bin/env bash
set -euo pipefail

PORT_PATTERN=':(3000|301[0-9]|302[0-9]|303[0-9]|8000)\b'

echo "FormAI local load recovery"
echo

preview_pids="$(lsof -iTCP -sTCP:LISTEN -n -P | perl -ne 'print if /:(3000|301[0-9]|302[0-9]|303[0-9]|8000)\b/' | awk '{print $2}' | sort -u)"
if [[ -n "${preview_pids}" ]]; then
  echo "Stopping preview/API listeners: ${preview_pids}"
  kill ${preview_pids} || true
else
  echo "No preview/API listeners detected."
fi

ollama_pids="$(pgrep -f 'ollama serve' || true)"
if [[ -n "${ollama_pids}" ]]; then
  echo "Stopping ollama serve: ${ollama_pids}"
  kill ${ollama_pids} || true
else
  echo "No ollama serve process detected."
fi

sleep 1
echo
echo "Remaining listeners on watched ports:"
lsof -iTCP -sTCP:LISTEN -n -P | perl -ne 'print if /:(3000|301[0-9]|302[0-9]|303[0-9]|8000|11434)\b/' || true
echo
echo "Codex renderer/GPU load can only be fully reset by manually quitting and reopening Codex.app."
