export function MetricScopeToggle({ value, onChange }) {
  return (
    <div className="metric-scope" aria-label="指标口径">
      <div className="metric-scope__buttons">
        {[
          ["month", "单月"],
          ["cumulative", "累计"],
        ].map(([id, label]) => (
          <button
            key={id}
            type="button"
            aria-pressed={value === id}
            onClick={() => onChange(id)}
          >
            {label}
          </button>
        ))}
      </div>
      <span>{value === "cumulative" ? "累计自 2026 年 8 月起，不含 2026 年 7 月数据" : "按当前选择账期统计"}</span>
    </div>
  );
}
