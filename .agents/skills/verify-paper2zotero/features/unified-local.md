# Unified local workflow

This branch does not ship `zotero_local.py`, `local_parse.py`, or `tests/test_unified_local.py`. Doctor does not require those scripts. Their absence is not a doctor failure. `run --feature unified-local` reports that absence and does not collect tests. Do not invent those modules or treat this note as a drive recipe.

`scripts/verify.py zotero-local` is a different check. It probes the Zotero Desktop API on 127.0.0.1:23119 through `capability.py`. It is not the missing `zotero_local.py` module.
