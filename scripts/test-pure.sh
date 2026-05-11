#!/usr/bin/env bash
# Run pure-function tests (no network, no cookies).
set -euo pipefail
cd "$(dirname "$0")/.."
uv run --with-editable . python -m unittest discover -s tests -v "$@"
