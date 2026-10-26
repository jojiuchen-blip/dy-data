/** Canonical ordinary-business filters; legacy scope never restricts these pages. */
export function replaceBusinessFiltersInUrl(values: Record<string, string | undefined> = {}): void {
  if (typeof window === "undefined") return;
  const url = new URL(window.location.href);
  url.searchParams.delete("productScope");
  url.searchParams.delete("product_scope");
  Object.entries(values).forEach(([key, value]) => {
    if (value) url.searchParams.set(key, value);
    else url.searchParams.delete(key);
  });
  const href = `${url.pathname}${url.search}${url.hash}`;
  if (href !== `${window.location.pathname}${window.location.search}${window.location.hash}`) {
    window.history.replaceState(window.history.state, "", href);
  }
}
