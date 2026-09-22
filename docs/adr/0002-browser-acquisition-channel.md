# ADR-0002: Use the user's browser as a PDF acquisition channel

Status: Accepted for browser transport. Routing precedence is superseded by [ADR-0004](0004-http-first-discovery-and-acquisition.md).

Some full-text access depends on a logged-in publisher session, institutional access or an interactive challenge. Reimplementing these sessions in an HTTP client would duplicate browser state and make access failures harder to diagnose. Adopting an entire publisher-scraper project would also duplicate the existing browser connection.

`scripts/browser_pdf.py` therefore uses the connected browser for the requests that need it. It classifies the observed page, follows candidate PDF links and captures bytes through the current session. Byte count and SHA-256 are checked after transfer; the paper identity check remains a separate requirement.

The result distinguishes login/entitlement, challenges, unreachable pages and a broken browser connection. The Agent inspects the actual page before choosing a remedy. Multiple publisher errors alone do not prove a lost institutional session, and a reachable page does not guarantee a downloadable PDF.

Browser access is a fallback under ADR-0004. It does not gate directly downloadable papers. Current session ownership and institutional-login steps are maintained in [acquisition-and-artifacts.md](../../paper-to-zotero/references/acquisition-and-artifacts.md#myloft-handoff).
