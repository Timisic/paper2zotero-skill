# Acquisition and paper artifacts

`process_run.py` performs this pipeline for a confirmed selection: it walks the acquisition order below, verifies identity, converts consented PDFs, and hands back the papers whose summaries the agent still owes. This document is what it does, and what to run by hand when one paper needs individual attention. The steps are per paper: a failure at any step never stops the others, and a paper keeps every artifact it already has.

## Local PDF entry

Use the following local path after selection, collection and upload permission are explicit. Load this section and the summary contract; acquisition/browser references are only needed if a PDF is missing.

Prepare `candidates.json` using the supplied bibliographic metadata (`id`, `title`, `doi`, year/authors when available), and `pdfs.json` as `[{"id": "doi:...", "pdf": "/absolute/source.pdf"}]`. Relative PDF paths resolve from `pdfs.json`, not the run directory. In the configured environment, start these commands directly:

```bash
python "$SKILL_DIR/scripts/workflow.py" init --run-root <workspace> --slug <label> --intent '<request>'
# Use the returned absolute run_dir in every command below.
python "$SKILL_DIR/scripts/workflow.py" import-candidates --run-dir <run_dir> --file <candidates.json>
python "$SKILL_DIR/scripts/workflow.py" approve-candidates --run-dir <run_dir> --ids '<selected IDs>' --source '<user authorization>'
python "$SKILL_DIR/scripts/workflow.py" consent --run-dir <run_dir> --service mineru --decision approved --source '<upload authorization>'
python "$SKILL_DIR/scripts/workflow.py" import-pdfs --run-dir <run_dir> --file <pdfs.json>
python "$SKILL_DIR/scripts/process_run.py" --run-dir <run_dir> --stages convert --collection-name '<approved collection>' --storage-root <Zotero-data-dir>
```

Record `denied` instead of `approved` if upload was declined. `import-pdfs` copies, verifies and records selected PDFs in one call, keeps rejected/unreadable originals and returns per-paper outcomes. Repeating it preserves an existing matching PDF and later artifacts; a different file is reported rather than replacing it. There is no need to choose paper directory names or assemble per-file copy/verify/record commands.

After conversion, follow `pending_summaries` and its summary contract, then execute `resume_command`. At delivery, `ingest.papers` already contains cloud/local verification and attachment reuse evidence.

## Acquisition order

`scripts/acquire.py` chooses the route; `process_run.py` runs it for every approved candidate. You do not sequence this by hand — this is what it does, so you can read a trail.

1. **The links already in hand.** Every open PDF URL discovery recorded, fetched directly over HTTPS, published versions before preprints. Most open-access papers end here in a couple of seconds, and nothing else runs: no DOI resolution, no browser.
2. **Links worth asking for**, only when step 1 produced no verified file: Unpaywall, then OpenAlex, then Semantic Scholar, then Crossref, trying each fresh PDF link before asking the next source; then arXiv for a preprint. A returned URL is a lead, not success. Known PMCIDs also use the official PMC cloud file metadata (not the PMC web viewer). `doi.org` itself is unreachable on some networks, so the DOI is resolved from metadata rather than by redirect.
3. **One browser attempt** (`browser_pdf.py`), only when HTTP has failed, using the best publisher route. If it cannot acquire the paper, return a `browser_handoff` for the agent to inspect the current session and use MyLOFT. A browser channel error pauses further automatic browser attempts in this batch.
4. A failed automatic attempt remains pending while the agent handles the handoff below. If no route remains, record `metadata_only` explicitly with `workflow.py record-paper --state metadata_only`; a timeout alone does not prove there is no full text.

**The browser is a fallback, not the front door.** Kimi being disconnected removes step 3 only: papers acquirable over HTTP still finish, and only the papers that needed the browser report the missing channel. Nothing about identity verification, hashing or recovery changes with the route.

**Every attempt is written to `papers/<id>/acquisition.json`** — channel, redacted URL, the source that suggested the link, the version it claims to be, bytes and SHA-256, the verification verdict, and which wall stopped it (`entitlement`, `challenge`, `reachability`, `rate_limited`, `not_a_pdf`, `too_large`, `identity_mismatch`, `browser_unavailable`). `browser_unavailable` means *our* channel broke, not that the host is unreachable — do not send the user to a mirror for it.

