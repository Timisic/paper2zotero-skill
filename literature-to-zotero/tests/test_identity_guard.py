"""The identity guard, hardened by what a real acceptance run turned up.

A live capture returned one paper's bytes while another was requested, and the
guard passed it: the requested title was "Mental-LLM", two words that both
appear in an unrelated mental-health NLP paper. These pin the two rules that
now stop it.
"""
from __future__ import annotations

import sys
from pathlib import Path

from test_cli import ROOT

sys.path.insert(0, str(ROOT / "scripts"))
import paper_artifacts as pa  # noqa: E402

JMIR_TEXT = (
    "JOURNAL OF MEDICAL INTERNET RESEARCH\n\nShin et al\n\nOriginal Paper\n\n"
    "Using Large Language Models to Detect Depression From User-Generated "
    "Diary Text Data as a Novel Approach in Digital Mental Health Screening\n"
    "doi: 10.2196/54617\n"
)


def test_a_declared_doi_that_differs_rejects_the_file() -> None:
    evidence = pa.identity_evidence(JMIR_TEXT, "Mental-LLM", "10.1145/3643540")
    assert evidence["doi_conflict"] is True
    assert pa.judge(evidence) == "rejected"


def test_a_matching_declared_doi_verifies_whatever_the_title_looks_like() -> None:
    evidence = pa.identity_evidence(JMIR_TEXT, "Totally unrelated wording here", "10.2196/54617")
    assert evidence["doi_match"] is True
    assert pa.judge(evidence) == "verified"


def test_a_short_title_alone_is_insufficient_not_proof() -> None:
    # Both title words appear, but two words identify nothing.
    text = "A study of mental health and LLM systems with no DOI printed anywhere."
    evidence = pa.identity_evidence(text, "Mental-LLM", None)
    assert evidence["title_token_overlap"] == 1.0
    assert pa.judge(evidence) == "insufficient"


def test_a_long_title_still_matches_on_words_alone() -> None:
    text = "Large Language Models for Mental Health Applications: a systematic review of trials."
    evidence = pa.identity_evidence(text, "Large Language Models for Mental Health Applications: Systematic Review", None)
    assert pa.judge(evidence) == "verified"


def test_a_reference_list_full_of_other_dois_is_not_a_conflict() -> None:
    """Scoping the check to the front matter is what makes it usable."""
    front = "Our Paper Title Goes Here With Enough Words\ndoi: 10.1000/ours\n"
    references = "\n".join(f"[{index}] Someone. doi:10.9999/other{index}" for index in range(40))
    evidence = pa.identity_evidence(front + " " * 4000 + references, "Our Paper Title Goes Here With Enough Words", "10.1000/ours")
    assert evidence["doi_match"] is True
    assert evidence["doi_conflict"] is False
    assert pa.judge(evidence) == "verified"


def test_an_unfilled_template_doi_declares_nothing() -> None:
    """Preprints of conference papers carry the camera-ready form, not a DOI.

    A live acceptance run rejected the right paper because its arXiv preprint
    printed `https://doi.org/10.1145/XXXXXX.XXXXXX` — the ACM template with
    the fields still blank.
    """
    text = ("MentaLLaMA: Interpretable Mental Health Analysis on Social Media with "
            "Large Language Models\nhttps://doi.org/10.1145/XXXXXX.XXXXXX\n")
    evidence = pa.identity_evidence(
        text, "MentaLLaMA: Interpretable Mental Health Analysis on Social Media with "
              "Large Language Models", "10.1145/3589334.3648137")
    assert evidence["front_matter_dois"] == []
    assert evidence["doi_conflict"] is False
    assert pa.judge(evidence) == "verified"
    assert pa.placeholder_doi("10.1145/xxxxxx.xxxxxx") is True
    assert pa.placeholder_doi("10.1145/3589334.3648137") is False


def test_a_word_perfect_title_under_a_conflicting_doi_is_kept_for_a_human() -> None:
    """A preprint announcing its own DOI is a version difference, not a mix-up."""
    title = "Large Language Models for Interpretable Mental Health Analysis"
    text = f"{title}\nhttps://doi.org/10.48550/arXiv.2309.13567\n"
    evidence = pa.identity_evidence(text, title, "10.1145/3589334.3648137")
    assert evidence["doi_conflict"] is True
    assert evidence["title_token_overlap"] == 1.0
    # Not verified — it is not the requested version — and not rejected either.
    assert pa.judge(evidence) == "insufficient"


def test_a_conflicting_doi_still_rejects_a_paper_that_is_merely_similar() -> None:
    evidence = pa.identity_evidence(
        JMIR_TEXT, "Using Large Language Models to Detect Anxiety From Wearable Sensor Streams",
        "10.1145/3643540")
    assert evidence["doi_conflict"] is True
    assert pa.judge(evidence) == "rejected"
