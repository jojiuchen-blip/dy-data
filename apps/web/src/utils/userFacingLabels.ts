type LabelMap = Readonly<Record<string, string>>;

function displayEnumLabel(
  value: string | null | undefined,
  labels: LabelMap,
  fallback: string,
  context: string,
): string {
  const normalized = value?.trim();
  if (!normalized) {
    return "-";
  }
  const label = labels[normalized];
  if (label) {
    return label;
  }
  if (import.meta.env.DEV) {
    console.warn(`[user-facing-label] Unknown ${context}`, normalized);
  }
  return fallback;
}

const orderStatusLabels: LabelMap = {
  active: "履约中",
  fulfilling: "履约中",
  paid: "履约中",
  converted: "已核销",
  fulfilled: "已核销",
  verified: "已核销",
  refunded: "已退款",
  refund: "已退款",
  cancelled: "已关闭",
  canceled: "已关闭",
  closed: "已关闭",
};

const followUpTimingStateLabels: LabelMap = {
  active: "跟进有效期内",
  protected: "跟进保护期内",
  expired: "跟进已超时",
  inactive: "当前轮次不可用",
};

const clueReasonLabels: LabelMap = {
  timeout: "超期失效",
  follow_failed: "线索战败",
  follow_lost: "线索战败",
  request_store_change: "客户要求换门店",
  manual: "人工调整",
  order_closed: "订单已关闭",
  order_verified: "订单已核销",
  order_refunded: "订单已退款",
  allocated_to_store: "已分配至门店",
  sla_expired: "首次跟进时限已到",
  protection_expired: "跟进保护期已结束",
  terminal_closed: "线索已关闭",
  reassigned: "已重新分配",
  correction: "管理员修正",
  headquarters_pool_retained: "保留在总部线索池",
  sale_store_unmapped: "销售门店未匹配",
  rule_version_unavailable: "暂无可用分配规则",
  order_id_missing: "缺少订单编号",
  strategy_disabled: "分配策略未启用",
  lead_not_active: "线索当前不可分配",
  current_self_owned_round_exists: "已存在当前门店跟进轮次",
  selected: "已选中门店",
  no_candidate: "无可分配门店",
  follow_poi_missing: "缺少锚点门店",
  strategies_exhausted: "轮次候选已耗尽",
  "核销保护期内": "核销保护期内",
  "线索战败": "线索战败",
};

const syncJobNameLabels: LabelMap = {
  orders: "订单数据同步",
  verify_records: "核销数据同步",
  shop_pois: "门店信息同步",
  aweme_bindings: "子机构号绑定同步",
  clues: "线索数据同步",
  douyin_collection: "抖音数据采集",
  collect_and_settle: "数据采集与结算重建",
  settlement: "结算结果重建",
  settlement_rebuild: "结算结果重建",
  backend_aweme_export: "子机构号浏览器导出",
  manual_backend_aweme_export: "手动子机构号浏览器导出",
};

const syncPhaseNameLabels: LabelMap = {
  orders: "订单数据",
  verify_records: "核销数据",
  shop_pois: "门店信息",
  aweme_bindings: "子机构号绑定",
  clues: "线索数据",
  clue_master_rebuild: "线索主表重建",
  clue_center_rebuild: "线索中心重建",
  clue_master_refresh: "线索主表刷新",
  clue_center_refresh: "线索中心刷新",
  clue_follow_up_due: "跟进时效处理",
  store_score_snapshot: "门店评分快照",
  backend_aweme_export: "子机构号浏览器导出",
  settlement: "结算结果",
};

const syncFailureReasonLabels: LabelMap = {
  "open api returned 0 rows": "开放接口未返回数据",
  "cdp endpoint unavailable": "浏览器导出服务暂不可用",
  "temporary douyin api error": "抖音开放接口暂时不可用",
  "[redacted sensitive error]": "任务执行失败，错误详情已隐藏",
};

const workerModeLabels: LabelMap = {
  collect_and_settle: "接口采集并重建结算",
  settlement_only: "只重建结算",
  backfill: "历史数据回填",
  browser_export_only: "只执行浏览器导出",
};

