import { useEffect, useMemo, useState } from "react";
import {
  ApiRequestError,
  fetchAdminSession,
  fetchSkuRules,
  loginAdmin,
  logoutAdmin,
  saveSkuRules,
} from "../api/client";
import type { SkuProductCommissionRule } from "../types/dashboard";
import { formatInteger, formatPercent } from "../utils/format";

const PAGE_SIZE = 500;

type DraftRule = Required<
  Pick<
    SkuProductCommissionRule,
    | "sku_id"
    | "product_name"
    | "product_type"
    | "commission_rate"
    | "is_service_product"
    | "order_count"
    | "verified_coupon_count"
  >
>;

function normalizeRule(row: SkuProductCommissionRule): DraftRule {
  return {
    sku_id: row.sku_id,
    product_name: row.product_name ?? "",
    product_type: row.product_type ?? "",
    commission_rate: row.commission_rate ?? 0,
    is_service_product: row.is_service_product ?? true,
    order_count: row.order_count ?? 0,
    verified_coupon_count: row.verified_coupon_count ?? 0,
  };
}

function rateToInput(rate: number): string {
  return new Intl.NumberFormat("zh-CN", {
    maximumFractionDigits: 2,
  }).format(rate * 100);
}

function inputToRate(value: string): number {
  const numeric = Number(value.replace("%", "").trim());
  if (!Number.isFinite(numeric)) {
    return 0;
  }
  return Math.max(0, Math.min(100, numeric)) / 100;
}

function ruleKey(rule: DraftRule): string {
  return rule.sku_id;
}

