#!/usr/bin/env bash
# Start OpenCode in this project with Rakathon Sol (EU) via APIM.
# Model default comes from ./opencode.json.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

if [[ ! -f .env ]]; then
  echo "Missing $ROOT/.env (need AZURE_LLM_API_KEY)" >&2
  exit 1
fi

set -a
# shellcheck disable=SC1091
source "$ROOT/.env"
set +a

if [[ -z "${AZURE_LLM_API_KEY:-}" ]]; then
  echo "AZURE_LLM_API_KEY is empty in .env" >&2
  exit 1
fi

# APIM requires header api-key (Bearer alone → "Invalid subscription key").
# OpenCode headers use {file:...} so sync the key from .env every launch.
mkdir -p "$ROOT/.opencode-secrets"
umask 077
printf '%s' "$AZURE_LLM_API_KEY" > "$ROOT/.opencode-secrets/apim-api-key"
chmod 600 "$ROOT/.opencode-secrets/apim-api-key"

# Private server + this project directory (loads opencode.json → Sol).
exec opencode --standalone .
