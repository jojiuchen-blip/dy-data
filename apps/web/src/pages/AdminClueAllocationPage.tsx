import { useEffect, useMemo, useState } from "react";
import {
  ApiRequestError,
  createClueAllocationRule,
  createClueAllocationRuleVersion,
  fetchClueAllocationAuditLogs,
  fetchClueAllocationCycles,
  fetchClueAllocationDecisions,
  fetchClueAllocationEligibleLeads,
  fetchClueAllocationRuleDetail,
  fetchClueAllocationRules,
  fetchClueAllocationStoreScores,
  fetchClueHeadquartersPool,
  publishClueAllocationRuleVersion,
  previewClueAllocationCycle,
  rebuildClueAllocationTrial,
  retireClueAllocationRuleVersion,
  runClueAllocationTrial,
} from "../api/client";
import { Button } from "../components/Button";
import { DataTable, type Column } from "../components/DataTable";
import { SelectField } from "../components/FormControls";
import { SolarIcon } from "../components/SolarIcon";
import type {
  ClueAllocationAuditLog,
  ClueAllocationCycle,
  ClueAllocationCyclePreview,
  ClueAllocationDecision,
  ClueAllocationEligibleLead,
  ClueAllocationRuleDetailData,
  ClueAllocationRule,
  ClueAllocationRuleScope,
  ClueAllocationRuleVersion,
  ClueAllocationRuleVersionWrite,
  ClueHeadquartersPoolEntry,
  StoreScoreSnapshot,
  StoreScoreSnapshotData,
} from "../types/dashboard";
import { formatDateTime } from "../utils/format";

const poolReasonLabels: Record<string, string> = {
  follow_poi_missing: "缺少锚点门店",
  no_candidate: "无可分配门店",
  strategies_exhausted: "轮次候选已耗尽",
};

const scopeLabels: Record<ClueAllocationRuleScope["scope_type"], string> = {
  global: "全局默认",
  city: "城市",
  store_group: "门店组",
  anchor_store: "锚点门店",
};

const strategyLabels: Record<string, string> = {
  sales_store_priority: "销售店优先（10 公里）",
  nearby_city_optimization: "15 公里城市优选",
  city_fallback: "城市兜底",
};

const decisionStatusLabels: Record<string, string> = {
  selected: "已分配",
  skipped: "已跳过",
  headquarters: "进入总部池",
};

type AllocationSubview = "rules" | "trial" | "records" | "headquarters";

const allocationSubviewItems: Array<{ id: AllocationSubview; label: string }> = [
  { id: "rules", label: "分配规则" },
  { id: "trial", label: "分配试运行" },
  { id: "records", label: "分配记录" },
  { id: "headquarters", label: "总部线索池" },
];

interface RuleVersionDraft {
  auto_expiry_enabled: boolean;
  first_follow_up_sla_hours: number;
  protection_days: number;
  conversion_weight: number;
  follow_24h_weight: number;
  lookback_days: number;
  min_samples: number;
  salesStoreEnabled: boolean;
  salesStoreDistanceKm: number;
  nearbyCityEnabled: boolean;
  nearbyCityDistanceKm: number;
  cityFallbackEnabled: boolean;
}

const defaultRuleVersionDraft: RuleVersionDraft = {
  auto_expiry_enabled: true,
  first_follow_up_sla_hours: 24,
  protection_days: 7,
  conversion_weight: 0.7,
  follow_24h_weight: 0.3,
  lookback_days: 30,
  min_samples: 20,
  salesStoreEnabled: true,
  salesStoreDistanceKm: 10,
  nearbyCityEnabled: true,
  nearbyCityDistanceKm: 15,
  cityFallbackEnabled: true,
};

function displayValue(value: string | null | undefined): string {
  return value || "-";
}

function displayPoolReason(reason: string): string {
  return poolReasonLabels[reason] ?? reason;
}

function summaryLabel(summary: Record<string, number> | undefined): string {
  if (!summary) {
    return "-";
  }
  return `分配 ${summary.assigned ?? 0}，总部池 ${summary.headquarters ?? 0}，跳过 ${summary.skipped ?? 0}`;
}

function displayAuditSummary(row: ClueAllocationAuditLog): string {
  const after = row.after_snapshot as Record<string, number>;
  return summaryLabel(after);
}

function describeRuleScope(scope: ClueAllocationRuleScope): string {
  if (scope.scope_type === "city") {
    return `${scopeLabels.city}：${displayValue(scope.city_code)}`;
  }
  if (scope.scope_type === "store_group") {
    return `${scopeLabels.store_group}：${displayValue(scope.store_group_id)}`;
  }
  if (scope.scope_type === "anchor_store") {
    return `${scopeLabels.anchor_store}：${displayValue(scope.anchor_store_id)}`;
  }
  return scopeLabels.global;
}

function distanceFromParams(params: Record<string, unknown>, fallback: number): number {
  const value = params.max_distance_km;
  return typeof value === "number" && Number.isFinite(value) ? value : fallback;
}

function ruleVersionToDraft(version?: ClueAllocationRuleVersion): RuleVersionDraft {
  if (!version) {
    return defaultRuleVersionDraft;
  }
  const strategies = new Map(version.strategy_configs.map((config) => [config.strategy_type, config]));
  const salesStore = strategies.get("sales_store_priority");
  const nearbyCity = strategies.get("nearby_city_optimization");
  const cityFallback = strategies.get("city_fallback");
  return {
    auto_expiry_enabled: version.auto_expiry_enabled ?? true,
    first_follow_up_sla_hours: version.first_follow_up_sla_hours ?? 24,
    protection_days: version.protection_days ?? 7,
    conversion_weight: version.conversion_weight ?? 0.7,
    follow_24h_weight: version.follow_24h_weight ?? 0.3,
    lookback_days: version.lookback_days ?? 30,
    min_samples: version.min_samples ?? 20,
    salesStoreEnabled: salesStore?.enabled ?? true,
    salesStoreDistanceKm: distanceFromParams(salesStore?.params ?? {}, 10),
    nearbyCityEnabled: nearbyCity?.enabled ?? true,
    nearbyCityDistanceKm: distanceFromParams(nearbyCity?.params ?? {}, 15),
    cityFallbackEnabled: cityFallback?.enabled ?? true,
  };
}

