export function StatusTag({ tone = "neutral", children }) {
  return <span className={`status-tag status-tag--${tone}`}>{children}</span>;
}
