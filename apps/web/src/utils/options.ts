import type { FilterMetaData, SelectOption } from "../types/dashboard";

const ALL_PRODUCTS = "all";

function unique(values: string[]): string[] {
  return [...new Set(values.filter(Boolean))];
}

function ensureValue(values: string[], value?: string): string[] {
  if (!value || values.includes(value)) {
    return values;
  }
  return [value, ...values];
}

function productLabel(value: string): string {
  return value === ALL_PRODUCTS ? "全部产品" : value;
}

function productScopeLabel(value: string): string {
  return value === ALL_PRODUCTS ? "全部" : value;
}

export function defaultProductType(meta: FilterMetaData | undefined): string {
  return meta?.default_product_type?.trim() || ALL_PRODUCTS;
}

export function productScopeOptions(
  meta: FilterMetaData | undefined,
  currentValue = ALL_PRODUCTS,
): SelectOption[] {
  const values = ensureValue(
    unique([ALL_PRODUCTS, ...(meta?.product_scopes ?? [])]),
    currentValue,
  );

  return values.map((value) => ({
    value,
    label: productScopeLabel(value),
  }));
}

export function productOptions(
  meta: FilterMetaData | undefined,
  currentValue = ALL_PRODUCTS,
): SelectOption[] {
  const values = ensureValue(
    unique([ALL_PRODUCTS, ...(meta?.product_types ?? [])]),
    currentValue,
  );

  return values.map((value) => ({
    value,
    label: productLabel(value),
  }));
}

export function productOptionsForScope(
  meta: FilterMetaData | undefined,
  productScope = ALL_PRODUCTS,
  currentValue = ALL_PRODUCTS,
): SelectOption[] {
  if (!productScope || productScope === ALL_PRODUCTS) {
    return productOptions(meta, currentValue);
  }
  const values = ensureValue(
    unique([
      ALL_PRODUCTS,
      ...(meta?.product_scope_type_map?.[productScope] ?? []),
    ]),
    currentValue,
  );

  return values.map((value) => ({
    value,
    label: productLabel(value),
  }));
}

export function saleMonthOptions(
  meta: FilterMetaData | undefined,
  currentValue?: string,
): SelectOption[] {
  return ensureValue(unique(meta?.sale_months ?? []), currentValue).map(
    (value) => ({ value, label: value }),
  );
}

export function verifyMonthOptions(
  meta: FilterMetaData | undefined,
  currentValue?: string,
): SelectOption[] {
  return ensureValue(unique(meta?.verify_months ?? []), currentValue).map(
    (value) => ({ value, label: value }),
  );
}

export function storeOptions(
  meta: FilterMetaData | undefined,
  currentStore?: { store_id: string; store_name: string },
): SelectOption[] {
  const stores = [...(meta?.stores ?? [])];
  if (
    currentStore &&
    !stores.some((store) => store.store_id === currentStore.store_id)
  ) {
    stores.unshift(currentStore);
  }

  return stores.map((store) => ({
    value: store.store_id,
    label: store.store_name,
  }));
}
