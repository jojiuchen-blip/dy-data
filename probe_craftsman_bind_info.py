import json
import os
import sys
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent))

from src.dy_data.config import douyin_account_id, douyin_app_id, douyin_app_secret, path_value


OUT_DIR = path_value("field_probe_dir", env_name="FIELD_PROBE_DIR")
OUT_DIR.mkdir(parents=True, exist_ok=True)

APP_ID = douyin_app_id()
APP_SECRET = douyin_app_secret()
ACCOUNT_ID = douyin_account_id()

API_URL = "https://open.douyin.com/goodlife/v2/craftsman_openapi/merchat/craftsman/bind_info/all/"


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


def main() -> None:
    token = get_client_token()
    headers = {
        "access-token": token,
        "content-type": "application/json",
        "Rpc-Transit-Life-Account": ACCOUNT_ID,
    }
    params = {"account_id": ACCOUNT_ID, "cursor": "0", "size": "20"}
    response = requests.get(API_URL, headers=headers, params=params, timeout=30)
    try:
        body = response.json()
    except Exception:
        body = {"raw_text": response.text}
    result = {
        "status_code": response.status_code,
        "url": response.url,
        "body": body,
    }
    path = OUT_DIR / "craftsman_bind_info_probe.json"
    path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"path": str(path), **result}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