Bounds are per paper: a size cap, a per-link timeout, one try per network route before moving to the next link, a ceiling on how many links are worth trying, and a separate short ceiling on the lookup detour. A source that is down costs seconds, not a run.

**Preprint versus version of record.** arXiv preprints can differ from the published version (revisions, added appendices, peer-review fixes). Keep them distinct: the recorded `version` says which file this is, and a preprint never becomes the version of record by default. DOI stays the primary work identity; the arXiv id is recorded as an additional identifier. A title-only arXiv match is a *lead*: it is followed only when an author surname and a plausible year agree, and an uncorroborated lead is recorded and dropped rather than downloaded.

**Google Scholar is a hint, not a download source.** Scholar has no stable API and the files it points at live on arbitrary hosts. Do not download from Scholar itself. When Scholar is needed, open the search in the borrowed authenticated tab, use it only to discover where an open copy actually lives (author page, university or institutional repository, arXiv), then download from that host and run identity verification. If only Scholar itself or an unverifiable host has the file, treat the paper as `metadata_only`.

## MyLOFT handoff

Read this branch when `acquire.browser_handoff` is returned, or the user explicitly asks to use a subscribed database. Read the installed `$kimi-webbridge` skill for its tool protocol. The browser is allowed to be agent-driven: use visible page evidence to choose the institution/database link and perform necessary clicks. The scripts handle transfers and identity checks; they do not replace your judgement about an authentication page.

**One owner, one session.** Wait until the processing command has exited before operating its browser. Use the `session` returned by the handoff for every Kimi call and helper. Inspect `list_tabs` first. A page-read error is not a missing tab. When a tab already exists, navigate in it; bootstrap opens one HTML page at most, and failed adoption means inspect/adopt that page with `find_tab`, not reopen it or create a new session. Preserve the user's other tabs.

1. **Inspect the actual state.** Use `list_tabs` (keep signed URLs private), then `snapshot` or `browser_pdf.py --session <session> state`. Compare the actual host with the requested publisher. An unchanged URL is a navigation failure; a visible login, purchase button, or institution selector is an access question. Do not infer a lost MyLOFT login from several unrelated errors.
2. **Establish entitlement when needed.** In that same session open `https://app.myloft.xyz/browse/home`, inspect the displayed institution and eResources/database list, and follow the matching publisher/database entry. Use the real portal link; do not invent proxy URL templates. MyLOFT may authorize ordinary publisher URLs through its extension, and some publishers additionally require the portal's SSO redirect. Reuse an already authenticated publisher session. Login/MFA/CAPTCHA requiring the account holder is one concise human action, while the other papers continue. Record this as `partial` with `--warning "authentication_required: <observed login step>"`; `metadata_only` would skip acquisition on resume, so it is inappropriate while awaiting login.
3. **Return to this paper.** Use a publisher URL from the handoff or from the observed database page. Open the paper once after the portal handshake. Follow its actual PDF link or use the capture helper below. If an authentication link opens another tab, adopt that exact observed tab into the same session; do not fight the login redirect by repeatedly reopening the original page.
4. **Capture and record.** Once the actual PDF is visible, `capture --current` reads its bytes without navigating again or putting a signed URL on the command line. For a landing page, `capture --url` follows its article PDF. Always give the expected title and DOI; preserve version provenance from the source. Run the verifier and record only a verified file as `pdf_acquired`.
5. **Stop on evidence.** Allow one retry after a concrete state change (completed portal login, cleared challenge, adopted the correct tab). If the same failure returns, leave a precise pending reason or `metadata_only`; do not restart the whole batch to try the same publisher again. Continue ingestion/conversion of existing files with `process_run.py --stages convert,ingest` so a missing paper does not trigger a fresh acquisition pass.

```bash
# Already at the authenticated PDF; no navigation and no signed URL in argv.
python "$SKILL_DIR/scripts/browser_pdf.py" --session <run-session> \
  capture --current --output <paper-dir>/source.pdf --doi '<doi>' --title '<title>'

# A known publisher landing page, after entitlement is established.
python "$SKILL_DIR/scripts/browser_pdf.py" --session <run-session> \
  capture --url '<publisher-url>' --output <paper-dir>/source.pdf --doi '<doi>' --title '<title>'

python "$SKILL_DIR/scripts/paper_artifacts.py" verify \
  --pdf <paper-dir>/source.pdf --doi '<doi>' --title '<title>'
python "$SKILL_DIR/scripts/workflow.py" record-paper --run-dir <run_dir> \
  --id '<candidate-id>' --state pdf_acquired --artifact pdf=<paper-dir>/source.pdf
```

