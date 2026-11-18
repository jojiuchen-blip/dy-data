"""Chinese presentation for downloads, leaving machine export contracts intact."""

from __future__ import annotations

import csv
import re
from collections.abc import Iterable, Mapping
from datetime import date, datetime, timezone
from decimal import Decimal
from io import StringIO
from zoneinfo import ZoneInfo

from starlette.requests import Request


SHANGHAI_TZ = ZoneInfo("Asia/Shanghai")
FIELD_LABELS = {
    "invoice_id": "发票记录ID", "store_id": "门店ID", "store_name": "门店名称",
    "effective_sap_code": "有效SAP编码", "statement_id": "账单ID", "statement_month": "账期",
    "settlement_batch_month": "结算批次账期", "statement_amount_cent": "账单金额（元）",
    "confirmed_amount_cent": "已确认金额（元）", "invoice_number": "发票号码", "invoice_date": "开票日期",
    "invoice_amount_cent": "发票金额（元）", "status": "开票状态", "rejection_reason": "驳回原因",
    "registered_at": "登记时间", "factory_deduction_date": "厂家扣款日期",
    "factory_deduction_amount_cent": "厂家扣款金额（元）", "processing_status": "处理状态",
    "statement_entry_id": "账单明细ID", "sap_code": "SAP编码", "billing_store_id": "结算门店ID",
    "billing_store_name": "结算门店名称", "service_store_name": "服务门店名称", "fee_direction": "费用方向",
    "order_id": "订单ID", "coupon_id": "券ID", "order_status": "订单状态", "coupon_status": "券状态",
    "product_name": "商品名称", "product_type": "商品类型", "sku_id": "SKU ID", "sku_name": "SKU名称",
    "sale_channel": "销售渠道", "sale_store_id": "销售门店ID", "sale_store_name": "销售门店名称",
    "verify_store_id": "核销门店ID", "verify_store_name": "核销门店名称", "sale_time": "销售时间",
    "verify_time": "核销时间", "received_amount_cent": "订单实收金额（元）",
    "frozen_fee_base_cent": "冻结计费基数（元）", "actual_fee_rate": "实际费率",
    "frozen_fee_amount_cent": "冻结费用金额（元）", "refund_time": "退款时间",
    "adjustment_type": "调整类型", "row_type": "明细类型", "submitted_at": "提交时间",
    "invoice_status": "开票状态", "settled_at": "结算时间", "settlement_date": "结算日期",
    "imported_at": "导入时间", "settlement_status": "结算状态",
    "store_maintained_sap_code": "门店维护SAP编码", "finance_imported_sap_code": "财务导入SAP编码",
    "effective_sap_version": "有效SAP版本", "effective_sap_updated_by": "最近操作人",
    "effective_sap_updated_at": "最近更新时间", "statement_total_cent": "账单总额（元）",
    "pending_invoice_amount_cent": "待开票金额（元）", "issued_amount_cent": "已开票金额（元）",
    "settled_or_deducted_amount_cent": "已结算或扣款金额（元）", "discrepancy_id": "差异记录ID",
    "sap_status": "SAP差异处理状态", "discrepancy_detected_at": "差异发现时间",
    "dispute_id": "异议ID", "dispute_type": "异议类型", "disputed_amount_cent": "异议金额（元）",
    "description": "异议说明", "contact_name": "联系人", "contact_phone_masked": "联系电话（脱敏）",
    "linked_order_count": "关联订单数", "linked_order_ids": "关联订单ID", "resolution_note": "处理说明",
    "result_statement_id": "处理结果账单ID", "owner_account_id": "销售账号ID",
    "owner_account_name": "销售账号名称", "sale_store_subject_name": "销售门店认证主体",
    "verify_store_subject_name": "核销门店认证主体", "is_verified": "是否核销",
    "relation_type": "销售核销关系", "is_commissionable": "是否参与分佣",
    "is_refund_excluded": "是否因退款排除", "paid_amount_cent": "订单实付金额（元）",
    "commission_rate": "佣金费率", "receivable_commission_cent": "应收佣金（元）",
    "payable_commission_cent": "应付佣金（元）",
    "skuName": "SKU名称", "skuId": "SKU ID", "productType": "商品类型",
    "promotionServiceFeeRate": "推广服务费率", "managementServiceFeeRate": "管理服务费率",
    "validationStatus": "校验状态", "errorFields": "错误字段", "errorMessages": "错误说明",
    "createdRuleVersion": "生成规则版本",
}
CHINESE_COLUMN_KEYS = {
    "费用方向": "fee_direction", "产品范围": "product_scope", "商品类型": "product_type",
    "账单状态": "statement_status", "原始基数": "original_base_cent", "调整基数": "adjustment_base_cent",
    "净基数": "adjusted_net_base_cent", "原始费用": "original_fee_cent", "调整费用": "adjustment_fee_cent",
    "调整后净额": "adjusted_net_fee_cent", "原始发生月份": "original_business_month",
    "销售月份": "sale_month", "核销月份": "verify_month", "调整入账月份": "adjustment_posting_month",
    "规则匹配日": "rule_match_date", "订单ID": "order_id", "券ID": "coupon_id", "SKU ID": "sku_id",
    "month": "statement_month",
}
VALUE_LABELS = {
    "PENDING_INVOICE": "待开票", "SUBMITTED_PENDING_FACTORY_REVIEW": "已提交待厂家审核",
    "APPROVED_SETTLED": "审核通过已结算", "REJECTED_REUPLOAD": "已驳回待重传",
    "PROMOTION": "推广服务费", "MANAGEMENT": "管理服务费", "GENERATING": "生成中",
    "PENDING_CONFIRMATION": "待确认", "CONFIRMED": "已确认", "LOCKED": "已锁账",
    "REVOKED": "已撤销", "PREVIEW": "预览", "SETTLED": "已结算", "UNSETTLED": "未结算",
    "ORIGINAL": "原始费用", "ADJUSTMENT": "调整费用", "REFUND": "退款调整",
    "CANCEL": "取消调整", "CANCELLATION": "取消调整", "CORRECTION": "更正调整",
    "REVERIFY": "重核销调整", "PENDING": "待处理", "IN_REVIEW": "审核中",
    "PENDING_ADMIN_APPROVAL": "待管理员审批", "ACCEPTED_WITH_ADJUSTMENT": "已受理并调整",
    "REJECTED": "已拒绝", "WITHDRAWN": "已撤回", "CORRECTED": "已更正",
    "RATE_ERROR": "费率错误", "DATA_MISSING": "数据缺失", "AMOUNT_ERROR": "金额错误", "OTHER": "其他",
    "FINANCE_ACTION_REQUIRED": "待财务处理", "MATCHED": "一致", "UNCONFIRMED": "待确认",
    "RED_FLUSHED": "已红冲", "VOIDED": "已作废", "ACTIVE": "有效", "SUPERSEDED": "已被后续版本替代",
    "VALID": "校验通过", "INVALID": "校验失败", "COMMITTED": "已提交", "COMMIT_FAILED": "提交失败",
    "SUBMITTED": "已提交", "PENDING_SUBMISSION": "待提交", "PENDING_STATEMENT": "待生成账单",
    "PENDING_STORE_CONFIRMATION": "待门店确认", "VERIFY_CANCEL": "核销取消调整", "DISPUTE": "异议调整",
    "PAID": "已支付", "VERIFIED": "已核销", "USED": "已核销", "COMPLETED": "已完成",
    "REFUNDED": "已退款", "CANCELLED": "已取消", "CANCELED": "已取消", "CLOSED": "已关闭",
    "active": "履约中", "fulfilling": "履约中", "paid": "履约中", "converted": "已核销",
    "fulfilled": "已核销", "verified": "已核销", "refunded": "已退款", "refund": "已退款",
    "cancelled": "已关闭", "canceled": "已关闭", "closed": "已关闭",
    "LIVE": "直播", "live": "直播", "SHORT_VIDEO": "短视频", "short_video": "短视频",
    "AFFILIATE": "分销", "affiliate": "分销",
    "all": "全部产品", "ALL": "全部产品", "tire": "轮胎", "TIRES": "轮胎", "TIRE": "轮胎",
    "SERVICE": "服务", "service": "服务", "SELF_SOLD_SELF_VERIFIED": "本店销售本店核销",
    "SELF_SOLD_OTHER_VERIFIED": "本店销售他店核销", "OTHER_SOLD_SELF_VERIFIED": "他店销售本店核销",
    "same_store": "同店销售核销", "cross_store": "跨店销售核销", "unverified": "未核销",
    "PARTIAL_REFUND": "部分退款调整", "FULL_REFUND": "全额退款调整",
    "VERIFY_CANCELLED": "核销取消调整", "MANUAL_CORRECTION": "人工更正",
    "DATA_QUALITY_BLOCKED": "数据质量异常", "BLOCKED": "异常阻断", "ADJUSTED": "已调整",
}
ENUM_FIELDS = {
    "status", "invoice_status", "processing_status", "fee_direction", "order_status", "coupon_status",
    "sale_channel", "adjustment_type", "row_type", "settlement_status", "sap_status", "dispute_type",
    "statement_status", "product_scope", "product_type", "relation_type", "validationStatus",
}
FILE_LABELS = {
    "finance-promotion-invoices": "推广服务费开票记录", "finance-management-invoices": "管理服务费开票记录",
    "finance-order-details": "财务订单明细", "finance-stores": "门店基础信息",
    "finance-sap-discrepancies": "SAP编码差异", "finance-disputes": "结算异议",
    "order-fee-details": "订单费用明细", "order-details": "订单分佣明细",
    "finance-import-errors": "财务导入错误明细", "douyin-ranking": "抖音账号榜单",
}


