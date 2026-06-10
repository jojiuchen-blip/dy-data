from __future__ import annotations


TOKEN_URL = "https://open.douyin.com/oauth/client_token/"
ORDER_QUERY_URL = "https://open.douyin.com/goodlife/v1/trade/order/query/"
VERIFY_RECORD_QUERY_URL = "https://open.douyin.com/goodlife/v1/fulfilment/certificate/verify_record/query/"
REFUND_QUERY_URL = "https://open.douyin.com/goodlife/v1/akte/after_sale/order/query/"
SHOP_POI_QUERY_URL = "https://open.douyin.com/goodlife/v1/shop/poi/query/"


def douyin_headers(token: str, account_id: str) -> dict[str, str]:
    return {
        "access-token": token,
        "content-type": "application/json",
        "Rpc-Transit-Life-Account": account_id,
    }
