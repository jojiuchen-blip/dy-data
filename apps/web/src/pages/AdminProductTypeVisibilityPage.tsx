import { useEffect, useMemo, useState } from "react";
import {
  ApiRequestError,
  fetchProductTypeVisibility,
  saveProductTypeVisibility,
} from "../api/client";
import { Button } from "../components/Button";
import { SelectField } from "../components/FormControls";
import { SolarIcon } from "../components/SolarIcon";
import type { ProductTypeVisibilityData } from "../types/dashboard";
import { formatDateTime } from "../utils/format";

function normalizeProductTypes(values: string[]): string[] {
  return Array.from(
    new Set(
      values
        .map((value) => value.trim())
        .filter((value) => value && value !== "all"),
    ),
  ).sort((left, right) => left.localeCompare(right, "zh-Hans-CN"));
}

function statusLabel(data: ProductTypeVisibilityData | null): string {
  if (!data) {
    return "-";
  }
  if (!data.enabled) {
    return "展示全部商品类型";
  }
  if (!data.visible_product_types.length) {
    return "已启用，但尚未选择商品类型";
  }
  if (data.visible_product_scopes.length) {
    return `仅展示 ${data.visible_product_scopes.length} 个产品范围 / ${data.visible_product_types.length} 个商品类型`;
  }
  return `仅展示 ${data.visible_product_types.length} 个商品类型`;
}