def chinese_download(request: Request) -> bool:
    """Read the explicit presentation option without changing legacy clients."""
    return request.query_params.get("locale", "").lower() == "zh-cn"


def spreadsheet_text(value: object, *, identifier: bool = False) -> str:
    """Protect text cells and long identifiers when opened in spreadsheets."""
    text = "" if value is None else str(value)
    stripped = text.lstrip()
    if stripped.startswith(("=", "+", "-", "@")) or text.startswith(("\t", "\r", "\n")):
        return "'" + text
    if identifier and re.fullmatch(r"\d+", text) and (len(text) > 15 or text.startswith("0")):
        return "'" + text
    return text


def chinese_date(value: object, *, month: bool = False) -> str:
    """Format stored UTC instants in Shanghai and retain date-only semantics."""
    if value is None or value == "":
        return ""
    text = str(value)
    if month:
        return re.sub(r"(\d{4})-(\d{2})", r"\1年\2月", text)
    if isinstance(value, datetime) or re.match(r"\d{4}-\d{2}-\d{2}[T ]", text):
        try:
            parsed = value if isinstance(value, datetime) else datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            return spreadsheet_text(text)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(SHANGHAI_TZ).strftime("%Y年%m月%d日 %H:%M:%S")
    if isinstance(value, date) or re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
        return re.sub(r"(\d{4})-(\d{2})-(\d{2})", r"\1年\2月\3日", text)
    return spreadsheet_text(text)


