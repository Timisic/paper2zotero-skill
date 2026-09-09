#!/usr/bin/env python3
"""Acquire bytes through the user's own logged-in browser (Kimi WebBridge).

Publisher PDFs are guarded by three different walls, and only the user's real
browser gets past all three at once: **entitlement** (institutional session —
MyLOFT/Shibboleth SSO cookies), **anti-bot** (Cloudflare Turnstile and
publisher challenge pages), and **reachability** (hosts a shell `urllib` call
cannot open but the browser's network stack can).

So this module treats the browser as a *transport*, not as a UI to click
around in. One loop drives it:

    navigate → read page state → classify → act → repeat → capture bytes

`classify_page` names what the tab is showing (`pdf`, `challenge`, `landing`,
`blocked`, `error`) and the caller acts on that name: solve a challenge with a
**trusted** CDP mouse click (a synthetic `el.click()` has `isTrusted=false`
and Turnstile ignores it), follow the landing page's own PDF link, or give up
with a recorded reason. Bytes come back through an in-page `fetch()` that is
base64-chunked over the daemon's JSON channel, with a SHA-256 computed in the
page and re-checked here so a truncated transfer can never look like success.

The blocked cases are reported, never faked: `challenge_unsolved` means a
human must click the checkbox in the visible tab; `blocked` means no lawful
copy was reachable from this session. Callers record those and move on.

Commands (each prints one JSON line):
  resolve  --doi DOI                 DOI → the URLs worth trying (no doi.org)
  capture  --url URL --output FILE   walk the ladder and write verified bytes
  locate   --url URL                 report the PDF URLs a landing page offers
  get      --url URL                 fetch text/JSON through the browser
  state    [--url URL]               classify what the tab currently shows

Attribution: the "capture the bytes at the network layer from an already
authenticated browser" idea is the transferable primitive of the MIT-licensed
paper-scraper project (https://github.com/GAO-pooh/paper-scraper), which does
it for ScienceDirect and INFORMS via Chrome CDP. Nothing is vendored; this is
an independent implementation over the skill's own browser channel.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import re
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Mapping, Sequence

sys.path.insert(0, str(Path(__file__).resolve().parent))
import paper_artifacts  # noqa: E402

DAEMON = "http://127.0.0.1:10086/command"
# Any reachable https page works as a JS realm for `get`; Crossref is the one
# metadata host this skill already depends on.
DEFAULT_ORIGIN = "https://api.crossref.org/"
CHUNK_CHARS = 400_000
CAPTCHA_HOSTS = ("challenges.cloudflare.com", "hcaptcha.com", "recaptcha.net", "google.com/recaptcha")
CHALLENGE_TEXT = re.compile(
    r"are you a robot|verify you are (a )?human|checking your browser|just a moment"
    r"|请稍候|請稍候|验证您是人类|驗證您是人類|人机验证|人機驗證",
    re.I,
)
# Publisher PDF URL shapes, matched against an anchor href. Ordered by how
# reliably the shape means "the full text of *this* article".
PDF_HREF = re.compile(
    r"(/doi/(pdf|pdfdirect|epdf)/|/content/pdf/|pdfft\?|/pdf(\?|$)|\.pdf($|\?)|/articles?/[^/]+\.pdf)",
    re.I,
)


class BrowserError(RuntimeError):
    """The daemon, the extension, or the page refused to do what we asked."""


# ── Daemon channel ─────────────────────────────────────────────────────────

def command(action: str, args: Mapping[str, Any], session: str, timeout: int = 180) -> Any:
    """One Kimi WebBridge call. Never goes through the user's HTTP proxy."""
    body = json.dumps({"action": action, "args": args, "session": session}).encode()
    request = urllib.request.Request(DAEMON, data=body, headers={"Content-Type": "application/json"})
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(request, timeout=timeout) as response:
            payload = json.load(response)
    except urllib.error.HTTPError as exc:
        # The daemon answered and refused — usually "this session has no tab
        # yet". Its own message is far more useful than a generic failure.
        detail = exc.read().decode("utf-8", "replace")[:400] or f"HTTP {exc.code}"
        raise BrowserError(f"{action} refused: {detail}") from exc
    except (urllib.error.URLError, TimeoutError) as exc:
        raise BrowserError(
            f"Kimi WebBridge daemon unreachable at {DAEMON} ({type(exc).__name__}); "
            "start it with ~/.kimi-webbridge/bin/kimi-webbridge start"
        ) from exc
    if not payload.get("ok"):
        raise BrowserError(str((payload.get("error") or {}).get("message") or payload))
    return payload.get("data")


def evaluate(code: str, session: str, timeout: int = 180) -> Any:
    """Run JS in the current tab; the snippet must return a JSON string."""
    data = command("evaluate", {"code": code}, session, timeout)
    value = data.get("value") if isinstance(data, dict) else data
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return value
    return value


