"""browser_pdf: the pure judgements the browser ladder branches on.

Everything here is deterministic — page state in, decision out — so the parts
that decide "is this a PDF, a captcha, or a dead end" and "which of these
forty PDF links is the article" are pinned without touching a browser.
"""

from __future__ import annotations

import base64
import argparse
import hashlib
import importlib.util
from pathlib import Path

import pytest

SPEC = importlib.util.spec_from_file_location(
    "browser_pdf", Path(__file__).resolve().parent.parent / "scripts" / "browser_pdf.py"
)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def state(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "url": "https://example.org/article/1",
        "title": "An article",
        "content_type": "text/html",
        "ready": "complete",
        "text": "Abstract ...",
        "citation_pdf_url": None,
        "links": [],
        "captcha": [],
    }
    base.update(overrides)
    return base


# ── classify_page ──────────────────────────────────────────────────────────

def test_a_pdf_response_is_a_pdf() -> None:
    assert MODULE.classify_page(state(content_type="application/pdf")) == "pdf"


def test_content_type_parameters_do_not_hide_a_pdf() -> None:
    assert MODULE.classify_page(state(content_type="application/pdf; name=main.pdf")) == "pdf"


def test_a_rendered_captcha_widget_is_a_challenge() -> None:
    page = state(captcha=[{"src": "https://challenges.cloudflare.com/turnstile/", "x": 300, "y": 200, "w": 300, "h": 65}])
    assert MODULE.classify_page(page) == "challenge"


def test_challenge_text_is_recognised_before_the_widget_renders() -> None:
    assert MODULE.classify_page(state(text="Are you a robot?\nPlease confirm")) == "challenge"
    assert MODULE.classify_page(state(text="請稍候…驗證您是人類")) == "challenge"


def test_a_browser_error_page_is_not_a_paywall() -> None:
    assert MODULE.classify_page(state(url="chrome-error://chromewebdata/")) == "error"


def test_a_page_offering_a_pdf_is_a_landing_page() -> None:
    page = state(citation_pdf_url="https://example.org/article/1.pdf")
    assert MODULE.classify_page(page) == "landing"


def test_a_page_offering_nothing_is_blocked() -> None:
    assert MODULE.classify_page(state(text="Purchase PDF $39.95")) == "blocked"


# ── pdf_links ranking ──────────────────────────────────────────────────────

def test_citation_meta_outranks_every_anchor() -> None:
    page = state(
        citation_pdf_url="https://example.org/article/1.pdf",
        links=["https://example.org/article/1/supplement.pdf"],
    )
    assert MODULE.pdf_links(page)[0] == "https://example.org/article/1.pdf"


def test_a_reference_lists_pdf_never_outranks_the_articles_own(
) -> None:
    """The JMIR regression: the only anchor on the page was a cited report."""
    page = state(
        url="https://formative.jmir.org/2025/1/e65605",
        links=["https://www.ofcom.org.uk/siteassets/online-nation-2023-report.pdf"],
    )
    assert MODULE.pdf_links(page)[0] == "https://formative.jmir.org/2025/1/e65605/PDF"


def test_same_origin_anchors_outrank_foreign_ones() -> None:
    page = state(
        url="https://example.org/article/1",
        links=[
            "https://elsewhere.example.com/cited.pdf",
            "https://example.org/article/1/pdf",
        ],
    )
    assert MODULE.pdf_links(page)[0] == "https://example.org/article/1/pdf"


def test_duplicates_collapse_but_order_survives() -> None:
    page = state(
        citation_pdf_url="https://example.org/a.pdf",
        links=["https://example.org/a.pdf", "https://example.org/b.pdf"],
    )
    assert MODULE.pdf_links(page) == ["https://example.org/a.pdf", "https://example.org/b.pdf"]


def test_non_pdf_anchors_are_ignored() -> None:
    assert MODULE.pdf_links(state(links=["https://example.org/article/2"])) == []


# ── publisher_pdf_urls ─────────────────────────────────────────────────────

