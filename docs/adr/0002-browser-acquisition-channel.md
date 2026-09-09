# ADR-0002: PDF acquisition goes through the user's browser as a transport

Status: Accepted for browser transport; routing precedence superseded by [ADR-0004](0004-http-first-discovery-and-acquisition.md)

Date: continuation session after `6abf762`

## Context

An end-to-end run left three of thirteen selected papers at `metadata_only`,
each blocked for a different reason that the workflow reported identically as
"could not download": a ScienceDirect article behind a Cloudflare challenge, a
SAGE article on a host this network cannot open at all, and a JMIR article
whose OA mirror was rate-limiting. The acquisition instructions told the agent
to set Chrome's download behaviour over CDP and click a download button —
which does not work in this runtime (`Browser.setDownloadBehavior` is
unavailable in the user's Arc, and programmatic download clicks stop firing
after about two), so every run improvised the same fragile in-page
`fetch` → base64 dance by hand, including a race bug.

The owner asked whether to integrate `paper-scraper` (MIT; ScienceDirect and
INFORMS scrapers that capture PDF bytes over Chrome CDP from a logged-in
browser). Vendoring it whole was not advisable: it is search-driven with no
per-DOI mode, reads Chrome cookies while the owner's session lives in Arc,
covers two platforms, and duplicates this skill's browser channel. The idea
inside it, however, is the right one.

Measured this session, all of it live:

- The owner's MyLOFT grants entitlement through its browser extension plus
  Shibboleth SSO, *not* by rewriting URLs. Plain publisher URLs are therefore
  the correct acquisition targets across every subscribed platform.
- The browser reaches Crossref, OpenAlex and Semantic Scholar, which the shell
  on this machine cannot; `doi.org` is unreachable from both.
- ScienceDirect answers a plain `fetch` of its PDF endpoint with a challenge
  page regardless of authentication, and answers a navigation with a Cloudflare
  Turnstile checkbox — whose widget lives in a *closed* shadow root and which
  ignores synthetic clicks.

## Decision

- New deep module `scripts/browser_pdf.py`: the browser is a **transport**,
  not a UI to automate. One loop — navigate, classify, act, repeat — where
  `classify_page` reduces any page to one of `pdf`, `challenge`, `landing`,
  `blocked`, `error`, and every branch is a pure function that is tested
  without a browser (`pdf_links` ranking, `publisher_pdf_urls`,
  `challenge_point`, `decode_capture`).
- Bytes are captured by an in-page `fetch` that also computes SHA-256; the
  hash and byte count are re-checked on reassembly, so a truncated chunk
  transfer fails loudly instead of writing a broken PDF.
- Anti-bot challenges are cleared with a **trusted** CDP mouse click at the
  checkbox, located through the Turnstile response `<input>`'s positioned
  ancestor. When that does not clear it, the result is `challenge_unsolved`
  and one human click — never a silent failure or a fake artifact.
- Platform coverage comes from generic rules, not a scraper per publisher:
  `citation_pdf_url` first (every Scholar-indexed publisher emits it), then a
  short table of URL conventions (the Atypon `/doi/pdf/<doi>` shape covers
  SAGE, Taylor & Francis, ACM, ACS, Science, PNAS at once), then same-origin
  anchors. Cross-origin anchors rank last because on an article page they are
  the reference list.
- `discover_openalex.py` retries bounded and then falls back to the same
  browser channel, so a blocked metadata host cannot silently become an empty
  candidate set.
- `paper-scraper` is credited in `references/acquisition-and-artifacts.md` and
  in the module docstring. No code is vendored (option C of the three that
  were offered).

## Consequences

- One command acquires a source PDF from any platform the user's browser can
  reach and is entitled to, instead of per-publisher scrapers. Verified live
  on six: Elsevier/ScienceDirect (open access *and* subscribed), JMIR,
  Springer, APA PsycNet, Cambridge Core.
- The three acquisition walls stay distinguishable in the record, so the
  remediation is right: `blocked` sends the user to MyLOFT, `error` to a
  mirror, `challenge_unsolved` to one click.
- A host the browser cannot open (SAGE, on this network) stays unacquirable.
  That is reported as `error`, not worked around.
- The skill now depends on the Kimi WebBridge daemon for discovery fallback as
  well as acquisition. Discovery still prefers the shell and only falls back.
- Arc hangs when asked to create a session's first tab, so the first tab is
  opened through the OS and adopted with `find_tab`. That bootstrap is
  macOS-shaped, like the rest of the skill's environment assumptions.
