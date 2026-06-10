import json
import os
from pathlib import Path

import requests


OUT_DIR = Path(r"D:\app\抖音来客看板\field_probe")
OUT_DIR.mkdir(parents=True, exist_ok=True)

APP_ID = os.getenv("DOUYIN_APP_ID")
APP_SECRET = os.getenv("DOUYIN_APP_SECRET")
ACCOUNT_ID = os.getenv("DOUYIN_ACCOUNT_ID", "7372082031255128115")

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