@pytest.mark.parametrize(
    "landing,expected",
    [
        ("https://formative.jmir.org/2025/1/e65605", "https://formative.jmir.org/2025/1/e65605/PDF"),
        (
            "https://journals.sagepub.com/doi/10.1177/14604582251396428",
            "https://journals.sagepub.com/doi/pdf/10.1177/14604582251396428",
        ),
        (
            "https://onlinelibrary.wiley.com/doi/10.1002/jclp.23456",
            "https://onlinelibrary.wiley.com/doi/pdfdirect/10.1002/jclp.23456",
        ),
        (
            "https://link.springer.com/article/10.1007/s10916-024-02001-1",
            "https://link.springer.com/content/pdf/10.1007/s10916-024-02001-1.pdf",
        ),
        ("https://www.nature.com/articles/s41591-024-03093-5", "https://www.nature.com/articles/s41591-024-03093-5.pdf"),
        ("https://www.mdpi.com/2076-328X/14/9/812", "https://www.mdpi.com/2076-328X/14/9/812/pdf"),
        (
            "https://www.frontiersin.org/articles/10.3389/fpsyg.2024.1234567/full",
            "https://www.frontiersin.org/articles/10.3389/fpsyg.2024.1234567/pdf",
        ),
        (
            "https://pmc.ncbi.nlm.nih.gov/articles/PMC12239686/",
            "https://pmc.ncbi.nlm.nih.gov/articles/PMC12239686/pdf/",
        ),
    ],
)
def test_platform_conventions(landing: str, expected: str) -> None:
    assert expected in MODULE.publisher_pdf_urls(landing)


def test_an_unknown_platform_gets_no_guess() -> None:
    assert MODULE.publisher_pdf_urls("https://example.org/some/article") == []


def test_a_doi_free_atypon_path_gets_no_guess() -> None:
    assert MODULE.publisher_pdf_urls("https://journals.sagepub.com/home/jhi") == []


# ── challenge_point ────────────────────────────────────────────────────────

def test_the_click_lands_on_the_checkbox_not_the_label() -> None:
    x, y = MODULE.challenge_point({"x": 300.0, "y": 200.0, "w": 300.0, "h": 65.0})
    assert (x, y) == (322.0, 232.5)


def test_a_narrow_widget_is_still_clicked_inside_itself() -> None:
    x, _ = MODULE.challenge_point({"x": 10.0, "y": 10.0, "w": 30.0, "h": 40.0})
    assert 10.0 < x < 40.0


# ── decode_capture ─────────────────────────────────────────────────────────

def test_a_clean_transfer_reassembles() -> None:
    raw = b"%PDF-1.7\n" + bytes(range(256)) * 8
    encoded = base64.b64encode(raw).decode()
    chunks = [encoded[i : i + 16] for i in range(0, len(encoded), 16)]
    assert MODULE.decode_capture(chunks, hashlib.sha256(raw).hexdigest(), len(raw)) == raw
    assert MODULE.is_pdf(raw)


def test_a_truncated_transfer_is_rejected_not_saved() -> None:
    raw = b"%PDF-1.7 body"
    encoded = base64.b64encode(raw).decode()
    with pytest.raises(MODULE.BrowserError, match="truncated"):
        MODULE.decode_capture([encoded], expected_bytes=len(raw) + 1)


def test_a_corrupted_transfer_is_rejected() -> None:
    raw = b"%PDF-1.7 body"
    encoded = base64.b64encode(raw).decode()
    with pytest.raises(MODULE.BrowserError, match="corrupted"):
        MODULE.decode_capture([encoded], expected_sha256="0" * 64)


def test_html_is_not_a_pdf() -> None:
    assert MODULE.is_pdf(b"<!doctype html>") is False


# ── walk: the branch that decides when to stop ─────────────────────────────

class FakeBrowser:
    """A scripted browser: URL → the page state a navigation lands on."""

    def __init__(self, pages: dict[str, dict[str, object]]) -> None:
        self.pages = pages
        self.visits: list[str] = []

    def navigate(self, url: str, session: str, settle: float = 10.0) -> dict[str, object]:
        self.visits.append(url)
        return dict(self.pages.get(url, state(url=url, text="Not found")))


def run_walk(monkeypatch: pytest.MonkeyPatch, browser: FakeBrowser, start: str) -> dict[str, object]:
    monkeypatch.setattr(MODULE, "navigate", browser.navigate)
    monkeypatch.setattr(MODULE, "time", type("_T", (), {"monotonic": staticmethod(lambda: 0.0), "sleep": staticmethod(lambda _s: None)}))
    return MODULE.walk(start, "test-session", rounds=6)