export function AdminSkuRulesPage() {
  const [checkingSession, setCheckingSession] = useState(true);
  const [authenticated, setAuthenticated] = useState(false);
  const [password, setPassword] = useState("");
  const [loginError, setLoginError] = useState("");
  const [rows, setRows] = useState<DraftRule[]>([]);
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const [dirtyIds, setDirtyIds] = useState<Set<string>>(new Set());
  const [query, setQuery] = useState("");
  const [page, setPage] = useState(1);
  const [total, setTotal] = useState(0);
  const [loadingRows, setLoadingRows] = useState(false);
  const [saving, setSaving] = useState(false);
  const [statusText, setStatusText] = useState("");
  const [bulkProductType, setBulkProductType] = useState("");
  const [bulkRate, setBulkRate] = useState("10");

  useEffect(() => {
    let cancelled = false;
    fetchAdminSession()
      .then(() => {
        if (!cancelled) {
          setAuthenticated(true);
        }
      })
      .catch(() => {
        if (!cancelled) {
          setAuthenticated(false);
        }
      })
      .finally(() => {
        if (!cancelled) {
          setCheckingSession(false);
        }
      });

    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    if (!authenticated) {
      return;
    }
    let cancelled = false;
    setLoadingRows(true);
    fetchSkuRules({ page, pageSize: PAGE_SIZE, q: query.trim() })
      .then((response) => {
        if (cancelled) {
          return;
        }
        setRows(response.data.rows.map(normalizeRule));
        setTotal(response.data.pagination.total);
        setSelectedIds(new Set());
        setDirtyIds(new Set());
      })
      .catch((error) => {
        if (cancelled) {
          return;
        }
        if (error instanceof ApiRequestError && error.status === 401) {
          setAuthenticated(false);
          setStatusText("登录已过期，请重新输入管理密码。");
          return;
        }
        setStatusText("商品规则暂时无法读取。");
      })
      .finally(() => {
        if (!cancelled) {
          setLoadingRows(false);
        }
      });

    return () => {
      cancelled = true;
    };
  }, [authenticated, page, query]);

  const productTypeOptions = useMemo(
    () =>
      Array.from(
        new Set(rows.map((row) => row.product_type.trim()).filter(Boolean)),
      ).sort(),
    [rows],
  );
  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE));
  const allSelected =
    rows.length > 0 && rows.every((row) => selectedIds.has(ruleKey(row)));
  const dirtyRows = rows.filter((row) => dirtyIds.has(ruleKey(row)));

  const updateRow = (skuId: string, patch: Partial<DraftRule>) => {
    setRows((current) =>
      current.map((row) =>
        row.sku_id === skuId ? { ...row, ...patch } : row,
      ),
    );
    setDirtyIds((current) => new Set(current).add(skuId));
  };

  const toggleSelected = (skuId: string) => {
    setSelectedIds((current) => {
      const next = new Set(current);
      if (next.has(skuId)) {
        next.delete(skuId);
      } else {
        next.add(skuId);
      }
      return next;
    });
  };

  const toggleAll = () => {
    setSelectedIds(() =>
      allSelected ? new Set() : new Set(rows.map((row) => ruleKey(row))),
    );
  };

  const applyBulk = () => {
    const productType = bulkProductType.trim();
    const targetIds = selectedIds.size
      ? selectedIds
      : new Set(rows.map((row) => row.sku_id));
    if (!productType) {
      setStatusText("先填写要批量应用的商品类型。");
      return;
    }
    const nextRate = inputToRate(bulkRate);
    setRows((current) =>
      current.map((row) =>
        targetIds.has(row.sku_id)
          ? {
              ...row,
              commission_rate: nextRate,
              is_service_product: true,
              product_type: productType,
            }
          : row,
      ),
    );
    setDirtyIds((current) => {
      const next = new Set(current);
      targetIds.forEach((skuId) => next.add(skuId));
      return next;
    });
    setStatusText(
      `已批量应用到 ${formatInteger(targetIds.size)} 个 SKU，保存后生效。`,
    );
  };

  const handleLogin = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setLoginError("");
    try {
      await loginAdmin(password);
      setPassword("");
      setAuthenticated(true);
      setStatusText("");
    } catch {
      setLoginError("密码不正确，或后端未配置管理密码。");
    }
  };

  const handleLogout = async () => {
    await logoutAdmin().catch(() => undefined);
    setAuthenticated(false);
    setRows([]);
  };

  const handleSave = async () => {
    const invalid = dirtyRows.find((row) => !row.product_type.trim());
    if (invalid) {
      setStatusText(`SKU ${invalid.sku_id} 还没有商品类型，不能保存。`);
      return;
    }
    setSaving(true);
    setStatusText("正在保存规则并重建结算...");
    try {
      const response = await saveSkuRules(
        dirtyRows.map((row) => ({
          commission_rate: row.commission_rate,
          is_service_product: row.is_service_product,
          product_type: row.product_type.trim(),
          sku_id: row.sku_id,
        })),
      );
      setDirtyIds(new Set());
      setStatusText(
        `已保存 ${formatInteger(
          response.data.updated_count,
        )} 条规则，并重建 ${formatInteger(
          response.data.settlement_detail_count,
        )} 条结算明细。`,
      );
    } catch (error) {
      if (error instanceof ApiRequestError && error.status === 401) {
        setAuthenticated(false);
        setStatusText("登录已过期，请重新输入管理密码。");
      } else {
        setStatusText("保存失败，请稍后重试。");
      }
    } finally {
      setSaving(false);
    }
  };

  if (checkingSession) {
    return (
      <main className="admin-page">
        <section className="admin-login-panel">正在检查管理权限...</section>
      </main>
    );
  }

  if (!authenticated) {
    return (
      <main className="admin-page admin-page--centered">
        <form className="admin-login-panel" onSubmit={handleLogin}>
          <div>
            <p className="source-pill">独立管理入口</p>
            <h1>商品分账规则管理</h1>
            <p className="admin-muted">输入管理密码后进入。</p>
          </div>
          <label className="filter-field">
            <span>管理密码</span>
            <input
              autoFocus
              onChange={(event) => setPassword(event.target.value)}
              placeholder="请输入管理密码"
              type="password"
              value={password}
            />
          </label>
          {loginError ? <p className="admin-error">{loginError}</p> : null}
          <button className="primary-button" type="submit">
            进入管理页
          </button>
        </form>
      </main>
    );
  }

  return (
    <main className="admin-page">
      <section className="admin-header">
        <div>
          <p className="source-pill">独立管理入口</p>
          <h1>商品分账规则管理</h1>
          <p className="admin-muted">
            SKU 规则保存后会立即重建结算结果，三个看板会按新规则展示。
          </p>
        </div>
        <div className="admin-header-actions">
          <a className="ghost-button admin-link-button" href="/admin">
            返回后台首页
          </a>
          <button className="ghost-button" onClick={handleLogout} type="button">
            退出
          </button>
        </div>
      </section>

      <section className="content-section admin-tools">
        <label className="filter-field">
          <span>搜索 SKU / 商品名称</span>
          <input
            onChange={(event) => {
              setPage(1);
              setQuery(event.target.value);
            }}
            placeholder="输入 SKU ID 或商品名称"
            value={query}
          />
        </label>
        <label className="filter-field">
          <span>批量商品类型</span>
          <input
            list="product-type-options"
            onChange={(event) => setBulkProductType(event.target.value)}
            placeholder="例如：养车服务"
            value={bulkProductType}
          />
        </label>
        <label className="filter-field">
          <span>批量分账比例</span>
          <input
            inputMode="decimal"
            onChange={(event) => setBulkRate(event.target.value)}
            value={bulkRate}
          />
        </label>
        <button className="ghost-button" onClick={applyBulk} type="button">
          应用到选中
        </button>
        <button
          className="primary-button"
          disabled={dirtyRows.length === 0 || saving}
          onClick={handleSave}
          type="button"
        >
          保存并生效
        </button>
      </section>

      <datalist id="product-type-options">
        {productTypeOptions.map((productType) => (
          <option key={productType} value={productType} />
        ))}
      </datalist>

      {statusText ? <div className="resource-notice">{statusText}</div> : null}

      <section className="content-section">
        <div className="section-title">
          <div>
            <h2>SKU 商品列表</h2>
            <p>
              共 {formatInteger(total)} 个 SKU，当前页 {formatInteger(rows.length)} 个
            </p>
          </div>
          {loadingRows ? <span className="source-pill">加载中</span> : null}
        </div>

        <div className="table-wrap">
          <table className="data-table admin-rule-table">
            <thead>
              <tr>
                <th className="is-center">
                  <input
                    aria-label="选择当前页全部 SKU"
                    checked={allSelected}
                    onChange={toggleAll}
                    type="checkbox"
                  />
                </th>
                <th>SKU ID</th>
                <th>商品名称</th>
                <th>商品类型</th>
                <th className="is-right">分账比例</th>
                <th className="is-center">参与分账</th>
                <th className="is-right">订单数</th>
                <th className="is-right">核销券数</th>
                <th className="is-center">状态</th>
              </tr>
            </thead>
            <tbody>
              {rows.length === 0 ? (
                <tr>
                  <td className="empty-cell" colSpan={9}>
                    暂无 SKU 数据
                  </td>
                </tr>
              ) : (
                rows.map((row) => {
                  const dirty = dirtyIds.has(row.sku_id);
                  return (
                    <tr key={row.sku_id}>
                      <td className="is-center">
                        <input
                          aria-label={`选择 SKU ${row.sku_id}`}
                          checked={selectedIds.has(row.sku_id)}
                          onChange={() => toggleSelected(row.sku_id)}
                          type="checkbox"
                        />
                      </td>
                      <td className="mono-cell">{row.sku_id}</td>
                      <td>{row.product_name || "-"}</td>
                      <td>
                        <input
                          className="table-input"
                          list="product-type-options"
                          onChange={(event) =>
                            updateRow(row.sku_id, {
                              product_type: event.target.value,
                            })
                          }
                          placeholder="输入商品类型"
                          value={row.product_type}
                        />
                      </td>
                      <td className="is-right">
                        <input
                          className="table-input table-input--number"
                          inputMode="decimal"
                          onChange={(event) =>
                            updateRow(row.sku_id, {
                              commission_rate: inputToRate(event.target.value),
                            })
                          }
                          value={rateToInput(row.commission_rate)}
                        />
                      </td>
                      <td className="is-center">
                        <input
                          checked={row.is_service_product}
                          onChange={(event) =>
                            updateRow(row.sku_id, {
                              is_service_product: event.target.checked,
                            })
                          }
                          type="checkbox"
                        />
                      </td>
                      <td className="is-right">{formatInteger(row.order_count)}</td>
                      <td className="is-right">
                        {formatInteger(row.verified_coupon_count)}
                      </td>
                      <td className="is-center">
                        <span className="status-chip">
                          {dirty
                            ? "待保存"
                            : row.product_type
                              ? formatPercent(row.commission_rate)
                              : "未配置"}
                        </span>
                      </td>
                    </tr>
                  );
                })
              )}
            </tbody>
          </table>
        </div>

        <div className="pagination-controls">
          <span className="pagination-controls__summary">
            第 {formatInteger(page)} / {formatInteger(totalPages)} 页
          </span>
          <div className="pagination-controls__actions">
            <button
              className="ghost-button"
              disabled={page <= 1}
              onClick={() => setPage((current) => Math.max(1, current - 1))}
              type="button"
            >
              上一页
            </button>
            <button
              className="ghost-button"
              disabled={page >= totalPages}
              onClick={() =>
                setPage((current) => Math.min(totalPages, current + 1))
              }
              type="button"
            >
              下一页
            </button>
          </div>
        </div>
      </section>
    </main>
  );
}