function buildRuleVersionPayload(draft: RuleVersionDraft): ClueAllocationRuleVersionWrite {
  return {
    auto_expiry_enabled: draft.auto_expiry_enabled,
    first_follow_up_sla_hours: draft.first_follow_up_sla_hours,
    protection_days: draft.protection_days,
    conversion_weight: draft.conversion_weight,
    follow_24h_weight: draft.follow_24h_weight,
    lookback_days: draft.lookback_days,
    min_samples: draft.min_samples,
    strategy_configs: [
      {
        strategy_type: "sales_store_priority",
        enabled: draft.salesStoreEnabled,
        execution_order: 1,
        params: { max_distance_km: draft.salesStoreDistanceKm },
      },
      {
        strategy_type: "nearby_city_optimization",
        enabled: draft.nearbyCityEnabled,
        execution_order: 2,
        params: { max_distance_km: draft.nearbyCityDistanceKm },
      },
      {
        strategy_type: "city_fallback",
        enabled: draft.cityFallbackEnabled,
        execution_order: 3,
        params: {},
      },
    ],
  };
}

interface AdminClueAllocationPageProps {
  isHighestAdmin: boolean;
}

export function AdminClueAllocationPage({ isHighestAdmin }: AdminClueAllocationPageProps) {
  const [eligibleLeads, setEligibleLeads] = useState<ClueAllocationEligibleLead[]>([]);
  const [headquartersEntries, setHeadquartersEntries] = useState<
    ClueHeadquartersPoolEntry[]
  >([]);
  const [cycles, setCycles] = useState<ClueAllocationCycle[]>([]);
  const [auditLogs, setAuditLogs] = useState<ClueAllocationAuditLog[]>([]);
  const [rules, setRules] = useState<ClueAllocationRule[]>([]);
  const [selectedRuleId, setSelectedRuleId] = useState("");
  const [selectedRuleDetail, setSelectedRuleDetail] = useState<ClueAllocationRuleDetailData | null>(
    null,
  );
  const [decisions, setDecisions] = useState<ClueAllocationDecision[]>([]);
  const [scoreData, setScoreData] = useState<StoreScoreSnapshotData | null>(null);
  const [selectedLeadKeys, setSelectedLeadKeys] = useState<Set<string>>(new Set());
  const [selectedRebuildCycleId, setSelectedRebuildCycleId] = useState("");
  const [preview, setPreview] = useState<ClueAllocationCyclePreview | null>(null);
  const [loading, setLoading] = useState(true);
  const [activeSubview, setActiveSubview] = useState<AllocationSubview>("rules");
  const [action, setAction] = useState<
    "preview" | "trial" | "rebuild" | "rule" | "publish" | "retire" | null
  >(null);
  const [allowPrivilegedRebuild, setAllowPrivilegedRebuild] = useState(false);
  const [statusText, setStatusText] = useState("");
  const [isCompactViewport, setIsCompactViewport] = useState(false);
  const [ruleVersionDraft, setRuleVersionDraft] = useState<RuleVersionDraft>(
    defaultRuleVersionDraft,
  );
  const [newRuleName, setNewRuleName] = useState("");
  const [newRuleScopeType, setNewRuleScopeType] = useState<ClueAllocationRuleScope["scope_type"]>(
    "global",
  );
  const [newRuleScopeTarget, setNewRuleScopeTarget] = useState("");
  const isWritable = isHighestAdmin && !isCompactViewport;

  const selectedKeys = useMemo(
    () => Array.from(selectedLeadKeys).sort(),
    [selectedLeadKeys],
  );
  const rebuildSourceCycles = useMemo(
    () => cycles.filter((cycle) => cycle.execution_mode === "trial" && cycle.status === "completed"),
    [cycles],
  );

  const load = async ({ clearStatus = true }: { clearStatus?: boolean } = {}) => {
    setLoading(true);
    try {
      const [eligible, headquarters, cycleData, auditData, ruleData, decisionData, scores] = await Promise.all([
        fetchClueAllocationEligibleLeads(),
        fetchClueHeadquartersPool(),
        fetchClueAllocationCycles(),
        fetchClueAllocationAuditLogs(),
        fetchClueAllocationRules(),
        fetchClueAllocationDecisions(),
        fetchClueAllocationStoreScores(),
      ]);
      setEligibleLeads(eligible.data.rows);
      setHeadquartersEntries(headquarters.data.rows);
      setCycles(cycleData.data.rows);
      setAuditLogs(auditData.data.rows);
      setRules(ruleData.data.rows);
      setDecisions(decisionData.data.rows);
      setScoreData(scores?.data ?? null);
      setSelectedLeadKeys((current) => {
        const valid = new Set(eligible.data.rows.map((row) => row.lead_key));
        return new Set(Array.from(current).filter((leadKey) => valid.has(leadKey)));
      });
      setSelectedRebuildCycleId((current) =>
        cycleData.data.rows.some((cycle) => cycle.allocation_cycle_id === current) ? current : "",
      );
      setSelectedRuleId((current) =>
        ruleData.data.rows.some((rule) => rule.rule_id === current)
          ? current
          : ruleData.data.rows[0]?.rule_id ?? "",
      );
      if (clearStatus) {
        setStatusText("");
      }
    } catch (error) {
      if (error instanceof ApiRequestError && error.status === 403) {
        setStatusText("当前账号没有线索分配试运行权限。");
      } else {
        setStatusText("线索分配控制数据暂时无法读取。");
      }
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void load();
  }, []);

  useEffect(() => {
    const viewport = window.matchMedia("(max-width: 760px)");
    const syncViewport = () => setIsCompactViewport(viewport.matches);
    syncViewport();
    viewport.addEventListener("change", syncViewport);
    return () => viewport.removeEventListener("change", syncViewport);
  }, []);

  useEffect(() => {
    if (!selectedRuleId) {
      setSelectedRuleDetail(null);
      return;
    }
    let cancelled = false;
    void fetchClueAllocationRuleDetail(selectedRuleId)
      .then((response) => {
        if (cancelled) {
          return;
        }
        setSelectedRuleDetail(response.data);
        setRuleVersionDraft(ruleVersionToDraft(response.data.versions[0]));
      })
      .catch((error) => {
        if (!cancelled) {
          setSelectedRuleDetail(null);
          setStatusText(error instanceof Error ? error.message : "规则版本暂时无法读取。");
        }
      });
    return () => {
      cancelled = true;
    };
  }, [selectedRuleId]);

  const toggleLead = (leadKey: string) => {
    if (!isWritable) {
      return;
    }
    setSelectedLeadKeys((current) => {
      const next = new Set(current);
      if (next.has(leadKey)) {
        next.delete(leadKey);
      } else {
        next.add(leadKey);
      }
      return next;
    });
    setPreview(null);
  };

  const selectAllEligible = () => {
    if (!isWritable) {
      return;
    }
    setSelectedLeadKeys(new Set(eligibleLeads.map((row) => row.lead_key)));
    setPreview(null);
  };

  const clearSelection = () => {
    if (!isWritable) {
      return;
    }
    setSelectedLeadKeys(new Set());
    setPreview(null);
  };

  const ensureTrialSelection = (): boolean => {
    if (!isWritable) {
      setStatusText("移动端仅可查看，请使用桌面端执行分配操作。");
      return false;
    }
    if (selectedKeys.length) {
      return true;
    }
    setStatusText("请先选择需要预览或试运行的线索。");
    return false;
  };

  const handlePreview = async (operation: "trial" | "rebuild") => {
    if (!isWritable) {
      setStatusText("移动端仅可查看，请使用桌面端执行分配操作。");
      return;
    }
    if (operation === "trial" && !ensureTrialSelection()) {
      return;
    }
    if (operation === "rebuild" && !selectedRebuildCycleId) {
      setStatusText("请先选择需要重建的来源试运行批次。");
      return;
    }
    setAction("preview");
    try {
      const response = await previewClueAllocationCycle(
        operation === "trial"
          ? { operation, lead_keys: selectedKeys }
          : {
              operation,
              source_cycle_id: selectedRebuildCycleId,
              privileged_confirmation: allowPrivilegedRebuild,
            },
      );
      setPreview(response.data);
      setStatusText("已生成预览，尚未写入任何分配结果。请确认影响后执行。");
    } catch (error) {
      setStatusText(error instanceof Error ? error.message : "分配预览失败。");
    } finally {
      setAction(null);
    }
  };

  const runTrial = async () => {
    if (!isWritable) {
      setStatusText("移动端仅可查看，请使用桌面端执行分配操作。");
      return;
    }
    if (!ensureTrialSelection()) {
      return;
    }
    if (!preview || preview.operation !== "trial" || preview.lead_keys.join("|") !== selectedKeys.join("|")) {
      setStatusText("请先预览当前选择范围，再确认执行。");
      return;
    }
    if (!window.confirm(`确认启动这 ${selectedKeys.length} 条线索的试运行？`)) {
      return;
    }
    setAction("trial");
    try {
      const response = await runClueAllocationTrial({
        lead_keys: selectedKeys,
        preview_token: preview.preview_token,
        confirm: true,
      });
      setPreview(null);
      setStatusText(`试运行已完成。${summaryLabel(response.data.summary)}`);
      await load({ clearStatus: false });
    } catch (error) {
      setStatusText(error instanceof Error ? error.message : "试运行失败。");
    } finally {
      setAction(null);
    }
  };

  const runRebuild = async () => {
    if (!isWritable) {
      setStatusText("移动端仅可查看，请使用桌面端执行分配操作。");
      return;
    }
    if (!selectedRebuildCycleId) {
      setStatusText("请先选择需要重建的来源试运行批次。");
      return;
    }
    if (
      !preview ||
      preview.operation !== "rebuild" ||
      preview.source_cycle_id !== selectedRebuildCycleId
    ) {
      setStatusText("请先预览该来源批次，再确认重建。");
      return;
    }
    if (!window.confirm(`确认重建试运行批次 ${selectedRebuildCycleId}？`)) {
      return;
    }
    setAction("rebuild");
    try {
      const response = await rebuildClueAllocationTrial({
        source_cycle_id: selectedRebuildCycleId,
        preview_token: preview.preview_token,
        confirm: true,
        privileged_confirmation: allowPrivilegedRebuild,
      });
      setPreview(null);
      setStatusText(`试运行重建已完成。${summaryLabel(response.data.summary)}`);
      await load({ clearStatus: false });
    } catch (error) {
      setStatusText(error instanceof Error ? error.message : "试运行重建失败。");
    } finally {
      setAction(null);
    }
  };

  const ruleScopePayload = (): ClueAllocationRuleScope | null => {
    const target = newRuleScopeTarget.trim();
    if (newRuleScopeType !== "global" && !target) {
      setStatusText("请填写规则范围对应的标识。");
      return null;
    }
    return {
      scope_type: newRuleScopeType,
      city_code: newRuleScopeType === "city" ? target : null,
      store_group_id: newRuleScopeType === "store_group" ? target : null,
      anchor_store_id: newRuleScopeType === "anchor_store" ? target : null,
    };
  };

  const validateRuleVersionDraft = (): boolean => {
    const values = [
      ruleVersionDraft.first_follow_up_sla_hours,
      ruleVersionDraft.protection_days,
      ruleVersionDraft.conversion_weight,
      ruleVersionDraft.follow_24h_weight,
      ruleVersionDraft.lookback_days,
      ruleVersionDraft.min_samples,
      ruleVersionDraft.salesStoreDistanceKm,
      ruleVersionDraft.nearbyCityDistanceKm,
    ];
    if (values.some((value) => !Number.isFinite(value))) {
      setStatusText("规则参数必须是有效数字。");
      return false;
    }
    if (
      !Number.isInteger(ruleVersionDraft.first_follow_up_sla_hours) ||
      ruleVersionDraft.first_follow_up_sla_hours < 1 ||
      ruleVersionDraft.first_follow_up_sla_hours > 168 ||
      !Number.isInteger(ruleVersionDraft.protection_days) ||
      ruleVersionDraft.protection_days < 1 ||
      ruleVersionDraft.protection_days > 365 ||
      !Number.isInteger(ruleVersionDraft.lookback_days) ||
      ruleVersionDraft.lookback_days < 1 ||
      ruleVersionDraft.lookback_days > 365 ||
      !Number.isInteger(ruleVersionDraft.min_samples) ||
      ruleVersionDraft.min_samples < 1 ||
      ruleVersionDraft.min_samples > 10000 ||
      ruleVersionDraft.salesStoreDistanceKm <= 0 ||
      ruleVersionDraft.nearbyCityDistanceKm <= 0
    ) {
      setStatusText("SLA、保护期、样本窗口、最小样本和距离参数不在允许范围内。");
      return false;
    }
    if (
      ruleVersionDraft.conversion_weight < 0 ||
      ruleVersionDraft.follow_24h_weight < 0 ||
      Math.abs(ruleVersionDraft.conversion_weight + ruleVersionDraft.follow_24h_weight - 1) > 0.000001
    ) {
      setStatusText("核销转化与 24 小时有效跟进率的权重之和必须为 1。");
      return false;
    }
    return true;
  };

  const handleCreateRule = async () => {
    if (!isWritable) {
      setStatusText("移动端仅可查看，请使用桌面端配置规则。");
      return;
    }
    const name = newRuleName.trim();
    const scope = ruleScopePayload();
    if (!name || !scope) {
      if (!name) {
        setStatusText("请填写规则名称。");
      }
      return;
    }
    setAction("rule");
    try {
      const response = await createClueAllocationRule({ name, scope });
      setNewRuleName("");
      setNewRuleScopeTarget("");
      setStatusText("规则已创建，请继续创建草案版本并发布后生效。");
      await load({ clearStatus: false });
      setSelectedRuleId(response.data.rule_id);
    } catch (error) {
      setStatusText(error instanceof Error ? error.message : "创建规则失败。");
    } finally {
      setAction(null);
    }
  };

  const handleCreateRuleVersion = async () => {
    if (!isWritable) {
      setStatusText("移动端仅可查看，请使用桌面端配置规则。");
      return;
    }
    if (!selectedRuleId) {
      setStatusText("请先选择一个规则。");
      return;
    }
    if (!validateRuleVersionDraft()) {
      return;
    }
    setAction("rule");
    try {
      const response = await createClueAllocationRuleVersion(
        selectedRuleId,
        buildRuleVersionPayload(ruleVersionDraft),
      );
      setStatusText(`已创建草案版本 V${response.data.version_no}，发布前仍可继续调整。`);
      const detail = await fetchClueAllocationRuleDetail(selectedRuleId);
      setSelectedRuleDetail(detail.data);
      setRuleVersionDraft(ruleVersionToDraft(detail.data.versions[0]));
    } catch (error) {
      setStatusText(error instanceof Error ? error.message : "创建草案版本失败。");
    } finally {
      setAction(null);
    }
  };

  const handlePublishRuleVersion = async (version: ClueAllocationRuleVersion) => {
    if (!isWritable) {
      setStatusText("移动端仅可查看，请使用桌面端发布规则。");
      return;
    }
    if (!window.confirm(`确认发布 V${version.version_no}？同一规则范围的旧发布版本将自动退役。`)) {
      return;
    }
    setAction("publish");
    try {
      await publishClueAllocationRuleVersion(version.rule_version_id);
      setStatusText(`V${version.version_no} 已发布。`);
      await load({ clearStatus: false });
    } catch (error) {
      setStatusText(error instanceof Error ? error.message : "发布规则版本失败。");
    } finally {
      setAction(null);
    }
  };

  const handleRetireRuleVersion = async (version: ClueAllocationRuleVersion) => {
    if (!isWritable) {
      setStatusText("移动端仅可查看，请使用桌面端退役规则。");
      return;
    }
    if (!window.confirm(`确认退役 V${version.version_no}？该范围的新线索将回退到更低优先级的已发布规则。`)) {
      return;
    }
    setAction("retire");
    try {
      await retireClueAllocationRuleVersion(version.rule_version_id);
      setStatusText(`V${version.version_no} 已退役。`);
      await load({ clearStatus: false });
    } catch (error) {
      setStatusText(error instanceof Error ? error.message : "退役规则版本失败。");
    } finally {
      setAction(null);
    }
  };

  const eligibleColumns: Column<ClueAllocationEligibleLead>[] = [
    ...(isWritable
      ? [
          {
            key: "select",
            title: "选择",
            width: 72,
            render: (lead) => (
              <input
                aria-label={`选择线索 ${lead.canonical_clue_id ?? lead.lead_key}`}
                checked={selectedLeadKeys.has(lead.lead_key)}
                onChange={() => toggleLead(lead.lead_key)}
                type="checkbox"
              />
            ),
          } satisfies Column<ClueAllocationEligibleLead>,
        ]
      : []),
    {
      key: "clue",
      title: "线索标识",
      minWidth: 150,
      render: (lead) => displayValue(lead.canonical_clue_id),
    },
    {
      key: "order",
      title: "订单 ID",
      minWidth: 150,
      render: (lead) => displayValue(lead.order_id),
    },
    {
      key: "pool",
      title: "当前池",
      minWidth: 110,
      render: (lead) => (lead.pool_location === "headquarters_pool" ? "总部池" : "待分配"),
    },
    {
      key: "anchor-store",
      title: "锚点门店",
      minWidth: 150,
      render: (lead) => displayValue(lead.anchor_store_id),
    },
    {
      key: "anchor-city",
      title: "锚点城市",
      minWidth: 130,
      render: (lead) => displayValue(lead.anchor_city),
    },
    {
      key: "updated-at",
      title: "更新时间",
      minWidth: 160,
      render: (lead) => formatDateTime(lead.updated_at),
    },
  ];

  const headquartersColumns: Column<ClueHeadquartersPoolEntry>[] = [
    {
      key: "clue",
      title: "线索标识",
      minWidth: 150,
      render: (entry) => displayValue(entry.canonical_clue_id),
    },
    {
      key: "order",
      title: "订单 ID",
      minWidth: 150,
      render: (entry) => displayValue(entry.order_id),
    },
    {
      key: "reason",
      title: "进入原因",
      minWidth: 150,
      render: (entry) => displayPoolReason(entry.reason),
    },
    {
      key: "anchor-store",
      title: "锚点门店",
      minWidth: 150,
      render: (entry) => displayValue(entry.anchor_store_id),
    },
    {
      key: "entered-at",
      title: "进入时间",
      minWidth: 160,
      render: (entry) => formatDateTime(entry.entered_at),
    },
    {
      key: "cycle",
      title: "来源批次",
      minWidth: 180,
      render: (entry) => displayValue(entry.allocation_cycle_id),
    },
  ];

  const decisionColumns: Column<ClueAllocationDecision>[] = [
    {
      key: "strategy",
      title: "策略",
      minWidth: 190,
      render: (decision) => strategyLabels[decision.strategy_type] ?? decision.strategy_type,
    },
    {
      key: "mode",
      title: "执行方式",
      minWidth: 100,
      render: (decision) => (decision.execution_mode === "trial" ? "试运行" : "正式"),
    },
    {
      key: "store",
      title: "选择门店",
      minWidth: 170,
      render: (decision) => displayValue(decision.selected_store_name ?? decision.selected_store_id),
    },
    {
      key: "status",
      title: "结果",
      minWidth: 110,
      render: (decision) => decisionStatusLabels[decision.decision_status] ?? decision.decision_status,
    },
    {
      key: "reason",
      title: "原因",
      minWidth: 170,
      render: (decision) => displayValue(decision.reason),
    },
    {
      key: "executed-at",
      title: "执行时间",
      minWidth: 160,
      render: (decision) => formatDateTime(decision.executed_at),
    },
  ];

  const scoreColumns: Column<StoreScoreSnapshot>[] = [
    { key: "store", title: "门店 ID", minWidth: 150, render: (score) => score.store_id },
    { key: "city", title: "城市", minWidth: 120, render: (score) => displayValue(score.city_code) },
    {
      key: "conversion",
      title: "核销转化率",
      minWidth: 130,
      render: (score) => `${(score.conversion_rate * 100).toFixed(1)}%`,
    },
    {
      key: "follow-rate",
      title: "24 小时有效跟进率",
      minWidth: 170,
      render: (score) => `${(score.follow_24h_rate * 100).toFixed(1)}%`,
    },
    {
      key: "weight",
      title: "门店权重",
      minWidth: 110,
      render: (score) => score.store_weight.toFixed(2),
    },
    {
      key: "composite",
      title: "综合评分",
      minWidth: 120,
      render: (score) => score.composite_score.toFixed(4),
    },
  ];

  const cycleColumns: Column<ClueAllocationCycle>[] = [
    {
      key: "type",
      title: "批次类型",
      minWidth: 120,
      render: (cycle) => (cycle.cycle_type === "rebuild" ? "试运行重建" : "试运行"),
    },
    { key: "status", title: "状态", minWidth: 100, render: (cycle) => cycle.status },
    { key: "count", title: "线索数", minWidth: 90, render: (cycle) => cycle.active_lead_count },
    {
      key: "impact",
      title: "执行结果",
      minWidth: 220,
      render: (cycle) => summaryLabel(cycle.actual_impact as Record<string, number>),
    },
    { key: "actor", title: "操作人", minWidth: 120, render: (cycle) => displayValue(cycle.actor) },
    {
      key: "completed-at",
      title: "完成时间",
      minWidth: 160,
      render: (cycle) => formatDateTime(cycle.completed_at ?? cycle.executed_at),
    },
  ];

  const auditColumns: Column<ClueAllocationAuditLog>[] = [
    { key: "event", title: "事件", minWidth: 150, render: (row) => row.event_type },
    {
      key: "cycle",
      title: "批次",
      minWidth: 190,
      render: (row) => displayValue(row.allocation_cycle_id),
    },
    {
      key: "confirmation",
      title: "确认",
      minWidth: 120,
      render: (row) => (row.privileged_confirmation ? "特权确认" : "常规确认"),
    },
    {
      key: "summary",
      title: "结果摘要",
      minWidth: 220,
      render: (row) => displayAuditSummary(row),
    },
    { key: "actor", title: "操作人", minWidth: 120, render: (row) => displayValue(row.actor) },
    {
      key: "created-at",
      title: "记录时间",
      minWidth: 160,
      render: (row) => formatDateTime(row.created_at),
    },
  ];

  return (
    <div className="admin-page clue-allocation-admin-page">
      <section className="admin-header">
        <div>
          <h1>线索分配</h1>
          <p className="admin-muted">统一管理规则版本、试运行、分配记录和总部池。</p>
        </div>
        <div className="admin-header-actions">
          <Button
            icon="sync"
            disabled={loading || action !== null}
            onClick={() => void load()}
            type="button"
          >
            刷新
          </Button>
        </div>
      </section>

      {!isHighestAdmin ? (
        <div aria-live="polite" className="resource-notice" role="status">
          当前账号为只读权限，可查看线索分配状态、总部池、试运行记录和审计记录。
        </div>
      ) : null}

      {isHighestAdmin && isCompactViewport ? (
        <div aria-live="polite" className="resource-notice" role="status">
          移动端仅可查看。为避免误分配、误发布或误重建，请使用桌面端执行线索分配操作。
        </div>
      ) : null}

      {statusText ? (
        <div aria-live="polite" className="resource-notice" role="status">
          {statusText}
        </div>
      ) : null}

      <nav aria-label="线索分配功能" className="clue-allocation-subnav">
        {allocationSubviewItems.map((item) => (
          <button
            aria-pressed={activeSubview === item.id}
            className={`clue-allocation-subnav__item${
              activeSubview === item.id ? " is-active" : ""
            }`}
            key={item.id}
            onClick={() => setActiveSubview(item.id)}
            type="button"
          >
            {item.label}
          </button>
        ))}
      </nav>

      {activeSubview === "trial" ? (
        <>
      <section className="content-section clue-allocation-control">
        <div className="section-title">
          <div>
            <h2>待试运行线索</h2>
            <p>仅展示没有当前分配轮次的有效线索；总部池线索保留在总部池，暂不通过本页再投放。</p>
          </div>
          <span className="source-pill">
            {isWritable ? `已选 ${selectedKeys.length} 条` : `共 ${eligibleLeads.length} 条`}
          </span>
        </div>
        {isWritable ? (
          <div className="clue-allocation-control__actions">
            <Button onClick={selectAllEligible} type="button">
              全选当前页
            </Button>
            <Button onClick={clearSelection} type="button">
              清空选择
            </Button>
            <Button
              icon="eye"
              disabled={action !== null || !selectedKeys.length}
              onClick={() => void handlePreview("trial")}
              type="button"
            >
              {action === "preview" ? "预览中" : "预览结果"}
            </Button>
            <Button
              icon="check"
              disabled={
                action !== null ||
                !selectedKeys.length ||
                preview?.operation !== "trial" ||
                preview.lead_keys.join("|") !== selectedKeys.join("|")
              }
              onClick={() => void runTrial()}
              type="button"
              variant="primary"
            >
              {action === "trial" ? "试运行中" : "启动试运行"}
            </Button>
          </div>
        ) : null}
        <DataTable
          columns={eligibleColumns}
          emptyText={loading ? "正在加载待试运行线索..." : "暂无可试运行线索"}
          rows={eligibleLeads}
          stickyHeader="container"
        />
      </section>

      {isWritable ? (
        <section className="content-section clue-allocation-preview">
          <div className="section-title">
            <div>
              <h2>预览与重建</h2>
              <p>预览不落库；重建只针对一个来源试运行批次，默认阻止覆盖已产生跟进记录的线索。</p>
            </div>
          </div>
          <div className="clue-allocation-preview__body">
            <div>
              <span>当前预览</span>
              <strong>{preview ? summaryLabel(preview.summary) : "尚未生成"}</strong>
              <small>
                {preview
                  ? `${preview.operation === "rebuild" ? "重建" : "试运行"}有效线索 ${preview.active_lead_count} 条`
                  : "先选择线索或来源批次生成预览"}
              </small>
            </div>
            <SelectField
              label="来源试运行批次"
              onChange={(value) => {
                setSelectedRebuildCycleId(value);
                setPreview(null);
              }}
              options={rebuildSourceCycles.map((cycle) => ({
                value: cycle.allocation_cycle_id,
                label: `${cycle.cycle_type === "rebuild" ? "重建" : "试运行"} · ${formatDateTime(cycle.completed_at ?? cycle.executed_at)}`,
              }))}
              placeholder="请选择批次"
              value={selectedRebuildCycleId}
            />
            <label className="filter-field checkbox-field">
              <span>允许覆盖已有跟进记录</span>
              <input
                checked={allowPrivilegedRebuild}
                onChange={(event) => {
                  setAllowPrivilegedRebuild(event.target.checked);
                  setPreview(null);
                }}
                type="checkbox"
              />
            </label>
            <Button
              icon="eye"
              disabled={action !== null || !selectedRebuildCycleId}
              onClick={() => void handlePreview("rebuild")}
              type="button"
            >
              {action === "preview" ? "预览中" : "预览重建"}
            </Button>
            <Button
              icon="sync"
              disabled={
                action !== null ||
                !selectedRebuildCycleId ||
                preview?.operation !== "rebuild" ||
                preview.source_cycle_id !== selectedRebuildCycleId
              }
              onClick={() => void runRebuild()}
              type="button"
            >
              {action === "rebuild" ? "重建中" : "重建试运行"}
            </Button>
          </div>
        </section>
      ) : null}

        </>
      ) : null}

      {activeSubview === "rules" ? (
        <section className="content-section clue-allocation-rule-management">
        <div className="section-title">
          <div>
            <h2>规则范围与版本</h2>
            <p>新线索首次命中已发布版本后固定沿用；历史轮次与决策快照不会被后续配置改写。</p>
          </div>
          <span className="source-pill">{rules.length} 条规则</span>
        </div>
        <div className="clue-allocation-management-grid">
          <div className="clue-allocation-rule-readonly">
            <SelectField
              label="规则范围"
              onChange={setSelectedRuleId}
              options={rules.map((rule) => ({
                value: rule.rule_id,
                label: `${rule.name} · ${describeRuleScope(rule.scope)}`,
              }))}
              placeholder="请选择规则"
              value={selectedRuleId}
            />

            {selectedRuleDetail ? (
              <div className="clue-allocation-rule-versions">
                <div className="clue-allocation-rule-summary">
                  <strong>{selectedRuleDetail.rule.name}</strong>
                  <span>{describeRuleScope(selectedRuleDetail.rule.scope)}</span>
                </div>
                {selectedRuleDetail.versions.map((version) => (
                  <article className="clue-allocation-rule-version" key={version.rule_version_id}>
                    <div className="clue-allocation-rule-version__header">
                      <strong>{`V${version.version_no}`}</strong>
                      <span className={`clue-allocation-version-status is-${version.status}`}>
                        {version.status === "published"
                          ? "已发布"
                          : version.status === "draft"
                            ? "草案"
                            : "已退役"}
                      </span>
                    </div>
                    <dl className="clue-allocation-version-metrics">
                      <div>
                        <dt>自动超时</dt>
                        <dd>{version.auto_expiry_enabled ? `${version.first_follow_up_sla_hours} 小时` : "关闭"}</dd>
                      </div>
                      <div>
                        <dt>保护期</dt>
                        <dd>{`${version.protection_days ?? "-"} 天`}</dd>
                      </div>
                      <div>
                        <dt>评分</dt>
                        <dd>{`${version.conversion_weight ?? "-"} / ${version.follow_24h_weight ?? "-"}`}</dd>
                      </div>
                    </dl>
                    <div className="clue-allocation-strategy-list">
                      <h3>固定分配策略</h3>
                      {version.strategy_configs.map((config) => (
                        <p key={config.strategy_type}>
                          <span>{strategyLabels[config.strategy_type] ?? config.strategy_type}</span>
                          <strong>{config.enabled ? `第 ${config.execution_order} 顺位` : "已停用"}</strong>
                        </p>
                      ))}
                    </div>
                    {isWritable && version.status === "draft" ? (
                      <Button
                        icon="check"
                        disabled={action !== null}
                        onClick={() => void handlePublishRuleVersion(version)}
                        type="button"
                      >
                        发布版本
                      </Button>
                    ) : null}
                    {isWritable && version.status === "published" ? (
                      <Button
                        icon="close"
                        disabled={action !== null}
                        onClick={() => void handleRetireRuleVersion(version)}
                        type="button"
                      >
                        退役版本
                      </Button>
                    ) : null}
                  </article>
                ))}
                {!selectedRuleDetail.versions.length ? (
                  <p className="admin-muted">该规则尚未创建版本。</p>
                ) : null}
              </div>
            ) : (
              <p className="admin-muted">选择规则后可查看版本、策略和生效参数。</p>
            )}
          </div>

          {isWritable ? (
            <div className="clue-allocation-rule-editor">
              <div>
                <h3>新建规则</h3>
                <p>先定义作用范围，再为该范围创建并发布版本。</p>
              </div>
              <div className="clue-allocation-rule-editor__fields">
                <label className="filter-field">
                  <span>规则名称</span>
                  <input
                    onChange={(event) => setNewRuleName(event.target.value)}
                    placeholder="例如：上海城市规则"
                    value={newRuleName}
                  />
                </label>
                <SelectField
                  label="范围类型"
                  onChange={(value) => {
                    setNewRuleScopeType(value as ClueAllocationRuleScope["scope_type"]);
                    setNewRuleScopeTarget("");
                  }}
                  options={[
                    { value: "global", label: "全局默认" },
                    { value: "city", label: "城市" },
                    { value: "store_group", label: "门店组" },
                    { value: "anchor_store", label: "锚点门店" },
                  ]}
                  value={newRuleScopeType}
                />
                {newRuleScopeType !== "global" ? (
                  <label className="filter-field">
                    <span>
                      {newRuleScopeType === "city"
                        ? "城市代码"
                        : newRuleScopeType === "store_group"
                          ? "门店组 ID"
                          : "锚点门店 ID"}
                    </span>
                    <input
                      onChange={(event) => setNewRuleScopeTarget(event.target.value)}
                      value={newRuleScopeTarget}
                    />
                  </label>
                ) : null}
              </div>
              <Button
                icon="rules"
                disabled={action !== null}
                onClick={() => void handleCreateRule()}
                type="button"
              >
                创建规则
              </Button>

              <div className="clue-allocation-rule-editor__divider" />
              <div>
                <h3>新建草案版本</h3>
                <p>策略类型固定，只能调整启停、参数和评分权重。</p>
              </div>
              <div className="clue-allocation-rule-editor__fields clue-allocation-rule-editor__fields--dense">
                <label className="filter-field checkbox-field">
                  <span>启用自动超时</span>
                  <input
                    checked={ruleVersionDraft.auto_expiry_enabled}
                    onChange={(event) =>
                      setRuleVersionDraft((current) => ({
                        ...current,
                        auto_expiry_enabled: event.target.checked,
                      }))
                    }
                    type="checkbox"
                  />
                </label>
                <label className="filter-field">
                  <span>首次跟进 SLA（小时）</span>
                  <input
                    min={1}
                    onChange={(event) =>
                      setRuleVersionDraft((current) => ({
                        ...current,
                        first_follow_up_sla_hours: Number(event.target.value),
                      }))
                    }
                    type="number"
                    value={ruleVersionDraft.first_follow_up_sla_hours}
                  />
                </label>
                <label className="filter-field">
                  <span>核销保护期（天）</span>
                  <input
                    min={1}
                    onChange={(event) =>
                      setRuleVersionDraft((current) => ({
                        ...current,
                        protection_days: Number(event.target.value),
                      }))
                    }
                    type="number"
                    value={ruleVersionDraft.protection_days}
                  />
                </label>
                <label className="filter-field">
                  <span>核销转化权重</span>
                  <input
                    max={1}
                    min={0}
                    onChange={(event) =>
                      setRuleVersionDraft((current) => ({
                        ...current,
                        conversion_weight: Number(event.target.value),
                      }))
                    }
                    step={0.1}
                    type="number"
                    value={ruleVersionDraft.conversion_weight}
                  />
                </label>
                <label className="filter-field">
                  <span>24 小时有效跟进率权重</span>
                  <input
                    max={1}
                    min={0}
                    onChange={(event) =>
                      setRuleVersionDraft((current) => ({
                        ...current,
                        follow_24h_weight: Number(event.target.value),
                      }))
                    }
                    step={0.1}
                    type="number"
                    value={ruleVersionDraft.follow_24h_weight}
                  />
                </label>
                <label className="filter-field">
                  <span>评分窗口（天）</span>
                  <input
                    min={1}
                    onChange={(event) =>
                      setRuleVersionDraft((current) => ({
                        ...current,
                        lookback_days: Number(event.target.value),
                      }))
                    }
                    type="number"
                    value={ruleVersionDraft.lookback_days}
                  />
                </label>
                <label className="filter-field">
                  <span>最小样本数</span>
                  <input
                    min={1}
                    onChange={(event) =>
                      setRuleVersionDraft((current) => ({
                        ...current,
                        min_samples: Number(event.target.value),
                      }))
                    }
                    type="number"
                    value={ruleVersionDraft.min_samples}
                  />
                </label>
                <label className="filter-field checkbox-field">
                  <span>销售店优先</span>
                  <input
                    checked={ruleVersionDraft.salesStoreEnabled}
                    onChange={(event) =>
                      setRuleVersionDraft((current) => ({
                        ...current,
                        salesStoreEnabled: event.target.checked,
                      }))
                    }
                    type="checkbox"
                  />
                </label>
                <label className="filter-field">
                  <span>销售店距离（公里）</span>
                  <input
                    min={0.1}
                    onChange={(event) =>
                      setRuleVersionDraft((current) => ({
                        ...current,
                        salesStoreDistanceKm: Number(event.target.value),
                      }))
                    }
                    step={0.1}
                    type="number"
                    value={ruleVersionDraft.salesStoreDistanceKm}
                  />
                </label>
                <label className="filter-field checkbox-field">
                  <span>城市优选</span>
                  <input
                    checked={ruleVersionDraft.nearbyCityEnabled}
                    onChange={(event) =>
                      setRuleVersionDraft((current) => ({
                        ...current,
                        nearbyCityEnabled: event.target.checked,
                      }))
                    }
                    type="checkbox"
                  />
                </label>
                <label className="filter-field">
                  <span>城市优选距离（公里）</span>
                  <input
                    min={0.1}
                    onChange={(event) =>
                      setRuleVersionDraft((current) => ({
                        ...current,
                        nearbyCityDistanceKm: Number(event.target.value),
                      }))
                    }
                    step={0.1}
                    type="number"
                    value={ruleVersionDraft.nearbyCityDistanceKm}
                  />
                </label>
                <label className="filter-field checkbox-field">
                  <span>城市兜底</span>
                  <input
                    checked={ruleVersionDraft.cityFallbackEnabled}
                    onChange={(event) =>
                      setRuleVersionDraft((current) => ({
                        ...current,
                        cityFallbackEnabled: event.target.checked,
                      }))
                    }
                    type="checkbox"
                  />
                </label>
              </div>
              <Button
                icon="rules"
                disabled={action !== null || !selectedRuleId}
                onClick={() => void handleCreateRuleVersion()}
                type="button"
                variant="primary"
              >
                新建草案版本
              </Button>
            </div>
          ) : null}
        </div>
        </section>
      ) : null}

      {activeSubview === "records" ? (
        <>
          <section className="content-section">
            <div className="section-title">
              <div>
                <h2>最近分配决策</h2>
                <p>保留策略、选择结果、失败原因和当时的执行批次，用于复核而不暴露联系方式。</p>
              </div>
              <span className="source-pill">{decisions.length} 条</span>
            </div>
            <DataTable
              columns={decisionColumns}
              emptyText={loading ? "正在加载分配决策..." : "暂无分配决策记录"}
              rows={decisions}
              stickyHeader="container"
            />
          </section>

          <section className="content-section">
            <div className="section-title">
              <div>
                <h2>门店评分快照</h2>
                <p>综合评分由已配置的核销转化能力、24 小时有效跟进率与门店权重计算，分配决策保留当时快照。</p>
              </div>
              {scoreData?.run ? (
                <span className="source-pill">{formatDateTime(scoreData.run.computed_at)}</span>
              ) : null}
            </div>
            <DataTable
              columns={scoreColumns}
              emptyText={loading ? "正在加载门店评分快照..." : "暂无评分快照"}
              rows={scoreData?.rows ?? []}
              stickyHeader="container"
            />
          </section>

          <section className="content-section">
            <div className="section-title">
              <div>
                <h2>试运行记录</h2>
                <p>记录每次批次执行范围、结果和操作人。</p>
              </div>
              <span className="source-pill">{cycles.length} 次</span>
            </div>
            <DataTable
              columns={cycleColumns}
              emptyText={loading ? "正在加载试运行记录..." : "暂无试运行记录"}
              rows={cycles}
              stickyHeader="container"
            />
          </section>

          <section className="content-section">
            <div className="section-title">
              <div>
                <h2>审计记录</h2>
                <p>保留试运行与重建的范围、确认状态和结果摘要。</p>
              </div>
            </div>
            <DataTable
              columns={auditColumns}
              emptyText={loading ? "正在加载审计记录..." : "暂无审计记录"}
              rows={auditLogs}
              stickyHeader="container"
            />
          </section>
        </>
      ) : null}

      {activeSubview === "headquarters" ? (
        <section className="content-section">
          <div className="section-title">
            <div>
              <h2>总部线索池</h2>
              <p>没有锚点、无可分配门店或候选轮次耗尽的线索会保留在总部池。</p>
            </div>
            <span className="source-pill">{headquartersEntries.length} 条</span>
          </div>
          <DataTable
            columns={headquartersColumns}
            emptyText={loading ? "正在加载总部线索池..." : "总部池暂无线索"}
            rows={headquartersEntries}
            stickyHeader="container"
          />
        </section>
      ) : null}

    </div>
  );
}
