# Discovery and screening

The goal is a list of papers worth reading, fast. Coverage may be incomplete; the user can ask to widen it. Say what the list does not cover instead of buying completeness with time.

## Query construction

Build controlled concept groups for focal construct, population, context, outcome, method or study design, verified synonyms and abbreviations, and exclusions.

Prefer terminology found in user context and seed papers. Treat model-generated terminology as provisional until a pilot query returns coherent results. A synonym stays inside the recorded scope; a new research direction is a new request, and materially changed scope is re-recorded with `workflow.py record-scope` and mentioned to the user.

## Rounds and the stopping rule

- OpenAlex and Semantic Scholar answer the same round through one command (`discovery.py`), and their results are merged and deduplicated before you see them. One initial round may contain a few controlled queries; do not dress each query up as its own supplementary round.
- **At most one supplementary round by default**, and only when reliable candidates are clearly too few or missing information genuinely blocks a relevance judgement. Choose one existing source with a specific job — do not chain every provider.
- Network retries and the configured direct/proxy switch are not supplementary rounds, but they spend the same run-level time budget. An outer layer never resets an inner one.
- Stop and show the list when reliable candidates suffice, when the supplementary budget is spent, or when the run's time budget (~5 minutes, `workflow.py status` reports it) is reached. At the boundary, finish the bounded request already in flight and return results with a coverage note — do not start another round.

Not done by default: citation-network expansion, per-candidate metadata backfill for everything, preprint-then-published double searches, or forcing candidates into `core`/`expansion` buckets.

```bash
python "$SKILL_DIR/scripts/discovery.py" \
  --query '<English query>' \
  --from-year <year> --to-year <year> \
  --sources openalex,semantic_scholar \
  --run-dir <run_dir> \
  --output <run_dir>/candidates-round1.json

# only when the initial round is genuinely thin
python "$SKILL_DIR/scripts/discovery.py" --round supplementary \
  --reason 'only 4 reliable candidates after screening' \
  --output <run_dir>/candidates-round2.json ...
```

Give each round its own `--output`, then screen across the files and import the
chosen candidates once with `workflow.py import-candidates`. A round writes its
file only when at least one source answered — a round nobody answered writes
nothing and exits non-zero, so a dead network can never replace a list you
already have with an empty one.

`discover_openalex.py` is the same command restricted to OpenAlex, kept because older runs and scripts call it by name.

The round reports one `status`: `ok` (every source answered), `partial` (some answered, some failed — deliver what came back and say who is missing), or `failed` (nobody answered, so the round says nothing about the literature at all).

Read the `sources` array in the result before presenting anything. Each source reports `ok`, `empty`, `rate_limited`, `authentication_required`, `not_configured`, `skipped` or `unavailable`, and only `empty` is a statement about the literature. A round with `partial: true` delivered one source and lost another: say which, rather than presenting a narrower list as the whole picture.

The command records its round, reason and elapsed time in the run and refuses a second supplementary round unless the user asked to widen coverage (`--user-requested`). A supplementary round requires `--run-dir`: the ceiling lives in the run's ledger, so a top-up outside a run would be unbounded and unlogged.

## Provider roles

- OpenAlex: default discovery source and one citation-count observer. Needs no credential.
- Semantic Scholar: second discovery source and identifier backfill (arXiv, PubMed, Corpus ID). Its key is one request per second across *every* endpoint; without the key the source reports `not_configured` and the round continues without it.
- Crossref: DOI metadata and the publisher's registered full-text links. A contact address (`CROSSREF_MAILTO`) buys the polite pool.
- Unpaywall: open copies of a known DOI. Requires `UNPAYWALL_EMAIL`.
- arXiv: the open version of a preprinted paper, at one request per three seconds.
- OpenCitations: citation relationships, when they are actually needed.
- PubMed: biomedical, clinical, or neuroscience slices only.

Crossref, Unpaywall and arXiv answer questions about a *known* paper during acquisition. They are not parallel search engines: adding them to a topical round would widen retrieval without widening relevance.

Every source shares one request policy in `scripts/http_client.py`. Pacing is enforced per API key across processes, so two commands running at once cannot together break a limit; retries queue in the same line. A key is sent only to its own source's host and is dropped again if a redirect leaves it.

When a metadata API is unavailable, return that source's status within the shared budget and deliver the other source's candidates. Discovery never opens a browser automatically. A browser metadata probe is an explicit diagnostic action only, using the existing task session; it must not silently extend an ordinary search round. For queries, prefer a short phrase combining the intervention and study design (for example `conversational agent randomized controlled trial depression anxiety`) over concatenating every synonym into one request. Use the single supplementary round to correct a demonstrated coverage gap, not to multiply variations.

API keys belong in `~/.config/literature-to-zotero/env` or the environment (`scripts/credentials.py` resolves both), never in recorded command lines. `setup.py` reports which sources are configured without printing any value.

## Screening

Use DOI as candidate ID, the source's own ID second, and normalized title plus year last. `discovery.py` has already merged duplicates: a normalized DOI is decisive, and without one a merge additionally requires the same normalized title, the same year and the same first-author surname, because a wrong merge silently destroys a candidate while a missed merge only shows one extra row.

Read what the merge recorded rather than assuming a single truth:

- `sources` — every service that returned this paper.
- `citations` — one dated observation per source. They routinely disagree; a single number is never "the" citation count, and a missing one is unknown, not zero.
- `abstract_source` — which service wrote the abstract you are reading.
- `conflicts` — where two sources disagree about title, year, venue or an identifier. The first value was kept and nothing was overwritten; a conflict that matters is worth a word to the user.
- `versions` — a preprint and a version of record are related, never collapsed. An arXiv DOI (`10.48550/arXiv.*`) *is* the preprint's own DOI and proves no published version exists.

Prefer a published version over its preprint and keep the relationship.

Read title and source abstract for every presented candidate. Keep these fields distinct:

- `abstract`: source text or `null`;
- `hit_reason`: one agent-generated sentence — required, and the reason the paper is on this list;
- `candidate_set`: optional (`core` / `expansion`), only when that split helps this user.

The merged file is in retrieval order, not relevance order: it is whatever OpenAlex returned followed by what Semantic Scholar added. Two services rank by different internal scores that are not comparable to each other, so neither position in that file nor a citation count is a relevance judgement. Rank by direct relevance, research-design and evidence fit, complementarity, recency, then sourced citation count. Screen mainly on title and source abstract. Where missing metadata weakens the judgement, mark the row as thin evidence — never invent a study design or finding, and never launch an unbounded backfill to make the table look full.

Apply the requested study type before filling the table. If the request asks for empirical intervention studies, a review or model-only benchmark cannot substitute for one; list fewer papers rather than filling the remaining rows. Keep already-known download papers separate from a discovery list unless they independently pass that screening. Default to peer-reviewed journal articles, formal conference papers, and high-quality reviews when the request does not narrow the study type. Mark preprints. "Prefer top venues" ranks; only an explicit "only these venues" filters. Keep the user's language scope — do not silently narrow to English. Exclude books, dissertations, editorials, news, and non-academic pages unless the user included them.

Present 10–15 rows by default. Six qualifying papers means six rows plus a coverage note; a longer list needs an explicit user request (`candidate_table.py --max-rows`). Keep IDs stable so a rule like "citation top ten" resolves against this snapshot.

Retractions and major corrections stay outside the normal list. Present them only in a separately warned lane when their status is relevant.