def trusted_click(x: float, y: float, session: str) -> None:
    """A real mouse click at viewport CSS coordinates.

    Goes through CDP `Input.dispatchMouseEvent`, so the page sees
    `isTrusted=true` — the difference between solving a Turnstile checkbox and
    being ignored by it.
    """
    point = {"x": round(x), "y": round(y)}
    command("cdp", {"method": "Input.dispatchMouseEvent", "params": {"type": "mouseMoved", **point}}, session)
    for kind in ("mousePressed", "mouseReleased"):
        command(
            "cdp",
            {"method": "Input.dispatchMouseEvent", "params": {"type": kind, "button": "left", "clickCount": 1, **point}},
            session,
        )


# ── In-page programs ───────────────────────────────────────────────────────

PROBE_JS = r"""
(() => {
  const captchaHosts = %s;
  const frames = [...document.querySelectorAll('iframe')]
    .map(f => ({ src: f.src || '', r: f.getBoundingClientRect() }))
    .filter(x => captchaHosts.some(h => x.src.includes(h)) && x.r.width > 20 && x.r.height > 20)
    .map(x => ({ src: x.src.slice(0, 80), x: x.r.x, y: x.r.y, w: x.r.width, h: x.r.height }));
  // Turnstile draws its checkbox inside a *closed* shadow root, so the widget
  // is invisible to querySelectorAll even while it is plainly on screen. Its
  // response <input> is not: locate the widget through that instead.
  for (const input of document.querySelectorAll(
      'input[name="cf-turnstile-response"],input[name="g-recaptcha-response"],input[name="h-captcha-response"]')) {
    let host = input.parentElement;
    while (host && (host.getBoundingClientRect().width < 40 || host.getBoundingClientRect().height < 20)) {
      host = host.parentElement;
    }
    if (!host) continue;
    const r = host.getBoundingClientRect();
    if (r.width > 40 && r.height > 20) {
      frames.push({ src: 'closed-shadow:' + input.name, x: r.x, y: r.y, w: r.width, h: r.height });
    }
  }
  const meta = document.querySelector('meta[name="citation_pdf_url"]');
  const links = [...document.querySelectorAll('a[href]')]
    .map(a => a.href)
    .filter(h => h.startsWith('http'));
  return JSON.stringify({
    url: location.href,
    title: document.title,
    content_type: document.contentType,
    ready: document.readyState,
    text: (document.body ? document.body.innerText : '').slice(0, 1200),
    citation_pdf_url: meta ? meta.content : null,
    links: links.slice(0, 800),
    captcha: frames
  });
})()
"""

CAPTURE_JS = r"""
(async () => {
  try {
    const response = await fetch(location.href, { credentials: 'include' });
    const buffer = await response.arrayBuffer();
    const bytes = new Uint8Array(buffer);
    let binary = '';
    for (let i = 0; i < bytes.length; i += 0x8000) {
      binary += String.fromCharCode.apply(null, bytes.subarray(i, i + 0x8000));
    }
    window.__ltzCapture = btoa(binary);
    const digest = await crypto.subtle.digest('SHA-256', buffer);
    return JSON.stringify({
      ok: true,
      url: location.href,
      status: response.status,
      content_type: response.headers.get('content-type'),
      bytes: bytes.length,
      b64_length: window.__ltzCapture.length,
      sha256: [...new Uint8Array(digest)].map(b => b.toString(16).padStart(2, '0')).join('')
    });
  } catch (error) {
    return JSON.stringify({ ok: false, error: String(error).slice(0, 200) });
  }
})()
"""


def _probe_js() -> str:
    return PROBE_JS % json.dumps(list(CAPTCHA_HOSTS))


# ── Pure judgements ────────────────────────────────────────────────────────

def classify_page(state: Mapping[str, Any]) -> str:
    """Name what the tab is showing. Pure; the whole ladder branches on this.

    `pdf` the response is the file itself · `challenge` an anti-bot wall ·
    `landing` an article page that offers a PDF link · `blocked` a readable
    page with no reachable full text · `error` the browser never got a page.
    """
    url = str(state.get("url") or "")
    if not url or url.startswith(("chrome-error:", "about:", "chrome:")):
        return "error"
    if str(state.get("content_type") or "").lower().startswith("application/pdf"):
        return "pdf"
    # An interstitial is served with an empty body and its message only in the
    # <title> ("Just a moment…" / "請稍候…"), so a body-only check reads it as
    # an ordinary page and the walk gives up on a URL that was about to work.
    text = str(state.get("text") or "") + "\n" + str(state.get("title") or "")
    if state.get("captcha") or CHALLENGE_TEXT.search(text) or "/craft/challenge/" in url:
        return "challenge"
    if pdf_links(state):
        return "landing"
    return "blocked"


