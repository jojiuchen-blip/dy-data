from pathlib import Path


WEB_SRC = Path(__file__).resolve().parents[1] / "apps" / "web" / "src"


def read_source(relative_path: str) -> str:
    return (WEB_SRC / relative_path).read_text(encoding="utf-8")


def test_clue_center_does_not_display_douyin_follow_store_as_our_assignment() -> None:
    source = read_source("pages/ClueCenterPage.tsx")

    assert "线索当前归属" not in source
    assert "分配门店" not in source
    assert "归属门店" not in source
    assert "current_assigned_store_name" not in source
    assert "assigned_store_name" not in source
