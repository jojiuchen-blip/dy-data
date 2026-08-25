import { SolarIcon } from "./SolarIcon.jsx";

export function MetricStrip({ items }) {
  return (
    <dl className="metric-strip" style={{ "--metric-count": items.length }}>
      {items.map((item) => (
        <div className={`metric-card metric-card--${item.tone ?? "neutral"}`} key={item.label}>
          <dt>{item.label}</dt>
          <dd>{item.value}</dd>
          {item.helper ? <small>{item.helper}</small> : null}
        </div>
      ))}
    </dl>
  );
}

export function WorkbenchToolbar({ children, onSearch, actions, searchLabel = "搜索门店、SAP或发票号码" }) {
  return (
    <div className="workbench-toolbar">
      <label className="search-field">
        <SolarIcon name="document" size={18} />
        <span className="sr-only">{searchLabel}</span>
        <input
          type="search"
          placeholder={searchLabel}
          onChange={(event) => onSearch?.(event.target.value)}
        />
      </label>
      <div className="workbench-toolbar__filters">{children}</div>
      {actions ? <div className="workbench-toolbar__actions">{actions}</div> : null}
    </div>
  );
}

export function EmptyState({ title, detail }) {
  return (
    <div className="empty-state">
      <SolarIcon name="document" size={28} />
      <strong>{title}</strong>
      <span>{detail}</span>
    </div>
  );
}
