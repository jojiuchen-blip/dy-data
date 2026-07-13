import { useEffect, useMemo, useState } from "react";
import {
  ApiRequestError,
  fetchAdminSession,
  fetchNonCommissionOwnerAccounts,
  fetchSyncAdmin,
  fetchSkuRules,
  loginAdmin,
  lookupSkuRules,
  saveNonCommissionOwnerAccounts,
  saveSkuRules,
} from "../api/client";
import { Button } from "../components/Button";
import { StatusChip } from "../components/Chips";
import { DataTable, type Column } from "../components/DataTable";
import type { SkuProductCommissionRule, SkuRuleLookupData } from "../types/dashboard";
import { formatInteger, formatPercent } from "../utils/format";

const PAGE_SIZE = 500;
const MAX_LOOKUP_SKUS = 500;

type DraftRule = Required<
  Pick<
    SkuProductCommissionRule,
    | "sku_id"
    | "product_name"
    | "product_scope"
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
    product_scope: row.product_scope ?? "",
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

function parseSkuInput(value: string): string[] {
  return value
    .split(/[\s,，;；]+/)
    .map((item) => item.trim())
    .filter(Boolean);
}

function parseOwnerAccountInput(value: string): string[] {
  const seen = new Set<string>();
  return value
    .split(/[\n,，;；]+/)
    .map((item) => item.trim())
    .filter(Boolean)
    .filter((item) => {
      if (seen.has(item)) {
        return false;
      }
      seen.add(item);
      return true;
    });
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
  const [query, setQuery] = useState("");
  const [productScopeQuery, setProductScopeQuery] = useState("");
  const [page, setPage] = useState(1);
  const [total, setTotal] = useState(0);
  const [loadingRows, setLoadingRows] = useState(false);
  const [saving, setSaving] = useState(false);
  const [statusText, setStatusText] = useState("");
  const [bulkProductScope, setBulkProductScope] = useState("");
  const [bulkProductType, setBulkProductType] = useState("");
  const [bulkRate, setBulkRate] = useState("10");
  const [bulkIsServiceProduct, setBulkIsServiceProduct] = useState(true);
  const [rebuildJobId, setRebuildJobId] = useState("");
  const [lookupInput, setLookupInput] = useState("");
  const [lookupResult, setLookupResult] = useState<SkuRuleLookupData | null>(null);
  const [lookupSelectedIds, setLookupSelectedIds] = useState<Set<string>>(new Set());
  const [lookingUp, setLookingUp] = useState(false);
  const [selectedSkuMap, setSelectedSkuMap] = useState<Map<string, DraftRule>>(new Map());
  const [draftMap, setDraftMap] = useState<Map<string, DraftRule>>(new Map());
  const [nonCommissionAccountText, setNonCommissionAccountText] = useState("");
  const [nonCommissionAccountCount, setNonCommissionAccountCount] = useState(0);
  const [loadingNonCommissionAccounts, setLoadingNonCommissionAccounts] = useState(false);
  const [savingNonCommissionAccounts, setSavingNonCommissionAccounts] = useState(false);

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
    fetchSkuRules({
      page,
      pageSize: PAGE_SIZE,
      productScope: productScopeQuery.trim(),
      q: query.trim(),
    })
      .then((response) => {
        if (cancelled) {
          return;
        }
        setRows(response.data.rows.map(normalizeRule));
        setTotal(response.data.pagination.total);
        setSelectedIds(new Set());
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
  }, [authenticated, page, productScopeQuery, query]);

  useEffect(() => {
    if (!authenticated) {
      return;
    }
    let cancelled = false;
    setLoadingNonCommissionAccounts(true);
    fetchNonCommissionOwnerAccounts()
      .then((response) => {
        if (cancelled) {
          return;
        }
        const names = response.data.rows.map((row) => row.owner_account_name);
        setNonCommissionAccountText(names.join("\n"));
        setNonCommissionAccountCount(names.length);
      })
      .catch((error) => {
        if (cancelled) {
          return;
        }
        if (!handleAuthError(error)) {
          setStatusText("不分佣账号规则暂时无法读取。");
        }
      })
      .finally(() => {
        if (!cancelled) {
          setLoadingNonCommissionAccounts(false);
        }
      });

    return () => {
      cancelled = true;
    };
  }, [authenticated]);

  useEffect(() => {
    if (!authenticated || !rebuildJobId) {
      return;
    }

    let cancelled = false;
    const poll = () => {
      fetchSyncAdmin()
        .then((response) => {
          if (cancelled) {
            return;
          }
          const job = response.data.jobs.find((item) => item.job_id === rebuildJobId);
          if (!job || job.status === "queued" || job.status === "running") {
            setStatusText(`规则已保存，结算结果正在后台重建。任务编号：${rebuildJobId}`);
            return;
          }
          if (job.status === "success") {
            setStatusText(
              `结算结果已按新规则重建完成，共重建 ${formatInteger(job.success_count)} 条明细。`,
            );
            setRebuildJobId("");
            return;
          }
          setStatusText(
            `结算重建失败，请到“数据同步管理”查看任务日志。任务编号：${rebuildJobId}`,
          );
          setRebuildJobId("");
        })
        .catch((error) => {
          if (cancelled) {
            return;
          }
          if (error instanceof ApiRequestError && error.status === 401) {
            setAuthenticated(false);
            setStatusText("登录已过期，请重新输入管理密码。");
          }
        });
    };

    poll();
    const timer = window.setInterval(poll, 5000);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [authenticated, rebuildJobId]);

  const selectedRules = useMemo(
    () => Array.from(selectedSkuMap.values()),
    [selectedSkuMap],
  );
  const dirtyRows = useMemo(() => Array.from(draftMap.values()), [draftMap]);
  const effectiveSelectedRules = useMemo(
    () =>
      selectedRules.map((rule) => draftMap.get(rule.sku_id) ?? rule),
    [draftMap, selectedRules],
  );
  const lookupRows = useMemo(
    () => lookupResult?.rows.map(normalizeRule) ?? [],
    [lookupResult],
  );
  const productScopeOptions = useMemo(
    () =>
      Array.from(
        new Set(
          [...rows, ...selectedRules, ...lookupRows]
            .map((row) => row.product_scope.trim())
            .filter(Boolean),
        ),
      ).sort(),
    [lookupRows, rows, selectedRules],
  );
  const productTypeOptions = useMemo(
    () =>
      Array.from(
        new Set(
          [...rows, ...selectedRules, ...dirtyRows, ...lookupRows]
            .map((row) => row.product_type.trim())
            .filter(Boolean),
        ),
      ).sort(),
    [dirtyRows, lookupRows, rows, selectedRules],
  );
  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE));
  const allSelected =
    rows.length > 0 && rows.every((row) => selectedIds.has(ruleKey(row)));
  const allLookupSelected =
    lookupRows.length > 0 &&
    lookupRows.every((row) => lookupSelectedIds.has(ruleKey(row)));

  const handleAuthError = (error: unknown): boolean => {
    if (error instanceof ApiRequestError && error.status === 401) {
      setAuthenticated(false);
      setStatusText("登录已过期，请重新输入管理密码。");
      return true;
    }
    return false;
  };

  const addRulesToSelection = (rules: DraftRule[]) => {
    if (!rules.length) {
      return;
    }
    let added = 0;
    setSelectedSkuMap((current) => {
      const next = new Map(current);
      for (const rule of rules) {
        if (!next.has(rule.sku_id)) {
          next.set(rule.sku_id, rule);
          added += 1;
        }
      }
      return next;
    });
    setStatusText(
      added
        ? `已加入 ${formatInteger(added)} 个 SKU 到预选窗口。`
        : "这些 SKU 已在预选窗口中。",
    );
  };

  const handleLookup = async () => {
    const skuIds = parseSkuInput(lookupInput);
    if (!skuIds.length) {
      setStatusText("请先输入要查询的 SKU ID。");
      return;
    }
    if (skuIds.length > MAX_LOOKUP_SKUS) {
      setStatusText(`一次最多查询 ${formatInteger(MAX_LOOKUP_SKUS)} 个 SKU。`);
      return;
    }
    setLookingUp(true);
    setStatusText("");
    try {
      const response = await lookupSkuRules(skuIds);
      setLookupResult(response.data);
      setLookupSelectedIds(new Set(response.data.rows.map((row) => row.sku_id)));
      setStatusText(
        `已匹配 ${formatInteger(response.data.rows.length)} 个 SKU，未匹配 ${formatInteger(
          response.data.missing_sku_ids.length,
        )} 个。`,
      );
    } catch (error) {
      if (!handleAuthError(error)) {
        setStatusText("批量 SKU 查询失败，请稍后重试。");
      }
    } finally {
      setLookingUp(false);
    }
  };

  const addLookupSelection = () => {
    addRulesToSelection(
      lookupRows.filter((row) => lookupSelectedIds.has(row.sku_id)),
    );
  };

  const addPageSelection = () => {
    addRulesToSelection(rows.filter((row) => selectedIds.has(row.sku_id)));
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

  const toggleLookupSelected = (skuId: string) => {
    setLookupSelectedIds((current) => {
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

  const toggleAllLookup = () => {
    setLookupSelectedIds(() =>
      allLookupSelected
        ? new Set()
        : new Set(lookupRows.map((row) => ruleKey(row))),
    );
  };

  const removeSelectedSku = (skuId: string) => {
    if (
      draftMap.has(skuId) &&
      !window.confirm(`SKU ${skuId} 有未保存草稿，确定从预选窗口移除吗？`)
    ) {
      return;
    }
    setSelectedSkuMap((current) => {
      const next = new Map(current);
      next.delete(skuId);
      return next;
    });
    setDraftMap((current) => {
      const next = new Map(current);
      next.delete(skuId);
      return next;
    });
  };

  const clearPreselection = () => {
    if (!selectedSkuMap.size) {
      return;
    }
    if (
      dirtyRows.length > 0 &&
      !window.confirm("预选窗口中有未保存草稿，确定清空全部预选 SKU 吗？")
    ) {
      return;
    }
    setSelectedSkuMap(new Map());
    setDraftMap(new Map());
    setStatusText("已清空预选窗口。");
  };

  const applyBulk = () => {
    const productScope = bulkProductScope.trim();
    const productType = bulkProductType.trim();
    if (!selectedSkuMap.size) {
      setStatusText("请先把 SKU 加入预选窗口。");
      return;
    }
    if (!productType) {
      setStatusText("请先填写要批量应用的商品类型。");
      return;
    }
    const nextRate = inputToRate(bulkRate);
    setDraftMap((current) => {
      const next = new Map(current);
      for (const baseRule of selectedSkuMap.values()) {
        const currentRule = next.get(baseRule.sku_id) ?? baseRule;
        next.set(baseRule.sku_id, {
          ...currentRule,
          commission_rate: nextRate,
          is_service_product: bulkIsServiceProduct,
          product_scope: productScope || currentRule.product_scope,
          product_type: productType,
        });
      }
      return next;
    });
    setStatusText(
      `已为预选窗口中的 ${formatInteger(
        selectedSkuMap.size,
      )} 个 SKU 生成待保存规则。`,
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

  const handleSaveNonCommissionAccounts = async () => {
    const accounts = parseOwnerAccountInput(nonCommissionAccountText);
    const confirmed = window.confirm(
      `将保存 ${accounts.length} 个不参与分佣的订单归属账号，并触发后台重建结算结果。确定继续吗？`,
    );
    if (!confirmed) {
      return;
    }
    setSavingNonCommissionAccounts(true);
    setStatusText("正在保存不分佣账号规则，并准备后台重建结算结果...");
    try {
      const response = await saveNonCommissionOwnerAccounts(accounts);
      const names = response.data.rows.map((row) => row.owner_account_name);
      setNonCommissionAccountText(names.join("\n"));
      setNonCommissionAccountCount(names.length);
      setRebuildJobId(response.data.job_id);
      setStatusText(
        `已保存 ${formatInteger(
          response.data.updated_count,
        )} 个不分佣账号，结算重建已在后台开始。任务编号：${response.data.job_id}`,
      );
    } catch (error) {
      if (!handleAuthError(error)) {
        setStatusText("不分佣账号规则保存失败，请稍后重试。");
      }
    } finally {
      setSavingNonCommissionAccounts(false);
    }
  };

  const handleSave = async () => {
    const invalid = dirtyRows.find((row) => !row.product_type.trim());
    if (invalid) {
      setStatusText(`SKU ${invalid.sku_id} 还没有商品类型，不能保存。`);
      return;
    }
    if (!dirtyRows.length) {
      setStatusText("预选窗口中还没有待保存规则。");
      return;
    }
    const confirmed = window.confirm(
      `将保存 ${dirtyRows.length} 个预选 SKU 的规则，并触发后台重建结算结果。确定继续吗？`,
    );
    if (!confirmed) {
      return;
    }
    setSaving(true);
    setStatusText("正在保存规则，并准备后台重建结算结果...");
    try {
      const response = await saveSkuRules(
        dirtyRows.map((row) => ({
          commission_rate: row.commission_rate,
          is_service_product: row.is_service_product,
          product_type: row.product_type.trim(),
          sku_id: row.sku_id,
        })),
      );
      setSelectedSkuMap((current) => {
        const next = new Map(current);
        dirtyRows.forEach((row) => next.set(row.sku_id, row));
        return next;
      });
      setRows((current) =>
        current.map((row) => draftMap.get(row.sku_id) ?? row),
      );
      setDraftMap(new Map());
      setRebuildJobId(response.data.job_id);
      setStatusText(
        `已保存 ${formatInteger(
          response.data.updated_count,
        )} 条规则，结算重建已在后台开始。任务编号：${response.data.job_id}`,
      );
    } catch (error) {
      if (!handleAuthError(error)) {
        setStatusText("保存失败，请稍后重试。");
      }
    } finally {
      setSaving(false);
    }
  };

  const skuColumns: Column<SkuProductCommissionRule>[] = [
    {
      align: "center",
      key: "select",
      title: (
        <input
          aria-label="选择当前页全部 SKU"
          checked={allSelected}
          onChange={toggleAll}
          type="checkbox"
        />
      ),
      render: (row) => (
        <input
          aria-label={`选择 SKU ${row.sku_id}`}
          checked={selectedIds.has(row.sku_id)}
          onChange={() => toggleSelected(row.sku_id)}
          type="checkbox"
        />
      ),
    },
    {
      key: "sku",
      title: "SKU ID",
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
      key: "scope",
      title: "产品范围",
      render: (row) => (draftMap.get(row.sku_id) ?? row).product_scope || "-",
    },
    {
      key: "type",
      title: "商品类型",
      render: (row) => (draftMap.get(row.sku_id) ?? row).product_type || "未配置",
    },
    {
      align: "right",
      key: "rate",
      title: "分账比例",
      render: (row) => formatPercent((draftMap.get(row.sku_id) ?? row).commission_rate),
    },
    {
      align: "center",
      key: "service",
      title: "参与分账",
      render: (row) => ((draftMap.get(row.sku_id) ?? row).is_service_product ? "是" : "否"),
    },
    {
      align: "right",
      key: "orders",
      title: "订单数",
      render: (row) => formatInteger(row.order_count ?? 0),
    },
    {
      align: "right",
      key: "verified",
      title: "核销券数",
      render: (row) => formatInteger(row.verified_coupon_count ?? 0),
    },
    {
      align: "center",
      key: "status",
      title: "状态",
      render: (row) => {
        const selected = selectedSkuMap.has(row.sku_id);
        const dirty = draftMap.has(row.sku_id);
        const label = dirty
          ? "待保存"
          : selected
            ? "已预选"
            : row.product_type
              ? "已配置"
              : "未配置";
        const tone = dirty ? "warning" : selected || row.product_type ? "brand" : "neutral";
        return (
          <StatusChip tone={tone}>
            {label}
          </StatusChip>
        );
      },
    },
  ];

  if (checkingSession) {
    return (
      <div className="admin-page">
        <section className="admin-login-panel">正在检查管理权限...</section>
      </div>
    );
  }

  if (!authenticated) {
    return (
      <div className="admin-page admin-page--centered">
        <form className="admin-login-panel" onSubmit={handleLogin}>
          <div>
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
          {loginError ? (
            <p className="admin-error" role="alert">
              {loginError}
            </p>
          ) : null}
          <Button type="submit" variant="primary">
            进入管理页
          </Button>
        </form>
      </div>
    );
  }

  return (
    <div className="admin-page">
      <section className="admin-header">
        <div>
          <h1>商品分账规则管理</h1>
          <p className="admin-muted">
            先查询并预选 SKU，再对预选范围批量修改；保存后会写入规则表并后台重建结算结果。
          </p>
        </div>
      </section>

      {statusText ? (
        <div
          aria-atomic="true"
          aria-live="polite"
          className="resource-notice"
          role="status"
        >
          {statusText}
        </div>
      ) : null}

      <datalist id="product-type-options">
        {productTypeOptions.map((productType) => (
          <option key={productType} value={productType} />
        ))}
      </datalist>
      <datalist id="product-scope-options">
        {productScopeOptions.map((productScope) => (
          <option key={productScope} value={productScope} />
        ))}
      </datalist>

      <section className="content-section non-commission-rule-panel">
        <div className="section-title">
          <div>
            <h2>订单归属账号不分佣</h2>
            <p>
              每行填写一个订单归属账号。这些账号销售的订单不参与分佣，保存后会按新规则后台重建结算结果。
            </p>
          </div>
          <span className="source-pill">
            {loadingNonCommissionAccounts
              ? "读取中"
              : `当前 ${formatInteger(nonCommissionAccountCount)} 个`}
          </span>
        </div>
        <label className="filter-field">
          <span>不分佣账号列表</span>
          <textarea
            className="sku-lookup-input non-commission-account-input"
            onChange={(event) => setNonCommissionAccountText(event.target.value)}
            placeholder="例如：比亚迪汽车销售有限公司&#10;比亚迪汽车精品"
            rows={5}
            value={nonCommissionAccountText}
          />
        </label>
        <div className="admin-header-actions sku-action-row">
          <Button
            disabled={savingNonCommissionAccounts}
            onClick={handleSaveNonCommissionAccounts}
            type="button"
            variant="primary"
          >
            保存账号规则并重建
          </Button>
        </div>
      </section>

      <div className="sku-rule-workspace">
        <div className="sku-rule-main">
          <section className="content-section">
            <div className="section-title">
              <div>
                <h2>批量 SKU 查询</h2>
                <p>支持粘贴多个 SKU ID，使用换行、逗号、空格或分号分隔。</p>
              </div>
              {lookingUp ? <span className="source-pill">查询中</span> : null}
            </div>
            <label className="filter-field">
              <span>SKU ID 列表</span>
              <textarea
                className="sku-lookup-input"
                onChange={(event) => setLookupInput(event.target.value)}
                placeholder="例如：sku-001&#10;sku-002, sku-003"
                rows={4}
                value={lookupInput}
              />
            </label>
            <div className="admin-header-actions sku-action-row">
              <Button
                disabled={lookingUp}
                onClick={handleLookup}
                type="button"
                variant="primary"
              >
                精确查询 SKU
              </Button>
              <Button
                onClick={() => setLookupInput("")}
                type="button"
              >
                清空输入
              </Button>
              <Button
                disabled={lookupSelectedIds.size === 0}
                onClick={addLookupSelection}
                type="button"
              >
                加入预选
              </Button>
            </div>

            {lookupResult ? (
              <div className="sku-lookup-result">
                <div className="section-title">
                  <div>
                    <h2>查询结果</h2>
                    <p>
                      匹配 {formatInteger(lookupRows.length)} 个，未匹配{" "}
                      {formatInteger(lookupResult.missing_sku_ids.length)} 个，重复{" "}
                      {formatInteger(lookupResult.duplicate_sku_ids.length)} 个
                    </p>
                  </div>
                  {lookupRows.length ? (
                    <label className="pagination-controls__size">
                      <input
                        checked={allLookupSelected}
                        onChange={toggleAllLookup}
                        type="checkbox"
                      />
                      全选匹配项
                    </label>
                  ) : null}
                </div>
                {lookupRows.length ? (
                  <div className="sku-lookup-list">
                    {lookupRows.map((row) => (
                      <label className="sku-lookup-row" key={row.sku_id}>
                        <input
                          checked={lookupSelectedIds.has(row.sku_id)}
                          onChange={() => toggleLookupSelected(row.sku_id)}
                          type="checkbox"
                        />
                        <span className="mono-cell">{row.sku_id}</span>
                        <span>{row.product_name || "-"}</span>
                        <span>{row.product_type || "未配置"}</span>
                      </label>
                    ))}
                  </div>
                ) : (
                  <div className="resource-panel">没有匹配到 SKU。</div>
                )}
                {lookupResult.missing_sku_ids.length ? (
                  <p className="admin-muted">
                    未匹配：{lookupResult.missing_sku_ids.join("、")}
                  </p>
                ) : null}
                {lookupResult.duplicate_sku_ids.length ? (
                  <p className="admin-muted">
                    重复输入：{lookupResult.duplicate_sku_ids.join("、")}
                  </p>
                ) : null}
              </div>
            ) : null}
          </section>

          <section className="content-section admin-tools">
            <label className="filter-field">
              <span>产品范围</span>
              <input
                list="product-scope-options"
                onChange={(event) => {
                  setPage(1);
                  setProductScopeQuery(event.target.value);
                }}
                placeholder="输入或选择产品范围"
                value={productScopeQuery}
              />
            </label>
            <label className="filter-field">
              <span>浏览搜索 SKU / 商品名称</span>
              <input
                onChange={(event) => {
                  setPage(1);
                  setQuery(event.target.value);
                }}
                placeholder="输入 SKU ID 或商品名称"
                value={query}
              />
            </label>
            <Button
              disabled={selectedIds.size === 0}
              onClick={addPageSelection}
              type="button"
            >
              加入当前选中
            </Button>
          </section>

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

            <DataTable
              columns={skuColumns}
              emptyText={loadingRows ? "正在加载 SKU 数据..." : "暂无 SKU 数据"}
              rows={rows}
              state={loadingRows ? "loading" : "ready"}
              tableClassName="admin-rule-table"
            />

            <div className="pagination-controls">
              <span className="pagination-controls__summary">
                第 {formatInteger(page)} / {formatInteger(totalPages)} 页
              </span>
              <div className="pagination-controls__actions">
                <Button
                  disabled={page <= 1}
                  onClick={() => setPage((current) => Math.max(1, current - 1))}
                  type="button"
                >
                  上一页
                </Button>
                <Button
                  disabled={page >= totalPages}
                  onClick={() =>
                    setPage((current) => Math.min(totalPages, current + 1))
                  }
                  type="button"
                >
                  下一页
                </Button>
              </div>
            </div>
          </section>
        </div>

        <aside className="content-section sku-selection-drawer">
          <div className="section-title">
            <div>
              <h2>预选窗口</h2>
              <p>
                已预选 {formatInteger(selectedSkuMap.size)} 个，待保存{" "}
                {formatInteger(dirtyRows.length)} 个
              </p>
            </div>
            <Button
              disabled={selectedSkuMap.size === 0}
              onClick={clearPreselection}
              type="button"
            >
              清空
            </Button>
          </div>

          <div className="sku-bulk-editor">
            <label className="filter-field">
              <span>产品范围</span>
              <input
                list="product-scope-options"
                onChange={(event) => setBulkProductScope(event.target.value)}
                placeholder="从 SKU 商品列表选择"
                value={bulkProductScope}
              />
            </label>
            <label className="filter-field">
              <span>商品类型</span>
              <input
                list="product-type-options"
                onChange={(event) => setBulkProductType(event.target.value)}
                placeholder="从 SKU 商品列表选择"
                value={bulkProductType}
              />
            </label>
            <label className="filter-field">
              <span>批量分账比例（%）</span>
              <input
                inputMode="decimal"
                onChange={(event) => setBulkRate(event.target.value)}
                value={bulkRate}
              />
            </label>
            <label className="filter-field checkbox-field">
              <span>参与分账</span>
              <input
                checked={bulkIsServiceProduct}
                onChange={(event) => setBulkIsServiceProduct(event.target.checked)}
                type="checkbox"
              />
            </label>
            <Button
              disabled={selectedSkuMap.size === 0}
              onClick={applyBulk}
              type="button"
            >
              应用到预选 SKU
            </Button>
            <Button
              disabled={dirtyRows.length === 0 || saving}
              onClick={handleSave}
              type="button"
              variant="primary"
            >
              保存预选规则并重建
            </Button>
          </div>

          <div className="sku-selected-list">
            {effectiveSelectedRules.length ? (
              effectiveSelectedRules.map((row) => {
                const dirty = draftMap.has(row.sku_id);
                return (
                  <div
                    className={`sku-selected-item${dirty ? " sku-selected-item--dirty" : ""}`}
                    key={row.sku_id}
                  >
                    <div>
                      <strong className="mono-cell">{row.sku_id}</strong>
                      <p>{row.product_name || "-"}</p>
                    </div>
                    <dl>
                      <div>
                        <dt>产品范围</dt>
                        <dd>{row.product_scope || "-"}</dd>
                      </div>
                      <div>
                        <dt>商品类型</dt>
                        <dd>{row.product_type || "未配置"}</dd>
                      </div>
                      <div>
                        <dt>分账比例</dt>
                        <dd>{formatPercent(row.commission_rate)}</dd>
                      </div>
                      <div>
                        <dt>参与</dt>
                        <dd>{row.is_service_product ? "是" : "否"}</dd>
                      </div>
                    </dl>
                    <div className="sku-selected-item__footer">
                      <StatusChip tone={dirty ? "warning" : "brand"}>
                        {dirty ? "待保存" : "已预选"}
                      </StatusChip>
                      <Button
                        onClick={() => removeSelectedSku(row.sku_id)}
                        type="button"
                      >
                        移除
                      </Button>
                    </div>
                  </div>
                );
              })
            ) : (
              <div className="resource-panel">
                先查询或浏览 SKU，再把需要修改的 SKU 加入这里。
              </div>
            )}
          </div>
        </aside>
      </div>
    </div>
  );
}