def localized_header(field: str, *, context: str = "", label: str | None = None) -> str:
    """Label the column using its business meaning and monetary unit."""
    key = CHINESE_COLUMN_KEYS.get(field, field)
    if key == "statement_amount_cent" and context in {
        "finance-promotion-invoices", "finance-management-invoices",
    }:
        return {
            "finance-promotion-invoices": "推广费总额（元）",
            "finance-management-invoices": "管理费总额（元）",
        }[context]
    if field == "status" and context == "finance-disputes":
        return "异议状态"
    if key.endswith("_cent"):
        return FIELD_LABELS.get(key, (label or field).replace("（分）", "").replace("（元）", "") + "（元）")
    return FIELD_LABELS.get(key, label or field)


def localized_value(field: str, value: object, *, context: str = "", direction: str | None = None) -> str:
    """Format a presentation cell while preserving unknown business codes."""
    key = CHINESE_COLUMN_KEYS.get(field, field)
    if value is None or value == "":
        return ""
    if key.endswith("_cent"):
        return format(Decimal(str(value)) / Decimal(100), ".2f")
    if key in ENUM_FIELDS:
        text = str(value)
        if key == "validationStatus" and text in {"PENDING", "COMMITTED", "COMMIT_FAILED"}:
            return {"PENDING": "待校验", "COMMITTED": "已写入", "COMMIT_FAILED": "写入失败"}[text]
        if key in {"status", "invoice_status"} and text == "APPROVED_SETTLED" and (
            direction == "MANAGEMENT" or context == "finance-management-invoices"
        ):
            return "已开票"
        if text in VALUE_LABELS:
            return VALUE_LABELS[text]
        if re.search(r"[\u3400-\u9fff]", text):
            return spreadsheet_text(text)
        return "未知（" + spreadsheet_text(text) + "）"
    if key.startswith("is_"):
        return {"True": "是", "False": "否", "true": "是", "false": "否", "1": "是", "0": "否"}.get(str(value), "未知（" + spreadsheet_text(value) + "）")
    if key.endswith("month"):
        return chinese_date(value, month=True)
    if key.endswith(("_at", "_time", "_date")):
        return chinese_date(value)
    if key == "errorFields":
        return "|".join(FIELD_LABELS.get(item, item) for item in str(value).split("|"))
    return spreadsheet_text(value, identifier=key.endswith(("_id", "_ids", "_code", "_number")) or key == "skuId")


def localized_csv(
    fields: list[str],
    rows: Iterable[Mapping[str, object]],
    *,
    context: str = "",
    header_labels: dict[str, str] | None = None,
) -> str:
    """Render every selected source row with Chinese headings and safe text."""
    output = StringIO(newline="")
    writer = csv.writer(output)
    writer.writerow([localized_header(field, context=context, label=(header_labels or {}).get(field)) for field in fields])
    for row in rows:
        writer.writerow([
            localized_value(field, row.get(field), context=context, direction=row.get("fee_direction"))
            for field in fields
        ])
    return output.getvalue()


def translate_csv(content: str, *, context: str = "") -> str:
    """Localize an existing export without querying or recomputing its rows."""
    reader = csv.DictReader(StringIO(content.lstrip("\ufeff")))
    return localized_csv(reader.fieldnames or [], reader, context=context)


def download_filename(request: Request, prefix: str, generated: datetime, *, extension: str = ".csv") -> str:
    """Name a user file using its direction, selected month and Shanghai day."""
    if not chinese_download(request):
        return f"{prefix}-{generated.date().isoformat()}{extension}"
    title = FILE_LABELS.get(prefix, prefix)
    if prefix == "finance-order-details":
        direction = request.query_params.get("feeDirection")
        title = {"PROMOTION": "推广服务费订单明细", "MANAGEMENT": "管理服务费订单明细"}.get(direction, title)
    month = request.query_params.get("month")
    period = "_" + chinese_date(month, month=True) if month else ""
    if generated.tzinfo is None:
        generated = generated.replace(tzinfo=timezone.utc)
    return f"{title}{period}_{generated.astimezone(SHANGHAI_TZ):%Y年%m月%d日}{extension}"
