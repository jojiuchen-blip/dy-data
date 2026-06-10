import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from src.dy_data.config import path_value, tencent_value


DASHBOARD_HTML = path_value("tencent_dashboard_html")


def required_env(name: str) -> str:
    cos_key = {
        "TENCENT_SECRET_ID": "secret_id",
        "TENCENT_SECRET_KEY": "secret_key",
        "TENCENT_COS_REGION": "region",
        "TENCENT_COS_BUCKET": "bucket",
    }.get(name)
    value = str(tencent_value(name, cos_key, default="") if cos_key else os.getenv(name, "")).strip()
    if not value:
        raise RuntimeError(f"缺少环境变量：{name}")
    return value


def main() -> None:
    try:
        from qcloud_cos import CosConfig, CosS3Client
    except ImportError as exc:
        raise RuntimeError(
            "缺少腾讯云 COS Python SDK。请先运行："
            "D:\\app\\抖音来客看板\\runtime\\python\\python.exe -m pip install cos-python-sdk-v5"
        ) from exc

    secret_id = required_env("TENCENT_SECRET_ID")
    secret_key = required_env("TENCENT_SECRET_KEY")
    region = required_env("TENCENT_COS_REGION")
    bucket = required_env("TENCENT_COS_BUCKET")
    key = str(tencent_value("TENCENT_COS_KEY", "key", default="index.html")).strip().lstrip("/") or "index.html"
    dashboard_html = Path(os.getenv("TENCENT_DASHBOARD_HTML", str(DASHBOARD_HTML)))

    if not dashboard_html.exists():
        raise RuntimeError(f"看板文件不存在：{dashboard_html}")

    config = CosConfig(Region=region, SecretId=secret_id, SecretKey=secret_key)
    client = CosS3Client(config)
    client.upload_file(
        Bucket=bucket,
        LocalFilePath=str(dashboard_html),
        Key=key,
        EnableMD5=True,
        ContentType="text/html; charset=utf-8",
        CacheControl=str(tencent_value("TENCENT_COS_CACHE_CONTROL", "cache_control", default="no-cache, max-age=60")),
    )
    print(f"已上传：{dashboard_html} -> cos://{bucket}/{key}")


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(f"上传失败：{error}", file=sys.stderr)
        raise
