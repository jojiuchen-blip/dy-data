import type { DashboardPublication } from "../types/dashboard";
import { useDashboardPublication } from "../hooks/PublicationContext";
import { formatDateTime } from "../utils/format";
import { Button } from "./Button";

export function PublicationTime({ publication }: { publication: DashboardPublication }) {
  return <span className="publication-time">
    <span>数据截至：{publication.dataAsOf ? formatDateTime(publication.dataAsOf) : "来源时间未知"}</span>
    <span>结果更新时间：{formatDateTime(publication.publishedAt)}</span>
    {publication.status === "refreshing" ? <span>后台更新中，展示上一完整结果</span> : null}
    {publication.status === "stale" ? <span>等待后台更新，展示上一完整结果</span> : null}
    {publication.status === "failed" ? <span>后台更新失败，展示上一完整结果</span> : null}
  </span>;
}

export function PagePublicationTime() {
  const { publication, refreshLatest, notice, analysisActive } = useDashboardPublication();
  if (!analysisActive) return null;
  return <aside className="page-publication-time" aria-label="当前分析结果版本">
    {publication ? <PublicationTime publication={publication} /> : <span>正在准备已发布结果，来源时间尚未确定。</span>}
    <Button onClick={refreshLatest} size="sm" variant="secondary">读取最新结果</Button>
    {notice ? <span role="status">{notice}</span> : null}
  </aside>;
}
