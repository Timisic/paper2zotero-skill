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
if [[ -n "${PAPER2ZOTERO_STARTUP_FILE:-}" ]]; then
  [[ -t 0 && -t 1 ]] || { echo 'An interactive terminal is required.' >&2; exit 1; }
  /usr/bin/bash -n "$wizard"
  printf 'ready\n' > "$(/usr/bin/cygpath -m "$PAPER2ZOTERO_STARTUP_FILE")"
  unset PAPER2ZOTERO_STARTUP_FILE
fi
exec /usr/bin/bash "$wizard" "$@"
