#!/usr/bin/env bash
set -euo pipefail
export PATH="$HOME/.local/bin:/opt/homebrew/bin:/usr/local/bin:$PATH"
config="$HOME/.config/literature-to-zotero/python-path"
if [[ -f "$config" ]]; then
  IFS= read -r interpreter < "$config"
else
  interpreter="${PYTHON_BIN:-python3}"
fi
if command -v cygpath >/dev/null 2>&1; then interpreter="$(cygpath -u "$interpreter")"; fi
exec "$interpreter" "$@"