export function AdminProductTypeVisibilityPage() {
  const [data, setData] = useState<ProductTypeVisibilityData | null>(null);
  const [enabled, setEnabled] = useState(false);
  const [selectedProductScopes, setSelectedProductScopes] = useState<string[]>([]);
  const [selectedProductTypes, setSelectedProductTypes] = useState<string[]>([]);
  const [defaultProductType, setDefaultProductType] = useState("all");
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [statusText, setStatusText] = useState("");

  const selectedSet = useMemo(
    () => new Set(selectedProductTypes),
    [selectedProductTypes],
  );
  const selectedScopeSet = useMemo(
    () => new Set(selectedProductScopes),
    [selectedProductScopes],
  );
  const availableProductScopes = useMemo(
    () => normalizeProductTypes(data?.available_product_scopes ?? []),
    [data],
  );
  const productScopeTypeMap = useMemo(
    () => data?.product_scope_type_map ?? {},
    [data],
  );
  const availableProductTypes = useMemo(
    () => normalizeProductTypes(data?.available_product_types ?? []),
    [data],
  );
  const scopedAvailableProductTypes = useMemo(() => {
    if (!selectedProductScopes.length) {
      return availableProductTypes;
    }
    const allowedTypes = new Set(
      selectedProductScopes.flatMap((productScope) => productScopeTypeMap[productScope] ?? []),
    );
    return availableProductTypes.filter((productType) => allowedTypes.has(productType));
  }, [availableProductTypes, productScopeTypeMap, selectedProductScopes]);
  const selectedCount = selectedProductTypes.length;
  const selectedScopeCount = selectedProductScopes.length;
  const defaultProductTypeHidden =
    enabled && defaultProductType !== "all" && !selectedSet.has(defaultProductType);
  const canSave = (!enabled || selectedCount > 0) && !defaultProductTypeHidden;
  const defaultProductTypeOptions = useMemo(
    () => [
      { value: "all", label: "全部产品" },
      ...scopedAvailableProductTypes.map((productType) => ({
        value: productType,
        label: productType,
      })),
    ],
    [scopedAvailableProductTypes],
  );

  const loadData = () => {
    setLoading(true);
    fetchProductTypeVisibility()
      .then((response) => {
        setData(response.data);
        setEnabled(response.data.enabled);
        setSelectedProductScopes(
          normalizeProductTypes(response.data.visible_product_scopes),
        );
        setSelectedProductTypes(
          normalizeProductTypes(response.data.visible_product_types),
        );
        setDefaultProductType(response.data.default_product_type || "all");
        setStatusText("");
      })
      .catch((error) => {
        if (error instanceof ApiRequestError && error.status === 401) {
          setStatusText("登录已过期，请重新登录后再配置商品口径。");
          return;
        }
        setStatusText("商品口径配置暂时无法读取。");
      })
      .finally(() => setLoading(false));
  };

  useEffect(() => {
    loadData();
  }, []);

  const pruneProductTypesForScopes = (
    productScopes: string[],
    productTypes: string[],
  ): string[] => {
    if (!productScopes.length) {
      return normalizeProductTypes(productTypes);
    }
    const allowedTypes = new Set(
      productScopes.flatMap((productScope) => productScopeTypeMap[productScope] ?? []),
    );
    return normalizeProductTypes(
      productTypes.filter((productType) => allowedTypes.has(productType)),
    );
  };

  const toggleProductScope = (productScope: string) => {
    setSelectedProductScopes((current) => {
      const nextScopes = current.includes(productScope)
        ? current.filter((value) => value !== productScope)
        : normalizeProductTypes([...current, productScope]);
      setSelectedProductTypes((currentTypes) => {
        const nextTypes = pruneProductTypesForScopes(nextScopes, currentTypes);
        if (defaultProductType !== "all" && !nextTypes.includes(defaultProductType)) {
          setDefaultProductType("all");
        }
        return nextTypes;
      });
      return nextScopes;
    });
  };

  const toggleProductType = (productType: string) => {
    setSelectedProductTypes((current) => {
      if (current.includes(productType)) {
        if (defaultProductType === productType) {
          setDefaultProductType("all");
        }
        return current.filter((value) => value !== productType);
      }
      return normalizeProductTypes([...current, productType]);
    });
  };

  const handleSave = async () => {
    if (!canSave) {
      setStatusText(
        defaultProductTypeHidden
          ? "默认显示范围必须属于已选择的可见商品类型。"
          : "启用商品口径限制时，至少选择一个商品类型。",
      );
      return;
    }
    setSaving(true);
    setStatusText("正在保存商品口径配置...");
    try {
      const response = await saveProductTypeVisibility({
        enabled,
        visible_product_scopes: selectedProductScopes,
        visible_product_types: selectedProductTypes,
        default_product_type: defaultProductType,
      });
      setData(response.data);
      setEnabled(response.data.enabled);
      setSelectedProductScopes(
        normalizeProductTypes(response.data.visible_product_scopes),
      );
      setSelectedProductTypes(
        normalizeProductTypes(response.data.visible_product_types),
      );
      setDefaultProductType(response.data.default_product_type || "all");
      setStatusText(
        response.data.enabled
          ? "商品口径已保存，线索中心和结算中心会立即按所选商品类型展示。"
          : "商品口径限制已停用，线索中心和结算中心会展示全部商品类型。",
      );
    } catch (error) {
      if (error instanceof ApiRequestError && error.status === 422) {
        setStatusText("商品口径保存失败，请确认默认显示范围属于可见商品类型。");
      } else if (error instanceof ApiRequestError && error.status === 401) {
        setStatusText("登录已过期，请重新登录后再保存。");
      } else {
        setStatusText("商品口径保存失败，请稍后重试。");
      }
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="admin-page">
      <section className="admin-header">
        <div>
          <h1>商品口径控制</h1>
          <p className="admin-muted">
            控制线索中心和结算中心展示哪些商品类型的数据，不改变分佣规则和历史数据。
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

      <section className="content-section product-visibility-panel">
        <div className="section-title">
          <div>
            <h2>展示口径</h2>
            <p>
              启用后，即使用户选择全部产品，系统也只统计下方勾选的商品类型。
            </p>
          </div>
          {loading ? <span className="source-pill">加载中</span> : null}
        </div>

        <div className="product-visibility-summary">
          <div>
            <span>当前状态</span>
            <strong>{statusLabel(data)}</strong>
            <small>
              更新人 {data?.updated_by || "-"} / 更新时间{" "}
              {formatDateTime(data?.updated_at)}
            </small>
          </div>
          <label className="filter-field checkbox-field product-visibility-toggle">
            <span>启用商品类型限制</span>
            <input
              checked={enabled}
              onChange={(event) => setEnabled(event.target.checked)}
              type="checkbox"
            />
          </label>
        </div>

        <div className="product-visibility-toolbar">
          <div>
            <SolarIcon name="filter" size={18} />
            <span>
              已选择 {selectedCount} / {scopedAvailableProductTypes.length}
            </span>
          </div>
          <div className="product-visibility-actions">
            <Button
              disabled={!scopedAvailableProductTypes.length}
              onClick={() => setSelectedProductTypes(scopedAvailableProductTypes)}
              type="button"
            >
              全部选择
            </Button>
            <Button
              disabled={!selectedCount}
              onClick={() => {
                setSelectedProductTypes([]);
                setDefaultProductType("all");
              }}
              type="button"
            >
              清空选择
            </Button>
          </div>
        </div>

        <div className="product-visibility-subsection">
          <div className="product-visibility-subtitle">
            <strong>产品范围</strong>
            <span>
              已选择 {selectedScopeCount} / {availableProductScopes.length}
            </span>
          </div>
          {availableProductScopes.length ? (
            <div
              className="product-type-option-grid"
              aria-label="可见产品范围"
            >
              {availableProductScopes.map((productScope) => {
                const checked = selectedScopeSet.has(productScope);
                return (
                  <label
                    className={`product-type-option ${checked ? "is-selected" : ""}`}
                    key={productScope}
                  >
                    <input
                      checked={checked}
                      onChange={() => toggleProductScope(productScope)}
                      type="checkbox"
                    />
                    <span>{productScope}</span>
                    {checked ? <SolarIcon name="check" size={16} /> : null}
                  </label>
                );
              })}
            </div>
          ) : (
            <div className="resource-panel">
              暂无可配置产品范围。请先确认 SKU 商品列表已有产品范围数据。
            </div>
          )}
        </div>

        <SelectField
          className="product-visibility-default"
          helperText="用户进入所有商品类型筛选器时，默认先展示这个范围；用户仍可手动切换。"
          label="默认显示范围"
          onChange={setDefaultProductType}
          options={defaultProductTypeOptions}
          value={defaultProductType}
        />

        <div className="product-visibility-subsection">
          <div className="product-visibility-subtitle">
            <strong>商品类型</strong>
            {selectedScopeCount ? <span>已按产品范围筛选</span> : null}
          </div>
          {scopedAvailableProductTypes.length ? (
            <div
              className="product-type-option-grid"
              aria-label="可见商品类型"
            >
              {scopedAvailableProductTypes.map((productType) => {
                const checked = selectedSet.has(productType);
                return (
                  <label
                    className={`product-type-option ${checked ? "is-selected" : ""}`}
                    key={productType}
                  >
                    <input
                      checked={checked}
                      onChange={() => toggleProductType(productType)}
                      type="checkbox"
                    />
                    <span>{productType}</span>
                    {checked ? <SolarIcon name="check" size={16} /> : null}
                  </label>
                );
              })}
            </div>
          ) : (
            <div className="resource-panel">
              暂无可配置商品类型。请先确认商品规则、订单明细或线索中心已有商品类型数据。
            </div>
          )}
        </div>

        <div className="product-visibility-save-row">
          <p>
            该配置保存后立即生效；排行榜、单店结算、订单明细、线索筛选和线索列表都会按此口径收口。
          </p>
          <Button
            disabled={saving || loading || !canSave}
            onClick={handleSave}
            type="button"
            variant="primary"
          >
            保存口径
          </Button>
        </div>
      </section>
    </div>
  );
}