def pdf_links(state: Mapping[str, Any]) -> list[str]:
    """Ordered PDF URLs this page offers, best first.

    Ranking is the whole point. A publisher article page links to dozens of
    PDFs and all but one of them belong to *other* papers — the reference
    list. Ordered by how strongly a URL means "the full text of this article":

    1. `citation_pdf_url` — the meta tag publishers emit for Google Scholar.
       The most portable cross-platform signal, and always about this article.
    2. `publisher_pdf_urls` — the URL the platform's own convention implies.
       Needed whenever the download button is JS-driven and never appears as
       an anchor (JMIR, most Atypon platforms).
    3. Same-origin anchors under the landing page's own path.
    4. Any other same-origin anchor.
    5. Cross-origin anchors, last: on an article page these are almost always
       cited papers hosted elsewhere.
    """
    landing = str(state.get("url") or "")
    ranked: list[str] = []
    citation = state.get("citation_pdf_url")
    if isinstance(citation, str) and citation.startswith("http"):
        ranked.append(citation)
    ranked.extend(publisher_pdf_urls(landing))
    anchors = [href for href in (state.get("links") or []) if isinstance(href, str) and PDF_HREF.search(href)]
    host = urllib.parse.urlparse(landing).netloc
    prefix = landing.split("?")[0].rstrip("/")
    ranked.extend(h for h in anchors if h.startswith(prefix))
    ranked.extend(h for h in anchors if urllib.parse.urlparse(h).netloc == host)
    ranked.extend(anchors)
    seen: set[str] = set()
    unique: list[str] = []
    for href in ranked:
        if href not in seen:
            seen.add(href)
            unique.append(href)
    return unique


# Landing-URL → PDF-URL conventions, tried when the page offers no usable
# anchor. `Atypon` hosts (SAGE, Wiley, Taylor & Francis, ACM, ACS, Science,
# PNAS, …) share one `/doi/<doi>` → `/doi/pdf/<doi>` shape, which is why this
# table stays short while covering most subscribed platforms.
ATYPON_HOSTS = (
    "journals.sagepub.com",
    "www.tandfonline.com",
    "dl.acm.org",
    "pubs.acs.org",
    "www.science.org",
    "www.pnas.org",
    "royalsocietypublishing.org",
    "www.emerald.com",
    "journals.plos.org",
)


# What marks the start of an institutional proxy's own domain. EZproxy and
# its relatives are how most universities outside this skill's origin grant
# access, and they *rewrite the hostname*. `PROXY_LABELS` match one dot-
# separated label; `PROXY_DOMAINS` match a whole trailing domain.
PROXY_LABELS = ("ezproxy", "ezp", "libproxy", "openathens", "eresources", "remotexs", "proxy")
PROXY_DOMAINS = ("idm.oclc.org", "oclc.org")


def unproxied_host(url: str) -> str:
    """The publisher's own hostname behind an institutional proxy. Pure.

    EZproxy serves `sciencedirect.com` as
    `www-sciencedirect-com.ezproxy.lib.example.edu` (dots become dashes, and a
    real dash is doubled), or sometimes as a plain suffix append. Matching a
    platform convention against the rewritten name never succeeds, so the
    identity used for matching is the un-rewritten host — while the URLs we
    actually emit stay on the live host, which is the only one that serves
    the file.
    """
    netloc = urllib.parse.urlparse(url).netloc.split("@")[-1].split(":")[0].lower()
    labels = netloc.split(".")
    # Start at 1: the publisher needs at least one label of its own in front,
    # so a proxy marker in the very first label is part of the real host.
    for index in range(1, len(labels)):
        remainder = ".".join(labels[index:])
        is_proxy = any(marker in labels[index] for marker in PROXY_LABELS) or remainder.endswith(PROXY_DOMAINS)
        if not is_proxy:
            continue
        prefix = labels[:index]
        if len(prefix) == 1 and "-" in prefix[0]:
            # EZproxy's dash form; a literal dash in the real host is doubled.
            return prefix[0].replace("--", "\x00").replace("-", ".").replace("\x00", "-")
        return ".".join(prefix)
    return netloc


