#!/usr/bin/env bash
set -euo pipefail

if ! command -v conda >/dev/null 2>&1; then
  echo "conda not found on PATH." >&2
  exit 1
fi

conda build conda -c conda-forge -c defaults
