# Local parser verification

## Start and health

Run the parent skill doctor, then `run --feature local-parser`. No parser models, Zotero service or account are needed for this fixture subset. For installed package availability, use `python3 paper-to-zotero/scripts/local_parse.py doctor`; this does not prove inference works.

## Drive and assert

Six tests drive the real CLI with a fake engine executable: successful content and unchanged source bytes; refusal to overwrite existing output; failed conversion with no implicit fallback; explicitly requested fallback with actual engine recorded; image-only Markdown rejected; timeout kills an owned descendant that ignores SIGTERM. Require six passed, none skipped. These tests do not measure OCR or parser quality.

Actual public-file checks are described in `paper-to-zotero/references/local-tools.md` and `docs/local-tools-evaluation.md`. Use new output directories and explicit local files. Basic needs preinstalled ONNX weights. The semantic helper `scripts/evaluate_semantic.py --help` uses six public descriptions and a new isolated database, never the user's library. It requires an explicit cached model directory and installs nothing.

## Evidence and failures

Inspect result.json, CLI exit status, source/Markdown hashes and per-engine stdout/stderr. Conversion success requires readable text, but does not certify correct formulas or tables. `no_readable_text` on a scan means use Basic explicitly; missing local weights mean report the missing prerequisite. Do not enable cloud fallback. Comparison of figures/tables still needs source inspection.

## Cleanup

The fixture runner removes its own temporary profile and peers; check cleanup.json. Local conversion is a bounded subprocess, not a daemon. Retain fresh output and logs as evidence; never remove existing runs, model caches or real Zotero data.