def publisher_pdf_urls(landing: str) -> list[str]:
    """PDF URLs implied by a platform's own URL convention. Pure."""
    parsed = urllib.parse.urlparse(landing)
    path = parsed.path.rstrip("/")
    # Already at a PDF endpoint: proposing the convention again just appends
    # another suffix, and the walk chases /pdf/pdf/pdf until its rounds run
    # out. If this URL did not serve a PDF, adding to it will not either.
    if re.search(r"(/(pdf|epdf|pdfdirect)|\.pdf)$", path, re.I):
        return []
    host = unproxied_host(landing)
    base = f"{parsed.scheme}://{parsed.netloc}"
    # Platforms carry the DOI in the path under different prefixes
    # (`/doi/`, `/doi/abs/`, `/article/`), so take it wherever it appears.
    match = re.search(r"(10\.\d{4,9}/[^?#]+)", path)
    doi = match.group(1) if match else ""
    if host.endswith(".jmir.org") and re.search(r"/\d{4}/\d+/e\d+$", path):
        return [f"{base}{path}/PDF"]
    if host.endswith("onlinelibrary.wiley.com") and doi:
        return [f"{base}/doi/pdfdirect/{doi}", f"{base}/doi/pdf/{doi}"]
    if host in ATYPON_HOSTS and doi:
        return [f"{base}/doi/pdf/{doi}"]
    if host.endswith("link.springer.com") and doi:
        return [f"{base}/content/pdf/{doi}.pdf"]
    if host.endswith("www.nature.com") and re.search(r"/articles/[^/]+$", path):
        return [f"{base}{path}.pdf"]
    if host.endswith("www.mdpi.com"):
        return [f"{base}{path}/pdf"]
    if host.endswith("www.frontiersin.org"):
        return [f"{base}{re.sub(r'/full$', '', path)}/pdf"]
    if host.endswith("ncbi.nlm.nih.gov") and "/articles/PMC" in path:
        return [f"{base}{path}/pdf/"]
    return []


def walk_candidates(state: Mapping[str, Any]) -> list[str]:
    """The subset of `pdf_links` that is safe to follow automatically. Pure.

    A foreign PDF link on an article page is somebody else's paper — or, on
    MDPI, the journal's marketing flyer, which is a perfectly valid PDF and
    the wrong document. Following one yields a confident, wrong success, so
    the walk follows only what the page itself claims is this article
    (`citation_pdf_url`), what the platform's own convention implies, and
    anchors on the same origin. Foreign links stay in `pdf_links` so `locate`
    can still show them to a human.

    Redirects are unaffected: ScienceDirect's same-origin `pdfft` URL is
    followed and lands on its CDN by redirect, and a redirect is not a
    candidate.
    """
    landing = str(state.get("url") or "")
    host = urllib.parse.urlparse(landing).netloc
    allowed = set(publisher_pdf_urls(landing))
    citation = state.get("citation_pdf_url")
    if isinstance(citation, str) and citation.startswith("http"):
        allowed.add(citation)
    return [
        url for url in pdf_links(state) if url in allowed or urllib.parse.urlparse(url).netloc == host
    ]


def challenge_point(frame: Mapping[str, Any]) -> tuple[float, float]:
    """Where to click a captcha widget: its checkbox, not its centre.

    Turnstile and reCAPTCHA both put the checkbox at the widget's left edge,
    vertically centred; the middle of the frame is the label text and does
    nothing. 22px in is measured, not guessed — the checkbox is roughly 24px
    wide starting ~10px from the edge, so this lands inside it whether the
    rect is the iframe itself or the slightly wider wrapper that a closed
    shadow root forces us to measure instead.
    """
    x = float(frame.get("x") or 0.0)
    y = float(frame.get("y") or 0.0)
    width = float(frame.get("w") or 0.0)
    height = float(frame.get("h") or 0.0)
    return x + min(22.0, max(width / 2.0, 1.0)), y + height / 2.0


def decode_capture(chunks: Sequence[str], expected_sha256: str = "", expected_bytes: int = 0) -> bytes:
    """Reassemble the base64 chunks and prove the transfer was lossless."""
    raw = base64.b64decode("".join(chunks))
    if expected_bytes and len(raw) != expected_bytes:
        raise BrowserError(f"transfer truncated: expected {expected_bytes} bytes, assembled {len(raw)}")
    if expected_sha256 and hashlib.sha256(raw).hexdigest() != expected_sha256:
        raise BrowserError("transfer corrupted: SHA-256 computed in the page does not match the assembled bytes")
    return raw


def is_pdf(raw: bytes) -> bool:
    return raw.startswith(b"%PDF-")


# ── The ladder ─────────────────────────────────────────────────────────────

def read_state(session: str) -> dict[str, Any]:
    """What the session's tab currently shows.

    A session with no tab yet is a normal starting condition, not an error:
    the caller navigates next, which opens one.
    """
    try:
        result = evaluate(_probe_js(), session)
    except BrowserError as error:
        tabs = session_tabs(session)
        if not tabs:
            return {"url": "", "text": "", "no_tab": True}
        # Native PDF viewers may reject page JS. The tab inventory still
        # proves that a tab exists; bootstrap must not open another page.
        tab = tabs[-1]
        url = str(tab.get("url") or "")
        if re.search(r"\.pdf(?:\?|$)", url, re.I):
            return {"url": url, "title": tab.get("title", ""), "content_type": "application/pdf", "ready": "complete"}
        raise BrowserError("existing tab is unreadable; keep this session and inspect it: " + str(error)) from error
    return result if isinstance(result, dict) else {"url": "", "text": str(result)}


