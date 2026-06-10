import json
from pathlib import Path

from src.dy_data.config import path_value

PATH = path_value("field_probe_dir") / "craftsman_single_nickname_probe.json"


def main() -> None:
    data = json.loads(PATH.read_text(encoding="utf-8"))
    rows = []
    for name, result in data.items():
        body = result.get("body") or {}
        payload = body.get("data") or {}
        items = payload.get("openapi_merchat_craftsman_info") or []
        rows.append(
            {
                "probe": name,
                "status": result.get("status"),
                "error_code": payload.get("error_code", body.get("extra", {}).get("error_code")),
                "description": payload.get("description", body.get("extra", {}).get("description")),
                "count": len(items),
                "first_nickname": (items[0] or {}).get("nickname") if items else "",
                "url": result.get("url"),
            }
        )
    print(json.dumps(rows, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
