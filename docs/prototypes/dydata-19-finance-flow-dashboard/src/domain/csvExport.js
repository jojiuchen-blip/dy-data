function escapeCell(value) {
  const text = value == null ? "" : String(value);
  return /[",\n]/.test(text) ? `"${text.replace(/"/g, '""')}"` : text;
}

export function buildCsv(rows) {
  const fields = [...new Set(rows.flatMap((row) => Object.keys(row)))];
  return [
    fields.map(escapeCell).join(","),
    ...rows.map((row) => fields.map((field) => escapeCell(row[field])).join(",")),
  ].join("\n");
}

export function exportAllFields(rows, fileName) {
  if (!rows.length) return 0;
  const csv = buildCsv(rows);

  const isJsdom = typeof navigator !== "undefined" && navigator.userAgent.toLowerCase().includes("jsdom");
  if (!isJsdom && typeof document !== "undefined" && typeof URL?.createObjectURL === "function") {
    const blob = new Blob(["\uFEFF", csv], { type: "text/csv;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = fileName;
    link.click();
    URL.revokeObjectURL(url);
  }
  return rows.length;
}