def session_tabs(session: str) -> list[dict[str, Any]]:
    data = command("list_tabs", {}, session, timeout=20)
    if not isinstance(data, dict) or not isinstance(data.get("tabs"), list):
        raise BrowserError("could not read this session's tab inventory")
    return list(data["tabs"])


def open_command(url: str, platform: str | None = None) -> list[str]:
    """The OS command that hands a URL to the default browser. Pure.

    The first tab has to be opened outside the extension (see `ensure_tab`),
    and every OS spells that differently — a bare `open` is macOS only, and
    hard-coding it made this skill fail on Windows and Linux at the very
    first page it tried to load.
    """
    system = platform if platform is not None else sys.platform
    if system == "darwin":
        return ["open", url]
    if system.startswith("win"):
        # The empty string is `start`'s window-title argument; without it a
        # quoted URL is taken as the title and no browser opens.
        return ["cmd", "/c", "start", "", url]
    return ["xdg-open", url]


def tab_markers(url: str) -> list[str]:
    """Strings `find_tab` can recognise a freshly opened tab by, best first.

    The full URL matches when the browser lands exactly where it was sent; the
    host still matches after a redirect (an SSO bounce, a trailing-slash
    rewrite); the registrable domain survives a hop to another subdomain.
    """
    parsed = urllib.parse.urlparse(url)
    markers = [url]
    if parsed.netloc:
        markers.append(parsed.netloc)
        labels = parsed.netloc.split(".")
        if len(labels) > 2:
            markers.append(".".join(labels[-2:]))
    seen: set[str] = set()
    unique: list[str] = []
    for marker in markers:
        if marker and marker not in seen:
            seen.add(marker)
            unique.append(marker)
    return unique


def ensure_tab(session: str, url: str, patience: float = 12.0, attempts: int = 1) -> None:
    """Adopt one HTML bootstrap tab once; a failed adoption is a handoff.

    Inventory, not page JavaScript, answers whether a tab exists. Open a
    stable HTML origin before navigating to a PDF/CDN, so redirecting PDFs
    cannot defeat find_tab. `attempts` remains accepted for older callers but
    never authorizes multiple OS opens.
    """
    if session_tabs(session):
        return
    subprocess.run(open_command(DEFAULT_ORIGIN), check=False)
    deadline = time.monotonic() + patience
    while time.monotonic() < deadline:
        time.sleep(1.0)
        try:
            command("find_tab", {"url": DEFAULT_ORIGIN, "active": True}, session, timeout=10)
            if session_tabs(session):
                return
        except BrowserError:
            continue
    raise BrowserError(
        f"tab adoption failed for session {session!r}; keep the existing page, "
        "bring it to the foreground and adopt it with find_tab; do not reopen or switch sessions"
    )


def navigate(url: str, session: str, settle: float = 10.0) -> dict[str, Any]:
    """Send the session's tab to `url` and wait for it to say something useful.

    `readyState === "complete"` is not enough on a publisher SPA: ScienceDirect
    reports complete seconds before it paints the article, and a page read at
    that moment looks exactly like a paywall. So the wait continues while the
    page still classifies as `blocked` — a page that really is blocked costs
    the settle budget once, which is cheaper than recording a false refusal.

    `newTab` is deliberately never used: it hangs in this runtime, and one
    task should own one tab anyway.

    A navigation that never happens must not look like a page that loaded. If
    the tab is still showing the *previous* URL when the budget runs out, this
    returns an error state rather than that stale page — otherwise the caller
    reads one paper's bytes while believing it asked for another's.
    """
    ensure_tab(session, url)
    before = str(read_state(session).get("url") or "")
    command("navigate", {"url": url}, session)
    deadline = time.monotonic() + settle
    state = read_state(session)
    while time.monotonic() < deadline:
        moved = not before or str(state.get("url") or "") != before or before == url
        if moved and state.get("ready") == "complete" and classify_page(state) != "blocked":
            break
        time.sleep(1.0)
        state = read_state(session)
    if before and before != url and str(state.get("url") or "") == before:
        return {**state, "url": before, "stale": True, "requested": url}
    return state