Save a short handoff note in the run: publisher, observed access state, the portal/database used, action taken, final verification, elapsed time. Do not save cookies or signed query parameters. `save_as_pdf` is a webpage printout and cannot replace the source PDF. A download triggered through the observed publisher interface can be used after the same identity verification; it need not have come through a fixed script.

`browser_error` means the adapter/session broke; `challenge_unsolved` means the challenge still needs a click; `blocked` means the current page offered no obtainable PDF, not proof that the library has no subscription; `wrong_document` means the bytes belong to another paper. Read `detail` before choosing the next action.

The public acquisition path uses plain APIs. `browser_pdf.py get/resolve` remain explicit diagnostic tools for a metadata host that HTTP cannot reach; they are not an automatic search fallback.

The transferable idea of capturing PDF response bytes from an authenticated browser came from the MIT-licensed [paper-scraper](https://github.com/GAO-pooh/paper-scraper); no code is vendored. PMC file discovery follows the [official cloud dataset](https://pmc.ncbi.nlm.nih.gov/tools/pmcaws/), updated August 2026. PMC web availability does not imply that its distributed dataset includes a PDF.

## Verification

```bash
python "$SKILL_DIR/scripts/paper_artifacts.py" verify \
  --pdf <downloaded.pdf> --title '<candidate title>' --doi '<doi>'
```

The verifier has three outcomes, and the difference between the last two matters:

- `verified` (exit 0) — the text names this paper's DOI or title. Preserve its SHA-256.
- `rejected` (exit 2) — not a PDF, or readable text that names a *different* paper. Do not keep it as a source PDF.
- `unverified` (exit 3) — no readable text could be extracted, so identity is unknown. **Keep the file** and flag it for human inspection; "could not read" is not evidence against the download.

Text extraction prefers `pdftotext` (poppler) and falls back to a built-in stdlib reader, so verification works on a machine with no extra tools installed. The built-in reader cannot decode PDFs whose fonts use custom CID encodings (Elsevier's typically do) — those come back `unverified` until poppler is installed. Installing it is the single cheapest way to raise the automatic-verification rate:

```bash
brew install poppler          # macOS
sudo apt install poppler-utils # Debian/Ubuntu
choco install poppler          # Windows
```

## Markdown

Use only identity-verified selected PDFs and recorded MinerU consent (see [workflow.md](workflow.md)). Credentials are resolved by `credentials.py` across supported runtimes.

```bash
python "$SKILL_DIR/scripts/mineru_parse.py" --run-dir <run_dir> --pdf <source.pdf>
```

Repeat `--pdf` for a batch. Default output is `<PDF parent>/mineru/<source-and-config-id>/paper.md` with extracted image assets. `--output <root>` instead groups outputs by data ID under that root. The checkpoint binds source hashes and converter settings; repeat the same command to resume a submitted batch. Read [recovery.md](recovery.md) after interrupted upload, polling or download. Standalone conversion needs `--consent-source '<explicit approval reference>'`.

MinerU (`vlm`) is the only converter. Without consent or a token, record `markdown_unavailable` as a warning and retain the PDF. A readable PDF can still support a summary labeled `source_basis=pdf`. Conversion failure does not invalidate PDF acquisition or prevent PDF ingestion. To deliver PDFs before a slow conversion, use `process_run.py --stages ingest`; the Markdown attaches to the same parent whenever it arrives. OCR is a MinerU option for scanned input.

## Full-text reading note

The current agent writes the note from verified full text; `summary_artifact.py` persists it with provenance. No separate summary model or API key is required.

When `process_run.py` returns `pending_summaries`, read [paper-summary.md](paper-summary.md) for the version-3 concise-summary contract and save/continue commands. Each handoff supplies the source, source basis, output path and instructions. The default is about 1,000 Chinese characters: question/design, main findings, a key limitation and one or two useful insights, with one draft/self-check.

A readable PDF can support the note when conversion fails, with `source_basis=pdf`. Missing or unreadable full text leaves the note missing; a source abstract cannot substitute. The normal workflow includes the agent's own factual and interpretive self-check before ingestion, without an extra user gate.
