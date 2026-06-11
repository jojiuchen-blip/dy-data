import json
import os
import sys
from pathlib import Path

import requests

sys.path.insert(0, str(next(p for p in Path(__file__).resolve().parents if (p / "src").exists())))

from src.dy_data.config import douyin_app_id, douyin_app_secret, path_value


OUT_DIR = path_value("field_probe_dir", env_name="FIELD_PROBE_DIR")
OUT_DIR.mkdir(parents=True, exist_ok=True)

APP_ID = douyin_app_id()
APP_SECRET = douyin_app_secret()


def get_client_token() -> str:
    response = requests.post(
        "https://open.douyin.com/oauth/client_token/",
        json={
            "client_key": APP_ID,
            "client_secret": APP_SECRET,
            "grant_type": "client_credential",
        },
        timeout=20,
    )
    data = response.json()
    token = data.get("data", {}).get("access_token")
    if not token:
        raise RuntimeError(json.dumps(data, ensure_ascii=False))
    return token


def call_get(url: str, token: str, params: dict) -> dict:
    response = requests.get(
        url,
        headers={"content-type": "application/json", "access-token": token},
        params=params,
        timeout=30,
    )
    try:
        body = response.json()
    except Exception:
        body = {"raw_text": response.text}
    return {"status_code": response.status_code, "url": response.url, "body": body}


def main() -> None:
    token = get_client_token()
    results = {}

    for relation_type in ["brand", "cooperation", "employee"]:
        results[f"relation_{relation_type}"] = call_get(
            "https://open.douyin.com/api/apps/v1/capacity/query_aweme_relation_list/",
            token,
            {"type": relation_type, "page_num": 1, "page_size": 10},
        )

    for capacity_key in ["video_self_mount", "live_self_mount"]:
        results[f"self_mount_{capacity_key}"] = call_get(
            "https://developer.toutiao.com/api/apps/v1/capacity/query_self_mount_user_list",
            token,
            {"capacity_key": capacity_key, "page_num": 1, "page_size": 10},
        )

    path = OUT_DIR / "aweme_bind_interface_probe.json"
    path.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"path": str(path), "results": results}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