def walk(url: str, session: str, rounds: int = 6, settle: float = 10.0, patience: float = 25.0) -> dict[str, Any]:
    """Drive the tab from `url` to a PDF response, or to a recorded refusal.

    A queue of candidates rather than a single "follow the best link" path,
    because the common no-access failure is a *bounce*: an unentitled PDF URL
    silently redirects back to the abstract page. Every URL is visited at most
    once, so a bounce costs one candidate instead of spinning until the round
    budget runs out, and the walk moves on to the next candidate.

    Returns the final page state plus `kind` (the classification it stopped
    on) and `trail` (what it did on the way), so a caller can record exactly
    why a paper is not `read_back_verified`.
    """
    trail: list[str] = []
    visited: set[str] = set()
    queue: list[str] = [url]
    state: dict[str, Any] = {"url": "", "kind": "error"}
    for _ in range(max(1, rounds)):
        while queue and queue[0] in visited:
            queue.pop(0)
        if not queue:
            break
        target = queue.pop(0)
        visited.add(target)
        state = navigate(target, session, settle)
        landed = str(state.get("url") or "")
        # The tab never left the previous page: this candidate was not visited,
        # and whatever the tab still shows belongs to something else.
        kind = "error" if state.get("stale") else classify_page(state)
        if kind == "challenge":
            state = solve_challenge(state, session, patience, trail)
            landed = str(state.get("url") or "")
            kind = classify_page(state)
        trail.append(f"{kind} @ {landed[:120]}")
        if kind in {"pdf", "error"}:
            return {**state, "kind": kind, "trail": trail}
        if kind == "challenge":
            return {**state, "kind": "challenge_unsolved", "trail": trail}
        bounced = landed != target and landed in visited
        visited.add(landed)
        if bounced:
            # An unentitled PDF URL redirected back somewhere we have been.
            continue
        queue.extend(candidate for candidate in walk_candidates(state) if candidate not in visited)
    kind = classify_page(state) if state.get("url") else "error"
    return {**state, "kind": "blocked" if kind == "landing" else kind, "trail": trail}


def solve_challenge(
    state: Mapping[str, Any], session: str, patience: float, trail: list[str]
) -> dict[str, Any]:
    """Click through an anti-bot checkbox, if one has rendered to click.

    The challenge page is served long before its widget paints — the text
    ("Are you a robot?") shows up first and the Turnstile iframe can take ten
    seconds more — so the widget is polled for, not sampled once.
    """
    current = dict(state)
    frames = current.get("captcha") or []
    deadline = time.monotonic() + patience
    while not frames and time.monotonic() < deadline:
        time.sleep(2.0)
        current = read_state(session)
        if classify_page(current) != "challenge":
            return current
        frames = current.get("captcha") or []
    if not frames:
        return current
    x, y = challenge_point(frames[0])
    trusted_click(x, y, session)
    trail.append(f"trusted-click ({round(x)},{round(y)})")
    deadline = time.monotonic() + patience
    while time.monotonic() < deadline:
        time.sleep(3.0)
        current = read_state(session)
        if classify_page(current) != "challenge":
            break
    return current


def capture_bytes(session: str, chunk: int = CHUNK_CHARS) -> tuple[bytes, dict[str, Any]]:
    """Pull the current document's bytes out of the page, provably intact."""
    header = evaluate(CAPTURE_JS, session)
    if not isinstance(header, dict) or not header.get("ok"):
        raise BrowserError(str((header or {}).get("error") if isinstance(header, dict) else header))
    total = int(header.get("b64_length") or 0)
    chunks: list[str] = []
    for offset in range(0, total, chunk):
        piece = evaluate(
            f"(()=>JSON.stringify(window.__ltzCapture.slice({offset},{offset + chunk})))()", session
        )
        if not isinstance(piece, str):
            raise BrowserError(f"chunk at offset {offset} did not come back as text")
        chunks.append(piece)
    evaluate("(()=>{delete window.__ltzCapture;return JSON.stringify('cleared')})()", session)
    return decode_capture(chunks, str(header.get("sha256") or ""), int(header.get("bytes") or 0)), header


# ── Commands ───────────────────────────────────────────────────────────────