const allocationStrategyLabels: LabelMap = {
  sales_store_priority: "销售店优先（10 公里）",
  nearby_city_optimization: "15 公里城市优选",
  city_fallback: "城市兜底",
};

const allocationDecisionStatusLabels: LabelMap = {
  assigned: "已分配",
  selected: "已分配",
  skipped: "已跳过",
  headquarters: "进入总部线索池",
};

const allocationCycleStatusLabels: LabelMap = {
  queued: "待执行",
  running: "执行中",
  completed: "已完成",
  failed: "失败",
  cancelled: "已取消",
  canceled: "已取消",
};

const allocationEventTypeLabels: LabelMap = {
  trial_executed: "已执行试运行",
  trial_rebuilt: "已重建试运行",
  rule_created: "已创建分配规则",
  rule_version_created: "已创建规则版本",
  rule_version_published: "已发布规则版本",
  rule_version_retired: "已停用规则版本",
};

const allocationExecutionModeLabels: LabelMap = {
  trial: "试运行",
  formal: "正式运行",
  production: "正式运行",
  live: "正式运行",
};

const allocationCycleTypeLabels: LabelMap = {
  trial: "试运行",
  rebuild: "试运行重建",
};

const userRoleLabels: LabelMap = {
  admin: "管理员",
  highest_admin: "最高管理员",
  super_admin: "最高管理员",
  store: "门店账号",
  viewer: "只读账号",
};

export function displayOrderStatus(value: string | null | undefined): string {
  return displayEnumLabel(value, orderStatusLabels, "未知订单状态", "order status");
}

export function displayFollowUpTimingState(value: string | null | undefined): string {
  return displayEnumLabel(
    value,
    followUpTimingStateLabels,
    "未知时效状态",
    "follow-up timing state",
  );
}

export function displayClueReason(value: string | null | undefined): string {
  return displayEnumLabel(value, clueReasonLabels, "未知原因", "clue reason");
}

export function displaySyncJobName(value: string | null | undefined): string {
  return displayEnumLabel(value, syncJobNameLabels, "未知任务类型", "sync job name");
}

export function displaySyncPhaseName(value: string | null | undefined): string {
  return displayEnumLabel(value, syncPhaseNameLabels, "未知处理阶段", "sync phase name");
}

export function displaySyncFailureReason(value: string | null | undefined): string {
  const normalized = value?.trim();
  if (!normalized) {
    return "-";
  }
  const label = syncFailureReasonLabels[normalized.toLowerCase()];
  if (label) {
    return label;
  }
  if (import.meta.env.DEV) {
    console.warn("[user-facing-label] Unknown sync failure reason", normalized);
  }
  return "任务执行失败，请查看服务日志";
}

export function displayWorkerMode(value: string | null | undefined): string {
  return displayEnumLabel(value, workerModeLabels, "未知运行模式", "worker mode");
}

export function displayAllocationStrategy(value: string | null | undefined): string {
  return displayEnumLabel(
    value,
    allocationStrategyLabels,
    "未知分配策略",
    "allocation strategy",
  );
}

export function displayAllocationDecisionStatus(
  value: string | null | undefined,
): string {
  return displayEnumLabel(
    value,
    allocationDecisionStatusLabels,
    "未知分配结果",
    "allocation decision status",
  );
}

export function displayAllocationCycleStatus(value: string | null | undefined): string {
  return displayEnumLabel(
    value,
    allocationCycleStatusLabels,
    "未知批次状态",
    "allocation cycle status",
  );
}

export function displayAllocationEventType(value: string | null | undefined): string {
  return displayEnumLabel(
    value,
    allocationEventTypeLabels,
    "未知事件类型",
    "allocation event type",
  );
}

export function displayAllocationExecutionMode(
  value: string | null | undefined,
): string {
  return displayEnumLabel(
    value,
    allocationExecutionModeLabels,
    "未知执行方式",
    "allocation execution mode",
  );
}

export function displayAllocationCycleType(value: string | null | undefined): string {
  return displayEnumLabel(
    value,
    allocationCycleTypeLabels,
    "未知批次类型",
    "allocation cycle type",
  );
}

export function displayUserRole(value: string | null | undefined): string {
  return displayEnumLabel(value, userRoleLabels, "未知角色", "user role");
}
