import { useState } from "react";
import { fetchCommissionRulesSummary } from "../api/client";
import { useApiResource } from "../hooks/useApiResource";
import { formatPercent } from "../utils/format";
import { SolarIcon } from "./SolarIcon";

export function CommissionRulesButton() {
  const [open, setOpen] = useState(false);
  const resource = useApiResource(fetchCommissionRulesSummary, []);
  const rules = resource.data?.data;
  const accountText = rules?.non_commission_owner_accounts.length
    ? rules.non_commission_owner_accounts.join("、")
    : "暂无已配置的不分佣账号";
  const commissionSkus = rules?.commission_skus ?? [];

  return (
    <div className="commission-rules">
      <button
        aria-controls="commission-rules-popover"
        aria-expanded={open}
        className="ghost-button commission-rules__button"
        onClick={() => setOpen((current) => !current)}
        type="button"
      >
        <SolarIcon name="rules" size={15} />
        分佣规则
      </button>
      {open ? (
        <div
          aria-labelledby="commission-rules-title"
          className="commission-rules__popover"
          id="commission-rules-popover"
          role="region"
        >
          <div className="commission-rules__header">
            <h2 id="commission-rules-title">分佣规则</h2>
            <button
              aria-label="关闭分佣规则"
              className="icon-button"
              onClick={() => setOpen(false)}
              type="button"
            >
              <SolarIcon name="close" size={18} />
            </button>
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
                <table className="data-table commission-rules__table">
                  <thead>
                    <tr>
                      <th>商品编码</th>
                      <th>商品名称</th>
                      <th>销售店分佣比例</th>
                    </tr>
                  </thead>
                  <tbody>
                    {commissionSkus.length ? (
                      commissionSkus.map((row) => (
                        <tr key={row.sku_id}>
                          <td className="mono-cell">{row.sku_id}</td>
                          <td>{row.product_name || "-"}</td>
                          <td>{formatPercent(row.commission_rate)}</td>
                        </tr>
                      ))
                    ) : (
                      <tr>
                        <td colSpan={3}>暂无分佣比例不为 0% 的商品 SKU</td>
                      </tr>
                    )}
                  </tbody>
                </table>
              </div>
            </>
          )}
        </div>
      ) : null}
    </div>
  );
}
