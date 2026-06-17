from __future__ import annotations

import re
import unicodedata


_DASH_CHARS = {"-", "‐", "‑", "‒", "–", "—", "―", "−", "﹣", "－"}


def normalize_owner_account_name(value: str | None) -> str:
    normalized = unicodedata.normalize("NFKC", value or "")
    normalized = "".join("—" if char in _DASH_CHARS else char for char in normalized)
    normalized = re.sub(r"—+", "—", normalized)
    normalized = re.sub(r"\s+", "", normalized)
    return normalized.casefold()
