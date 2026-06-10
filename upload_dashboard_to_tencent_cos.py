import os
import sys
from pathlib import Path


DASHBOARD_HTML = Path(r"D:\app\抖音来客看板\dashboard\index.html")


def required_env(name: str) -> str:
    value = os.getenv(name, "").strip()
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
    key = os.getenv("TENCENT_COS_KEY", "index.html").strip().lstrip("/") or "index.html"
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
        CacheControl=os.getenv("TENCENT_COS_CACHE_CONTROL", "no-cache, max-age=60"),
    )
    print(f"已上传：{dashboard_html} -> cos://{bucket}/{key}")


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(f"上传失败：{error}", file=sys.stderr)
        raise
