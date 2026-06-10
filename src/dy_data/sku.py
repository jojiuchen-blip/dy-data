from __future__ import annotations

from typing import Any


DEFAULT_SKU_TYPE_MAP: dict[str, str] = {
    "1834808062911500": "268保养",
    "1839843694054411": "268保养",
    "1836174558502924": "268保养",
    "1834807415534650": "168保养",
    "1836174232747016": "168保养",
    "1842945450213424": "漆面",
    "1859247916957723": "漆面",
    "1859251879725066": "漆面",
    "1838947657772048": "漆面",
    "1865042571753472": "蒸发箱清洗",
    "1865042831665155": "外循环清洗",
}


def normalize_sku_id(value: Any) -> str:
    if value in ("", None):
        return ""
    text = str(value).strip()
    if text.endswith(".0"):
        text = text[:-2]
    return text


def product_type_for_sku(sku_id: Any, sku_type_map: dict[str, str] | None = None) -> str:
    mapping = sku_type_map or DEFAULT_SKU_TYPE_MAP
    return mapping.get(normalize_sku_id(sku_id), "")