def test_a_landing_page_is_followed_to_its_pdf(monkeypatch: pytest.MonkeyPatch) -> None:
    browser = FakeBrowser(
        {
            "https://example.org/article/1": state(links=["https://example.org/article/1/pdf"]),
            "https://example.org/article/1/pdf": state(
                url="https://example.org/article/1/pdf", content_type="application/pdf"
            ),
        }
    )
    result = run_walk(monkeypatch, browser, "https://example.org/article/1")
    assert result["kind"] == "pdf"
    assert browser.visits == ["https://example.org/article/1", "https://example.org/article/1/pdf"]


def test_bouncing_pdf_links_end_as_blocked_without_looping(monkeypatch: pytest.MonkeyPatch) -> None:
    """Wiley's no-entitlement shape: every PDF URL redirects to the abstract."""
    abstract = state(
        url="https://example.org/doi/abs/1",
        links=["https://example.org/doi/pdf/1", "https://example.org/doi/pdfdirect/1"],
    )
    browser = FakeBrowser(
        {
            "https://example.org/doi/1": abstract,
            "https://example.org/doi/pdf/1": abstract,
            "https://example.org/doi/pdfdirect/1": abstract,
        }
    )
    result = run_walk(monkeypatch, browser, "https://example.org/doi/1")
    assert result["kind"] == "blocked"
    assert len(browser.visits) == 3
    assert len(set(browser.visits)) == 3


def test_an_unreachable_host_stops_immediately(monkeypatch: pytest.MonkeyPatch) -> None:
    browser = FakeBrowser({"https://blocked.example/a": state(url="chrome-error://chromewebdata/")})
    result = run_walk(monkeypatch, browser, "https://blocked.example/a")
    assert result["kind"] == "error"
    assert browser.visits == ["https://blocked.example/a"]


# ── ensure_tab: adopting the session's first tab ───────────────────────────

def test_markers_go_from_exact_url_to_registrable_domain() -> None:
    assert MODULE.tab_markers("https://app.myloft.xyz/browse/home") == [
        "https://app.myloft.xyz/browse/home",
        "app.myloft.xyz",
        "myloft.xyz",
    ]


def test_a_bare_host_needs_no_domain_fallback() -> None:
    assert MODULE.tab_markers("https://example.org/x") == ["https://example.org/x", "example.org"]


def test_an_unreadable_existing_pdf_tab_never_opens_another_page(monkeypatch: pytest.MonkeyPatch) -> None:
    """A native PDF viewer can reject evaluate while its tab still exists."""
    opened: list = []
    def command(action, args, session, timeout=180):
        if action == "list_tabs":
            return {"success": True, "tabs": [{"tabId": 7, "url": "https://cdn.example.org/a.pdf"}]}
        raise MODULE.BrowserError("Cannot access contents of this page")
    monkeypatch.setattr(MODULE, "command", command)
    monkeypatch.setattr(MODULE.subprocess, "run", lambda *a, **k: opened.append(a))
    monkeypatch.setattr(MODULE.time, "sleep", lambda _: None)
    try:
        MODULE.ensure_tab("existing-pdf", "https://publisher.example.org/b", patience=0, attempts=2)
    except MODULE.BrowserError:
        pass
    assert not opened, "a page-read failure must not bootstrap another browser page"


def test_current_capture_keeps_the_authenticated_pdf_page(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys) -> None:
    raw = (Path(__file__).parent / "fixtures/probe.pdf").read_bytes()
    monkeypatch.setattr(MODULE, "read_state", lambda _: state(url="https://cdn.example.org/a.pdf?token=signed-secret-123", content_type="application/pdf"))
    def no_navigation(*args):
        raise AssertionError("an authenticated PDF must not be navigated away from")
    monkeypatch.setattr(MODULE, "walk", no_navigation)
    monkeypatch.setattr(MODULE, "capture_bytes", lambda *a: (raw, {"content_type": "application/pdf"}))
    args = argparse.Namespace(current=True, url=None, session="s", output=str(tmp_path / "source.pdf"),
                              title="Zotero MCP Write Probe", doi="10.1000/alpha", chunk=400000)
    assert MODULE.command_capture(args) == 0
    assert (tmp_path / "source.pdf").read_bytes() == raw
    output = capsys.readouterr().out
    assert "captured" in output and "signed-secret-123" not in output


