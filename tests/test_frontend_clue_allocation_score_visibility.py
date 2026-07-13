from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _read(relative_path: str) -> str:
    return (ROOT / "apps" / "web" / "src" / relative_path).read_text(encoding="utf-8")


def test_normal_admin_loads_and_renders_store_score_snapshots() -> None:
    page_source = _read("pages/AdminClueAllocationPage.tsx")
    load_start = page_source.index("const load = async")
    load_end = page_source.index("setScoreData", load_start)
    load_source = page_source[load_start:load_end]

    assert "fetchClueAllocationStoreScores()," in load_source
    assert "isHighestAdmin ? fetchClueAllocationStoreScores()" not in load_source

    score_table = page_source.index("columns={scoreColumns}")
    score_section_start = page_source.rfind("<section", 0, score_table)
    score_section_end = page_source.index("</section>", score_table)
    score_section = page_source[score_section_start:score_section_end]

    assert "rows={scoreData?.rows ?? []}" in score_section
    assert "{isHighestAdmin ? (" not in score_section
    assert "scoreData?.run" in score_section