def command_capture(args: argparse.Namespace) -> int:
    if getattr(args, "current", False):
        state = read_state(args.session)
        state.update({"kind": classify_page(state), "trail": ["capture current authenticated page"]})
    else:
        if not args.url:
            raise BrowserError("capture requires --url or --current")
        state = walk(args.url, args.session, args.rounds, args.settle)
    report: dict[str, Any] = {
        "status": "failed",
        "kind": state.get("kind"),
        "requested_url": args.url,
        "final_url": state.get("url"),
        "trail": state.get("trail"),
    }
    if state.get("kind") != "pdf":
        report["remediation"] = {
            "challenge_unsolved": "打开 Arc 里这个标签页，手动点一下 Cloudflare 的“验证您是人类”，再重跑本命令。",
            "blocked": "PDF 链接都被弹回摘要页或页面根本没有全文（本馆无订阅权限）；"
            "先在 MyLOFT 里打开该出版社完成机构登录再重试，否则改用 OA 镜像或记为 metadata_only。",
            "error": "浏览器打不开这个地址（网络/代理不可达）；换镜像源或检查代理。",
        }.get(str(state.get("kind")), "浏览器未到达 PDF 响应。")
        report["detail"] = report["remediation"]
        print(json.dumps(public_report(report), ensure_ascii=False))
        return 2
    raw, header = capture_bytes(args.session, args.chunk)
    if not is_pdf(raw):
        report["kind"] = "not_a_pdf"
        report["content_type"] = header.get("content_type")
        report["remediation"] = "响应不是 PDF（可能是登录页或错误页）；不要保存，改走其他来源。"
        print(json.dumps(public_report(report), ensure_ascii=False))
        return 2
    if args.title or args.doi:
        # A valid PDF is not the same as the *right* PDF: MDPI's article page
        # links its journal's marketing flyer, which downloads perfectly. When
        # the caller knows what it asked for, check before writing. Text the
        # builtin reader cannot decode means "unknown", never "mismatch", so
        # the file is still written and left for identity verification.
        text, extractor = paper_artifacts.extract_text_from_bytes(raw)
        evidence = paper_artifacts.identity_evidence(text, args.title or "", args.doi)
        if extractor != "none" and not paper_artifacts.matches(evidence):
            report["kind"] = "wrong_document"
            report["identity_evidence"] = evidence
            report["remediation"] = (
                "抓到的是有效 PDF，但不是这篇论文（常见：期刊宣传页、参考文献里的他人论文）。"
                "未落盘；用 locate 查看候选，或换来源。"
            )
            print(json.dumps(public_report(report), ensure_ascii=False))
            return 2
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(raw)
    report.update(
        {
            "status": "captured",
            "path": str(output.resolve()),
            "bytes": len(raw),
            "sha256": hashlib.sha256(raw).hexdigest(),
            "content_type": header.get("content_type"),
            "observed_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        }
    )
    print(json.dumps(public_report(report), ensure_ascii=False))
    return 0


def public_report(value: Any) -> Any:
    """Keep temporary signed URLs out of CLI output and shared run logs."""
    if isinstance(value, dict):
        return {key: public_report(item) for key, item in value.items()}
    if isinstance(value, list):
        return [public_report(item) for item in value]
    if isinstance(value, str):
        def strip(match: re.Match[str]) -> str:
            parts = urllib.parse.urlsplit(match[0])
            return urllib.parse.urlunsplit((parts.scheme, parts.hostname or "", parts.path, "", ""))
        return re.sub(r"https?://[^\s\"<>]+", strip, value)
    return value


CROSSREF_WORK = "https://api.crossref.org/works/"
OPENALEX_WORK = "https://api.openalex.org/works/doi:"


def landing_candidates(crossref: Mapping[str, Any], openalex: Mapping[str, Any]) -> list[str]:
    """Where a DOI's full text plausibly lives, best first. Pure.

    `doi.org` itself is unreachable on some networks, so the DOI is resolved
    from metadata instead of by redirect. An open-access PDF beats a landing
    page (no entitlement, no anti-bot), and an Elsevier PII is expanded into
    the ScienceDirect URL because Crossref only ever reports it as an
    `alternative-id`.
    """
    ordered: list[str] = []
    best_oa = openalex.get("best_oa_location") or {}
    primary = openalex.get("primary_location") or {}
    for value in (best_oa.get("pdf_url"), primary.get("pdf_url")):
        if isinstance(value, str) and value.startswith("http"):
            ordered.append(value)
    resource = (crossref.get("resource") or {}).get("primary") or {}
    for value in (resource.get("URL"), best_oa.get("landing_page_url"), primary.get("landing_page_url")):
        if isinstance(value, str) and value.startswith("http") and "doi.org/" not in value:
            ordered.append(value)
    for alternative in crossref.get("alternative-id") or []:
        if isinstance(alternative, str) and re.fullmatch(r"S\d{4}[0-9X]{6,}", alternative):
            ordered.append(f"https://www.sciencedirect.com/science/article/pii/{alternative}")
    seen: set[str] = set()
    unique: list[str] = []
    for value in ordered:
        if value not in seen:
            seen.add(value)
            unique.append(value)
    return unique


def command_resolve(args: argparse.Namespace) -> int:
    """DOI → the URLs worth trying, without going through doi.org."""
    doi = re.sub(r"^https?://(?:dx\.)?doi\.org/", "", args.doi, flags=re.I).strip()

    def _json(url: str) -> dict[str, Any]:
        result = fetch_text(url, args.session, "", args.settle)
        if not result.get("ok"):
            return {}
        try:
            return dict(json.loads(str(result.get("body"))))
        except json.JSONDecodeError:
            return {}

    crossref = (_json(CROSSREF_WORK + urllib.parse.quote(doi)) or {}).get("message") or {}
    openalex = _json(OPENALEX_WORK + urllib.parse.quote(doi))
    titles = crossref.get("title") or [openalex.get("title")]
    payload = {
        "doi": doi,
        "title": (titles or [None])[0],
        "is_oa": (openalex.get("open_access") or {}).get("is_oa"),
        "urls": landing_candidates(crossref, openalex),
    }
    print(json.dumps(payload, ensure_ascii=False))
    return 0 if payload["urls"] else 2


def command_locate(args: argparse.Namespace) -> int:
    state = navigate(args.url, args.session, args.settle)
    payload = {
        "kind": classify_page(state),
        "final_url": state.get("url"),
        "title": state.get("title"),
        "citation_pdf_url": state.get("citation_pdf_url"),
        "pdf_urls": pdf_links(state)[:10],
    }
    print(json.dumps(payload, ensure_ascii=False))
    return 0 if payload["pdf_urls"] or payload["kind"] == "pdf" else 2


def fetch_text(
    url: str, session: str, origin: str = "", settle: float = 10.0, limit: int = 1_000_000
) -> dict[str, Any]:
    """GET a text/JSON URL through the browser's network stack.

    The escape hatch for hosts a shell call cannot open on this network —
    Crossref, OpenAlex and Semantic Scholar are all reachable from the
    browser here and not from `urllib`. Runs from whatever https page the tab
    already shows (all three send `Access-Control-Allow-Origin: *`), and only
    navigates when it has to.
    """
    state = read_state(session)
    if origin or not str(state.get("url") or "").startswith("https://"):
        navigate(origin or DEFAULT_ORIGIN, session, settle)
    code = (
        "(async()=>{try{const r=await fetch(%s,{credentials:'omit'});const t=await r.text();"
        "return JSON.stringify({ok:true,status:r.status,body:t.slice(0,%d)})}"
        "catch(e){return JSON.stringify({ok:false,error:String(e).slice(0,200)})}})()"
        % (json.dumps(url), limit)
    )
    result = evaluate(code, session)
    if not isinstance(result, dict):
        return {"ok": False, "error": f"unexpected evaluate result: {type(result).__name__}"}
    return result


def command_get(args: argparse.Namespace) -> int:
    result = fetch_text(args.url, args.session, args.origin, args.settle, args.limit)
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result.get("ok") else 2


def command_state(args: argparse.Namespace) -> int:
    state = navigate(args.url, args.session, args.settle) if args.url else read_state(args.session)
    print(
        json.dumps(
            {
                "kind": classify_page(state),
                "url": state.get("url"),
                "title": state.get("title"),
                "content_type": state.get("content_type"),
                "captcha": bool(state.get("captcha")),
            },
            ensure_ascii=False,
        )
    )
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--session", default="literature-acquisition", help="Kimi WebBridge session (one per run)")
    parser.add_argument("--settle", type=float, default=10.0, help="seconds to wait for a navigation to finish")
    commands = parser.add_subparsers(dest="command", required=True)

    capture = commands.add_parser("capture", help="walk to the PDF and write verified bytes")
    target = capture.add_mutually_exclusive_group(required=True)
    target.add_argument("--url", help="landing page, DOI page, or direct PDF URL")
    target.add_argument("--current", action="store_true", help="capture the current PDF after authentication, without navigating again")
    capture.add_argument("--output", required=True)
    capture.add_argument("--title", default="", help="expected title; enables the wrong-document guard")
    capture.add_argument("--doi", default=None, help="expected DOI; enables the wrong-document guard")
    capture.add_argument("--rounds", type=int, default=4)
    capture.add_argument("--chunk", type=int, default=CHUNK_CHARS)
    capture.set_defaults(func=command_capture)

    resolve = commands.add_parser("resolve", help="DOI → the URLs worth trying (no doi.org round trip)")
    resolve.add_argument("--doi", required=True)
    resolve.set_defaults(func=command_resolve)

    locate = commands.add_parser("locate", help="report the PDF URLs a landing page offers")
    locate.add_argument("--url", required=True)
    locate.set_defaults(func=command_locate)

    get = commands.add_parser("get", help="fetch text/JSON through the browser")
    get.add_argument("--url", required=True)
    get.add_argument("--origin", default="", help="https page to run the fetch from")
    get.add_argument("--limit", type=int, default=200_000)
    get.set_defaults(func=command_get)

    state = commands.add_parser("state", help="classify what the tab shows")
    state.add_argument("--url", default="")
    state.set_defaults(func=command_state)

    args = parser.parse_args()
    try:
        raise SystemExit(args.func(args))
    except BrowserError as exc:
        print(json.dumps(public_report({"status": "failed", "kind": "browser_error", "detail": str(exc)}), ensure_ascii=False))
        raise SystemExit(3) from exc


if __name__ == "__main__":
    main()