class TabHarness:
    """Counts `open` calls and answers find_tab after a chosen attempt."""

    def __init__(self, succeed_on_open: int) -> None:
        self.succeed_on_open = succeed_on_open
        self.opens = 0

    def open(self, argv: list[str], check: bool = False) -> None:
        self.opens += 1

    def command(self, action: str, args: object, session: str, timeout: int = 180) -> object:
        if action == "list_tabs":
            return {"tabs": [{"url": "https://example.org/x"}] if getattr(self, "adopted", False) else []}
        if action == "find_tab" and self.opens >= self.succeed_on_open:
            self.adopted = True
            return {"success": True}
        raise MODULE.BrowserError(f"no tab matching for {action}")


def install_tab_harness(monkeypatch: pytest.MonkeyPatch, harness: TabHarness) -> None:
    monkeypatch.setattr(MODULE.subprocess, "run", harness.open)
    monkeypatch.setattr(MODULE, "command", harness.command)
    monkeypatch.setattr(MODULE, "read_state", lambda _session: {"no_tab": True})
    clock = {"t": 0.0}

    def tick(seconds: float) -> None:
        clock["t"] += seconds

    monkeypatch.setattr(
        MODULE,
        "time",
        type("_T", (), {"monotonic": staticmethod(lambda: clock["t"]), "sleep": staticmethod(tick)}),
    )


def test_one_bootstrap_is_adopted_without_reopening(monkeypatch: pytest.MonkeyPatch) -> None:
    harness = TabHarness(succeed_on_open=1)
    install_tab_harness(monkeypatch, harness)
    MODULE.ensure_tab("s", "https://example.org/x", patience=6.0, attempts=2)
    assert harness.opens == 1


def test_giving_up_says_what_the_user_should_do(monkeypatch: pytest.MonkeyPatch) -> None:
    harness = TabHarness(succeed_on_open=99)
    install_tab_harness(monkeypatch, harness)
    with pytest.raises(MODULE.BrowserError, match="foreground"):
        MODULE.ensure_tab("s", "https://example.org/x", patience=6.0, attempts=2)
    assert harness.opens == 1


def test_an_existing_tab_skips_the_bootstrap_entirely(monkeypatch: pytest.MonkeyPatch) -> None:
    harness = TabHarness(succeed_on_open=1)
    install_tab_harness(monkeypatch, harness)
    harness.adopted = True
    MODULE.ensure_tab("s", "https://example.org/x")
    assert harness.opens == 0


def test_an_empty_bodied_interstitial_is_a_challenge_not_a_landing_page() -> None:
    """SAGE regression: the wait message lives only in the <title>."""
    page = state(title="請稍候...", text="", citation_pdf_url="https://example.org/a.pdf")
    assert MODULE.classify_page(page) == "challenge"


def test_a_real_article_title_is_not_mistaken_for_a_challenge() -> None:
    page = state(title="Evaluating conversational agents", text="Abstract", citation_pdf_url="https://example.org/a.pdf")
    assert MODULE.classify_page(page) == "landing"


# ── portability: opening the first tab ─────────────────────────────────────

@pytest.mark.parametrize(
    "platform,expected",
    [
        ("darwin", ["open", "https://example.org/"]),
        ("win32", ["cmd", "/c", "start", "", "https://example.org/"]),
        ("linux", ["xdg-open", "https://example.org/"]),
    ],
)
def test_every_os_gets_its_own_open_command(platform: str, expected: list[str]) -> None:
    assert MODULE.open_command("https://example.org/", platform) == expected


def test_the_windows_start_command_keeps_its_title_placeholder() -> None:
    """Without the empty title argument, `start` swallows the URL as a title."""
    assert MODULE.open_command("https://x/", "win32")[3] == ""


# ── institutional proxies rewrite the hostname ─────────────────────────────

