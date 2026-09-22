#!/usr/bin/env bash
# Internal installation step; normal users run setup.sh.
set -euo pipefail
SKILL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
exec "${PYTHON_BIN:-python3}" "$SKILL_DIR/scripts/install.py" "$@"
