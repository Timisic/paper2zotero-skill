#!/usr/bin/env python3
"""Search and download through scansci-pdf 1.19.0.

This module is the only importer of scansci_pdf.
"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict, dataclass
from enum import Enum
import os
from pathlib import Path
import shutil
from typing import Any, Final, Literal

import credentials
from sources import Answer, Query, canonical_doi, observed_at

__all__ = [
    "SOURCE",
    "PIN",
    "INSTALL_LINE",
    "LEGAL_ONLY_ENV",
    "GreyPolicy",
    "ScanHit",
    "FetchHit",
    "FetchMiss",
    "NotAddressable",
    "LibraryStatus",
    "grey_policy",
    "search",
    "fetch_candidate",
    "library_ready",
]

SOURCE: Final = "scansci"
PIN: Final = "1.19.0"
INSTALL_LINE: Final = f"pip install 'scansci-pdf=={PIN}'"
LEGAL_ONLY_ENV: Final = "SCANSCI_LEGAL_ONLY"
# Subprocess tests inherit this and must not import scansci-pdf.
_FETCH_DISABLED_ENV: Final = "LITERATURE_SCANSCI_DISABLED"

# Winning labels LEGAL must not keep. Exact match after strip and lower.
# local_cache and late_capture hide which lane wrote the file.
_OPAQUE_UNDER_LEGAL: Final = frozenset({
    "",
    "none",
    "sci-hub",
    "scihub",
    "libgen",
    "scibban",
    "local_cache",
    "late_capture",
})

_GREY_TOKENS: Final = frozenset({"", "0", "false", "no", "grey"})
_LEGAL_TOKENS: Final = frozenset({"1", "true", "yes", "legal", "legal_only"})


class GreyPolicy(Enum):
    GREY = "grey"
    LEGAL = "legal"


@dataclass(frozen=True)
class ScanHit:
    title: str
    doi: str | None
    year: int | None
    authors: tuple[str, ...]
    abstract: str | None
    cited_by_count: int | None
    landing_page_url: str | None
    oa_pdf_url: str | None
    is_oa: bool | None


@dataclass(frozen=True)
class FetchHit:
    path: Path
    source: str
    doi: str | None
    version: Literal["preprint", "unknown"]


@dataclass(frozen=True)
class FetchMiss:
    status: Literal["not_configured", "unavailable", "not_found"]
    detail: str


@dataclass(frozen=True)
class NotAddressable:
    """No DOI and no arXiv id. Acquire records no scansci row."""


@dataclass(frozen=True)
class LibraryStatus:
    ok: bool
    detail: str
    install: str


def grey_policy(*, legal_only: bool = False) -> GreyPolicy:
    if legal_only:
        return GreyPolicy.LEGAL
    raw = credentials.configured_value(LEGAL_ONLY_ENV)
    if raw is None:
        return GreyPolicy.GREY
    token = raw.strip().lower()
    if token in _GREY_TOKENS:
        return GreyPolicy.GREY
    if token in _LEGAL_TOKENS:
        return GreyPolicy.LEGAL
    raise ValueError(f"unknown {LEGAL_ONLY_ENV}: {raw}")


def search(query: Query, *, budget: float) -> Answer:
    if budget <= 0:
        return Answer(source=SOURCE, question="search", status="skipped",
                      detail="retrieval budget spent", observed_at=observed_at())
    module, status = _library()
    if module is None:
        return Answer(source=SOURCE, question="search", status="not_configured",
                      records=[], detail=status.detail, observed_at=observed_at())
    try:
        rows = module.search_papers(
            query.text,
            limit=query.limit,
            year_from=query.from_year,
            year_to=query.to_year,
        )
    except Exception as exc:
        return Answer(source=SOURCE, question="search", status="unavailable",
                      records=[], detail=type(exc).__name__, observed_at=observed_at())
    if not isinstance(rows, list):
        return Answer(source=SOURCE, question="search", status="unavailable",
                      records=[], detail=type(rows).__name__, observed_at=observed_at())
    records = []
    for row in rows:
        hit = _scan_hit(row)
        if hit is not None:
            records.append(asdict(hit))
    return Answer(source=SOURCE, question="search", status="ok" if records else "empty",
                  records=records, observed_at=observed_at())


def fetch_candidate(
    candidate: Mapping[str, Any],
    directory: Path,
    policy: GreyPolicy,
) -> FetchHit | FetchMiss | NotAddressable:
    if os.environ.get(_FETCH_DISABLED_ENV) == "1":
        return NotAddressable()
    identifier, from_arxiv = _identifier(candidate)
    if identifier is None:
        return NotAddressable()
    module, status = _library()
    if module is None:
        return FetchMiss(status="not_configured", detail=status.detail)
    try:
        browser_first = _browser_first(module)
    except Exception as exc:
        return FetchMiss(status="unavailable", detail=type(exc).__name__)
    # This flag starts a long-lived browser. The default path does not.
    if browser_first:
        return FetchMiss(status="unavailable", detail="scihub_browser_first_enabled is set")
    # A crashed download leaves a PDF here. The next attempt must not treat it as a hit.
    _wipe_staging(directory)
    directory.mkdir(parents=True, exist_ok=True)
    try:
        raw = module.download(identifier, directory, **_download_kwargs(policy))
    except Exception as exc:
        return FetchMiss(status="unavailable", detail=type(exc).__name__)
    if not isinstance(raw, Mapping):
        return FetchMiss(status="unavailable", detail=type(raw).__name__)
    if raw.get("success") is not True:
        detail = str(raw.get("reason") or raw.get("error") or "not found")
        return FetchMiss(status="not_found", detail=detail)
    file_value = raw.get("file")
    if not file_value:
        return FetchMiss(status="unavailable", detail="download result has no file")
    path = Path(file_value)
    if not path.is_file():
        return FetchMiss(status="unavailable", detail="download result file is missing")
    label = str(raw.get("source") or "")
    if _legal_source_rejected(policy, label):
        if _within(path, directory):
            path.unlink(missing_ok=True)
        return FetchMiss(status="not_found", detail=label.strip() or "opaque source")
    try:
        placed = _copy_into_staging(path, directory)
    except OSError as exc:
        return FetchMiss(status="unavailable", detail=type(exc).__name__)
    version: Literal["preprint", "unknown"] = (
        "preprint" if from_arxiv or label.strip().lower() == "arxiv" else "unknown"
    )
    reported = canonical_doi(_text(raw.get("doi")))
    doi = reported if reported else (None if from_arxiv else identifier)
    return FetchHit(path=placed, source=label, doi=doi, version=version)


def library_ready() -> LibraryStatus:
    return _library()[1]


def _library() -> tuple[Any, LibraryStatus]:
    try:
        import scansci_pdf
    except ImportError as exc:
        detail = f"scansci-pdf {PIN} is not installed ({type(exc).__name__}). {INSTALL_LINE}"
        return None, LibraryStatus(ok=False, detail=detail, install=INSTALL_LINE)
    version = getattr(scansci_pdf, "__version__", None)
    if version != PIN:
        detail = f"scansci-pdf {version} is not {PIN}. {INSTALL_LINE}"
        return None, LibraryStatus(ok=False, detail=detail, install=INSTALL_LINE)
    return scansci_pdf, LibraryStatus(ok=True, detail=f"scansci-pdf {PIN}", install=INSTALL_LINE)


def _download_kwargs(policy: GreyPolicy) -> dict[str, object]:
    if policy is GreyPolicy.GREY:
        strategy, scihub_enabled = "fastest", True
    elif policy is GreyPolicy.LEGAL:
        strategy, scihub_enabled = "legal_only", False
    else:
        raise ValueError(f"unknown policy: {policy}")
    return {
        "strategy": strategy,
        "scihub_enabled": scihub_enabled,
        "use_tor": False,
        "use_vpnsci": False,
        "bibtex": False,
        "rename": False,
    }


def _legal_source_rejected(policy: GreyPolicy, source: str) -> bool:
    if policy is GreyPolicy.GREY:
        return False
    return source.strip().lower() in _OPAQUE_UNDER_LEGAL


def _browser_first(module: Any) -> bool:
    config = getattr(module, "config", None)
    load_config = getattr(config, "load_config", None)
    if not callable(load_config):
        return False
    loaded = load_config()
    if isinstance(loaded, Mapping):
        return bool(loaded.get("scihub_browser_first_enabled"))
    return bool(getattr(loaded, "scihub_browser_first_enabled", False))


def _wipe_staging(directory: Path) -> None:
    if directory.is_symlink() or directory.is_file():
        directory.unlink()
        return
    if directory.is_dir():
        shutil.rmtree(directory)


def _within(path: Path, directory: Path) -> bool:
    try:
        resolved = path.resolve()
        root = directory.resolve()
    except OSError:
        return False
    if resolved == root:
        return False
    try:
        resolved.relative_to(root)
    except ValueError:
        return False
    return True


def _copy_into_staging(path: Path, directory: Path) -> Path:
    # verified() moves the file it accepts. A cache hit outside staging is copied
    # in so that move does not take scansci's cache file.
    if _within(path, directory):
        return path
    directory.mkdir(parents=True, exist_ok=True)
    destination = directory / "download.pdf"
    shutil.copyfile(path, destination)
    return destination


def _identifier(candidate: Mapping[str, Any]) -> tuple[str | None, bool]:
    identifiers = candidate.get("identifiers") or {}
    if not isinstance(identifiers, Mapping):
        identifiers = {}
    doi = candidate.get("doi") or identifiers.get("doi")
    if not doi and str(candidate.get("id") or "").startswith("doi:"):
        doi = str(candidate["id"]).removeprefix("doi:")
    canonical = canonical_doi(None if doi is None else str(doi))
    if canonical:
        return canonical, False
    arxiv = identifiers.get("arxiv")
    if arxiv is None:
        return None, False
    text = str(arxiv).strip()
    if not text:
        return None, False
    return text, True


def _scan_hit(row: Any) -> ScanHit | None:
    if not isinstance(row, Mapping):
        return None
    title = _text(row.get("title"))
    if title is None:
        return None
    is_oa = row.get("is_oa")
    return ScanHit(
        title=title,
        doi=_text(row.get("doi")),
        year=_whole(row.get("year")),
        authors=_authors(row.get("authors")),
        abstract=_text(row.get("abstract")),
        cited_by_count=_whole(row.get("cited_by_count")),
        landing_page_url=_text(row.get("url")),
        oa_pdf_url=_text(row.get("oa_url")),
        is_oa=is_oa if isinstance(is_oa, bool) else None,
    )


def _authors(value: Any) -> tuple[str, ...]:
    if isinstance(value, str):
        text = value.strip()
        return (text,) if text else ()
    if not isinstance(value, (list, tuple)):
        return ()
    return tuple(item.strip() for item in value if isinstance(item, str) and item.strip())


def _whole(value: Any) -> int | None:
    if isinstance(value, bool) or value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None
