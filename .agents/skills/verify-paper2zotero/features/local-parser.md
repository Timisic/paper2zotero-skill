# Local parser verification

This branch does not ship `paper-to-zotero/scripts/local_parse.py` or `tests/test_local_parse.py`. Doctor does not require `local_parse.py`. A missing file is not a doctor failure. `run --feature local-parser` reports that absence and does not collect tests. Do not invent a parser CLI or treat this note as a drive recipe.
