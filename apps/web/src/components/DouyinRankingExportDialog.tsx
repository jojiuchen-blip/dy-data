import { useState } from "react";
import { downloadDouyinRanking } from "../api/client";
import { Button } from "./Button";
import { Dialog } from "./Dialog";
import { CheckboxField, TextField } from "./FormControls";
import { ResourcePanel } from "./ResourceState";
import { apiErrorText } from "../utils/apiErrors";
import { RANKING_EARLIEST_DATE } from "../utils/douyinRankingDates";
import { RANKING_LEVEL_OPTIONS, RANKING_METRIC_OPTIONS, type RankingMetric } from "../utils/rankingOptions";
import type { DouyinRankingLevel } from "../types/dashboard";

interface Props {
  productScope: string;
  periodStart: string;
  periodEnd: string;
  today: string;
  level: DouyinRankingLevel;
  filters: { groupName: string; serviceCenterName: string; districtName: string; areaName: string };
  onClose: () => void;
}

export function DouyinRankingExportDialog({ productScope, periodStart, periodEnd, today, level, filters, onClose }: Props) {
  const [start, setStart] = useState(periodStart);
  const [end, setEnd] = useState(periodEnd);
  const [levels, setLevels] = useState<DouyinRankingLevel[]>([level]);
  const [metrics, setMetrics] = useState<RankingMetric[]>(RANKING_METRIC_OPTIONS.map((item) => item.value));
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const valid = levels.length > 0 && metrics.length > 0 && start >= RANKING_EARLIEST_DATE && end >= start && end <= today;

  async function submit() {
    if (!valid || busy) return;
    setBusy(true);
    setError("");
    try {
      await downloadDouyinRanking({ ...filters, productScope, periodStart: start, periodEnd: end, levels: levels.join(","), metrics: metrics.join(",") });
      onClose();
    } catch (reason) {
      setError(apiErrorText(reason, "导出失败，请稍后重试。"));
    } finally {
      setBusy(false);
    }
  }

  return <Dialog open title="导出排行" onClose={onClose} closeDisabled={busy} panelStyle={{ gridTemplateRows: "auto minmax(0, 1fr) auto" }}
    description="每个指标一个工作表，所选层级在表内分别排名。导出当前账号权限和组织筛选范围内的全部结果。"
    actions={<><Button onClick={onClose} disabled={busy}>取消</Button><Button variant="primary" onClick={submit} loading={busy} disabled={!valid || busy}>{busy ? "正在生成…" : "导出 Excel"}</Button></>}>
    <div className="page-stack">
      <p>商品范围：{({all: "全部商品", jingcheng: "精诚养车商品", byd: "比亚迪本品"} as Record<string, string>)[productScope]}</p>
      <TextField label="导出开始日期" type="date" min={RANKING_EARLIEST_DATE} max={today} value={start} disabled={busy} onChange={(event) => setStart(event.target.value)} />
      <TextField label="导出结束日期" type="date" min={start} max={today} value={end} disabled={busy} onChange={(event) => setEnd(event.target.value)} />
      <fieldset disabled={busy}><legend>导出层级（可多选）</legend>
        {RANKING_LEVEL_OPTIONS.map((item) => <CheckboxField key={item.value} label={item.label} checked={levels.includes(item.value)} onChange={(event) => setLevels(event.target.checked ? [...levels, item.value] : levels.filter((value) => value !== item.value))} />)}
      </fieldset>
      <fieldset disabled={busy}><legend>排行指标（可多选）</legend>
        {RANKING_METRIC_OPTIONS.map((item) => <CheckboxField key={item.value} label={item.label} checked={metrics.includes(item.value)} onChange={(event) => setMetrics(event.target.checked ? [...metrics, item.value] : metrics.filter((value) => value !== item.value))} />)}
      </fieldset>
      <p>将生成 {metrics.length} 个工作表，每个工作表包含 {levels.length} 张层级排行附表。订单总量、不限24小时跟进率作为对应榜单的辅助指标。</p>
      {Object.values(filters).some(Boolean) && <p>当前组织筛选：{Object.values(filters).filter(Boolean).join(" / ")}</p>}
      {!valid && <p role="status">请至少选择一个层级和指标，并填写有效的起止日期。</p>}
      {error && <ResourcePanel tone="error">{error}</ResourcePanel>}
    </div>
  </Dialog>;
}
