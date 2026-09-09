#!/usr/bin/env bash
# Enter Git's POSIX environment explicitly, even when launched from Explorer.
set -euo pipefail
export PATH="/usr/bin:/mingw64/bin:$PATH"
if [[ -n "${PAPER2ZOTERO_PDF_BIN:-}" ]]; then
  export PATH="$(/usr/bin/cygpath -u "$PAPER2ZOTERO_PDF_BIN"):$PATH"
fi
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# Native drive paths also work if a caller changes MSYS path conversion settings.
wizard="$(/usr/bin/cygpath -m "$ROOT/literature-to-zotero/scripts/setup-wizard.sh")"
[[ -f "$wizard" ]] || { printf 'Wizard not found: %s\n' "$wizard" >&2; exit 1; }
exec /usr/bin/bash "$wizard" "$@"