@pytest.mark.parametrize(
    "url,expected",
    [
        ("https://www-sciencedirect-com.ezproxy.lib.uni.edu/science/article/pii/S1", "www.sciencedirect.com"),
        ("https://www-nature-com.libproxy1.usc.edu/articles/s41591-1", "www.nature.com"),
        ("https://link-springer-com.idm.oclc.org/article/10.1007/x", "link.springer.com"),
        ("https://onlinelibrary-wiley-com.ezp.lib.cam.ac.uk/doi/10.1002/x", "onlinelibrary.wiley.com"),
        ("https://www.sciencedirect.com.ezproxy.uni.edu/science/article/pii/S1", "www.sciencedirect.com"),
        ("https://formative.jmir.org/2025/1/e65605", "formative.jmir.org"),
        ("https://some-journal.org/doi/10.1/x", "some-journal.org"),
    ],
)
def test_the_publishers_own_host_is_recovered(url: str, expected: str) -> None:
    assert MODULE.unproxied_host(url) == expected


def test_a_doubled_dash_is_a_real_dash_in_the_publisher_host() -> None:
    assert MODULE.unproxied_host("https://some--journal-org.ezproxy.uni.edu/x") == "some-journal.org"


def test_platform_conventions_survive_a_proxy_rewrite() -> None:
    """Matched on the real publisher; emitted on the host that serves the file."""
    urls = MODULE.publisher_pdf_urls("https://journals-sagepub-com.ezproxy.x.edu/doi/10.1177/14604582251396428")
    assert urls == ["https://journals-sagepub-com.ezproxy.x.edu/doi/pdf/10.1177/14604582251396428"]


def test_a_proxied_landing_page_still_ranks_its_own_pdf_first() -> None:
    page = state(
        url="https://formative-jmir-org.ezproxy.uni.edu/2025/1/e65605",
        links=["https://www.ofcom.org.uk/cited-report.pdf"],
    )
    assert MODULE.pdf_links(page)[0] == "https://formative-jmir-org.ezproxy.uni.edu/2025/1/e65605/PDF"


# ── following only this article's own PDF ──────────────────────────────────

def test_a_foreign_pdf_link_is_reported_but_never_followed() -> None:
    """MDPI regression: the journal's marketing flyer is a valid PDF."""
    page = state(
        url="https://www.mdpi.com/2077-0383/14/7/2265",
        citation_pdf_url="https://www.mdpi.com/2077-0383/14/7/2265/pdf",
        links=["https://mdpi-res.com/journals/93/flyer.pdf"],
    )
    assert "https://mdpi-res.com/journals/93/flyer.pdf" in MODULE.pdf_links(page)
    assert MODULE.walk_candidates(page) == ["https://www.mdpi.com/2077-0383/14/7/2265/pdf"]


def test_a_cross_origin_citation_url_is_still_followed() -> None:
    """Some publishers host the article's own PDF on a separate CDN."""
    page = state(
        url="https://example.org/article/1",
        citation_pdf_url="https://cdn.example.net/article/1.pdf",
    )
    assert MODULE.walk_candidates(page) == ["https://cdn.example.net/article/1.pdf"]


def test_the_walk_stops_rather_than_following_a_foreign_pdf(monkeypatch: pytest.MonkeyPatch) -> None:
    landing = state(url="https://www.mdpi.com/x/1", links=["https://ads.example.net/flyer.pdf"])
    browser = FakeBrowser({"https://www.mdpi.com/x/1": landing})
    result = run_walk(monkeypatch, browser, "https://www.mdpi.com/x/1")
    assert result["kind"] == "blocked"
    # The platform's own /pdf convention is tried; the foreign flyer never is.
    assert browser.visits == ["https://www.mdpi.com/x/1", "https://www.mdpi.com/x/1/pdf"]
    assert not any("ads.example.net" in visited for visited in browser.visits)


def test_a_pdf_endpoint_does_not_get_the_convention_applied_again() -> None:
    """Otherwise the walk chases /pdf/pdf/pdf until its rounds run out."""
    assert MODULE.publisher_pdf_urls("https://www.mdpi.com/2077-0383/14/7/2265/pdf") == []
    assert MODULE.publisher_pdf_urls("https://formative.jmir.org/2025/1/e65605/PDF") == []
    assert MODULE.publisher_pdf_urls("https://link.springer.com/content/pdf/10.1007/x.pdf") == []
