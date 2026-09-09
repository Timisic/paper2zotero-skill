"""P1: one screened list, no core/expansion structure, honest gaps."""
from __future__ import annotations

import json
from pathlib import Path

from test_cli import FIXTURES, run_script


def screened(count: int, **overrides: object) -> list[dict[str, object]]:
    rows = []
    for index in range(count):
        row: dict[str, object] = {
            "id": f"doi:10.1000/p{index}",
            "title": f"Paper {index}",
            "year": 2025,
            "venue": "CHI",
            "hit_reason": "Tests an AI intervention against mental-health outcomes.",
            "cited_by_count": index,
            "citation_source": "OpenAlex",
            "citation_observed_at": "2026-09-05T00:00:00+00:00",
            "doi": f"10.1000/p{index}",
        }
        row.update(overrides)
        rows.append(row)
    return rows


def write(tmp_path: Path, rows: list[dict[str, object]]) -> Path:
    path = tmp_path / "candidates.json"
    path.write_text(json.dumps(rows), encoding="utf-8")
    return path


def test_screened_candidates_need_no_core_or_expansion_label(tmp_path: Path) -> None:
    source = write(tmp_path, screened(6))
    output = tmp_path / "candidate-table.md"
    result = run_script("candidate_table.py", "--input", str(source), "--output", str(output))
    assert json.loads(result.stdout)["rows"] == 6
    table = output.read_text()
    assert table.startswith("ID | Paper | Year / venue | Why relevant | Citations | Source")
    assert "Set" not in table.splitlines()[0]
    assert "https://doi.org/10.1000/p0" in table


def test_a_set_column_appears_only_when_candidates_carry_one(tmp_path: Path) -> None:
    rows = screened(2)
    rows[0]["candidate_set"] = "core"
    output = tmp_path / "candidate-table.md"
    run_script("candidate_table.py", "--input", str(write(tmp_path, rows)), "--output", str(output))
    header = output.read_text().splitlines()[0]
    assert header.endswith("| Set")


def test_missing_hit_reason_still_blocks_the_table(tmp_path: Path) -> None:
    result = run_script(
        "candidate_table.py", "--input", str(FIXTURES / "normalized_candidates.json"),
        "--output", str(tmp_path / "candidate-table.md"), check=False,
    )
    assert result.returncode == 2
    assert "candidate screening is incomplete" in result.stderr


def test_missing_citation_data_is_unknown_not_zero(tmp_path: Path) -> None:
    rows = screened(1, cited_by_count=None, citation_source=None, citation_observed_at=None)
    output = tmp_path / "candidate-table.md"
    run_script("candidate_table.py", "--input", str(write(tmp_path, rows)), "--output", str(output))
    columns = [value.strip() for value in output.read_text().splitlines()[2].split("|")]
    assert columns[4] == "Unknown"


def test_default_list_budget_is_fifteen_and_is_explicitly_overridable(tmp_path: Path) -> None:
    source = write(tmp_path, screened(16))
    output = tmp_path / "candidate-table.md"
    result = run_script("candidate_table.py", "--input", str(source), "--output", str(output), check=False)
    assert result.returncode == 2
    assert "list budget" in result.stderr
    widened = run_script(
        "candidate_table.py", "--input", str(source), "--output", str(output), "--max-rows", "20",
    )
    assert json.loads(widened.stdout)["rows"] == 16


def test_a_short_list_is_returned_as_is_without_padding(tmp_path: Path) -> None:
    output = tmp_path / "candidate-table.md"
    result = run_script("candidate_table.py", "--input", str(write(tmp_path, screened(6))), "--output", str(output))
    payload = json.loads(result.stdout)
    assert payload["rows"] == 6
    assert payload["below_default_list"] is True
