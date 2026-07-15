import { useState } from "react";
import { fetchCommissionRulesSummary } from "../api/client";
import { useApiResource } from "../hooks/useApiResource";
import type { CommissionRuleSkuSummary } from "../types/dashboard";
import { formatPercent } from "../utils/format";
import { Button, IconButton } from "./Button";
import { DataTable, type Column } from "./DataTable";

export function CommissionRulesButton() {
  const [open, setOpen] = useState(false);
  const resource = useApiResource(fetchCommissionRulesSummary, []);
  const rules = resource.data?.data;
  const accountText = rules?.non_commission_owner_accounts.length
    ? rules.non_commission_owner_accounts.join("、")
    : "暂无已配置的不分佣账号";
  const commissionSkus = rules?.commission_skus ?? [];
  const columns: Column<CommissionRuleSkuSummary>[] = [
    {
      key: "sku",
      title: "商品编码",
      align: "left",
      render: (row) => <span className="mono-cell">{row.sku_id}</span>,
    },
    {
      key: "name",
      title: "商品名称",
      align: "left",
      render: (row) => row.product_name || "-",
    },
    {
      align: "right",
      key: "rate",
      title: "销售店分佣比例",
      render: (row) => formatPercent(row.commission_rate),
    },
  ];

  return (
    <div className="commission-rules">
      <Button
        aria-controls="commission-rules-popover"
        aria-expanded={open}
        className="commission-rules__button"
        icon="rules"
        onClick={() => setOpen((current) => !current)}
        size="sm"
        type="button"
        variant="secondary"
      >
        分佣规则
      </Button>
      {open ? (
        <div
          aria-labelledby="commission-rules-title"
          className="commission-rules__popover"
          id="commission-rules-popover"
          role="region"
        >
          <div className="commission-rules__header">
            <h2 id="commission-rules-title">分佣规则</h2>
            <IconButton
              icon="close"
              label="关闭分佣规则"
              onClick={() => setOpen(false)}
              type="button"
            />
          </div>
          {resource.loading ? (
            <p className="admin-muted">正在读取分佣规则...</p>
          ) : resource.error ? (
            <p className="admin-error">分佣规则暂时无法读取。</p>
          ) : (
            <>
              <p className="admin-muted">以下情况不参与分佣：</p>
              <ol className="commission-rules__list">
                <li>销售门店和核销门店相同，不产生跨店分佣。</li>
                <li>这些账号销售的订单不参与分佣：{accountText}。</li>
                <li>订单未匹配到销售门店，或核销记录未匹配到核销门店。</li>
                <li>订单、券或核销记录处于退款、撤销、关闭等无效状态。</li>
                <li>商品 SKU 未在管理后台配置为参与分账，或销售店分佣比例为 0%。</li>
              </ol>
              <div className="commission-rules__sku-header">
                <h3>当前参与分佣的商品 SKU</h3>
                <span>{commissionSkus.length} 个</span>
              </div>
              <div className="commission-rules__table-wrap">
                <DataTable
                  columns={columns}
                  emptyText="暂无分佣比例不为 0% 的商品 SKU"
                  rows={commissionSkus}
                  tableClassName="commission-rules__table"
                />
              </div>
            </>
          )}
        </div>
      ) : null}
    </div>
  );
}
