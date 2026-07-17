import type {
  ApiResponse,
  ClueAllocationAuditLogData,
  ClueAllocationCycle,
  ClueAllocationCycleData,
  ClueAllocationCycleExecution,
  ClueAllocationCyclePreview,
  ClueAllocationCyclePreviewRequest,
  ClueAllocationCycleRebuildRequest,
  ClueAllocationCycleRequest,
  ClueAllocationDecisionData,
  ClueAllocationEligibleLead,
  ClueAllocationEligibleLeadData,
  ClueAllocationRule,
  ClueAllocationRuleCreate,
  ClueAllocationRuleDetailData,
  ClueAllocationRuleListData,
  ClueAllocationRuleVersion,
  ClueAllocationRuleVersionWrite,
  ClueAssignmentRound,
  ClueAssignmentRoundData,
  ClueFilterMetadata,
  ClueFollowUpPayload,
  ClueFollowUpRecord,
  ClueHeadquartersPoolData,
  ClueOrderDetail,
  ClueOverviewFilters,
  ClueOverviewMetrics,
  CluePhoneReveal,
  Pagination,
  StoreScoreSnapshotData,
} from "../types/dashboard";
import { createClueDemoState } from "./clueDemoGenerator";
import type {
  ClueDemoPreviewToken,
  ClueDemoState,
} from "./clueDemoTypes";

export interface ClueDemoRoundQuery {
  filters: ClueOverviewFilters;
  page: number;
  pageSize: number;
}

export interface ClueDemoExportFile {
  filename: string;
  content: string;
  mimeType: "text/csv;charset=utf-8";
}

export interface ClueDemoHeadquartersFilters {
  pool_status?: string;
  reason?: string;
  entered_date_start?: string;
  entered_date_end?: string;
  order_status?: string;
  order_id?: string;
  page?: number;
  page_size?: number;
}

export class ClueDemoRepositoryError extends Error {
  constructor(
    public readonly status: number,
    message: string,
  ) {
    super(message);
    this.name = "ClueDemoRepositoryError";
  }
}

function demoResponse<T>(data: T, generatedAt: string): ApiResponse<T> {
  return {
    data: structuredClone(data),
    meta: { generated_at: generatedAt, source: "demo" },
  };
}

function paginate<T>(
  rows: T[],
  page: number,
  pageSize: number,
): { rows: T[]; pagination: Pagination } {
  const safeSize = Math.max(1, Math.min(Math.floor(pageSize) || 20, 100));
  const totalPages = Math.max(1, Math.ceil(rows.length / safeSize));
  const safePage = Math.max(1, Math.min(Math.floor(page) || 1, totalPages));
  const start = (safePage - 1) * safeSize;
  return {
    rows: rows.slice(start, start + safeSize),
    pagination: {
      page: safePage,
      page_size: safeSize,
      total: rows.length,
      total_pages: totalPages,
    },
  };
}

function uniqueSorted(values: Array<string | null | undefined>): string[] {
  return [...new Set(values.filter((value): value is string => Boolean(value)))].sort(
    (left, right) => left.localeCompare(right, "zh-CN"),
  );
}

export class ClueDemoRepository {
  private state: ClueDemoState = createClueDemoState();

  reset(): void {
    this.state = createClueDemoState();
  }

  getFilters(): ApiResponse<ClueFilterMetadata> {
    return demoResponse(
      {
        assigned_stores: this.state.stores.map((store) => ({
          store_id: store.store_id,
          store_name: store.store_name,
        })),
        assigned_provinces: uniqueSorted(
          this.state.stores.map((store) => store.province),
        ),
        assigned_cities: uniqueSorted(
          this.state.stores.map((store) => store.city),
        ),
        product_types: uniqueSorted(
          Object.values(this.state.orderDetails).map(
            (detail) => detail.product_type,
          ),
        ),
        default_product_type: "all",
        lead_statuses: uniqueSorted(
          this.state.rounds.map((round) => round.lead_status),
        ),
        round_statuses: uniqueSorted(
          this.state.rounds.map((round) => round.round_status),
        ),
        verification_statuses: [
          "unverified",
          "self_store_verified",
          "other_store_verified",
        ],
      },
      this.state.generatedAt,
    );
  }

  getOverview(
    filters: ClueOverviewFilters = {},
  ): ApiResponse<ClueOverviewMetrics> {
    const rows = this.filterRounds(filters);
    const total = rows.length;
    const followed = rows.filter((round) => Boolean(round.followed_at)).length;
    const successful = rows.filter((round) =>
      ["success", "appointment"].includes(round.follow_result),
    ).length;
    const selfVerified = rows.filter(
      (round) => round.is_self_store_verified,
    ).length;
    const pendingReassign = rows.filter(
      (round) =>
        round.round_no === round.current_round_no &&
        (round.lead_status === "pending_reassign" ||
          ["failed_pending_reassign", "expired_pending_reassign"].includes(
            round.round_status,
          )),
    ).length;

    return demoResponse(
      {
        total_clues: total,
        active_clues: rows.filter(
          (round) =>
            round.is_current_round &&
            ["active_unfollowed", "active_followed"].includes(
              round.round_status,
            ),
        ).length,
        follow_rate: total ? followed / total : 0,
        follow_success_rate: total ? successful / total : 0,
        verified_count: selfVerified,
        self_store_verify_rate: total ? selfVerified / total : 0,
        pending_reassign_count: pendingReassign,
      },
      this.state.generatedAt,
    );
  }

  getAssignmentRounds(
    query: ClueDemoRoundQuery,
  ): ApiResponse<ClueAssignmentRoundData> {
    const rows = this.filterRounds(query.filters).sort((left, right) => {
      const dateOrder = (right.assigned_at ?? "").localeCompare(
        left.assigned_at ?? "",
      );
      return dateOrder || right.round_no - left.round_no;
    });
    return demoResponse(
      paginate(rows, query.page, query.pageSize),
      this.state.generatedAt,
    );
  }

  getOrderDetail(orderId: string): ApiResponse<ClueOrderDetail> {
    const detail = this.state.orderDetails[orderId];
    if (!detail) {
      throw new ClueDemoRepositoryError(404, "演示线索不存在");
    }
    return demoResponse(detail, this.state.generatedAt);
  }

  getOrderPhone(orderId: string): ApiResponse<CluePhoneReveal> {
    const detail = this.state.orderDetails[orderId];
    if (!detail) {
      throw new ClueDemoRepositoryError(404, "演示线索不存在");
    }
    const sequence = orderId.replace("DEMO-ORDER-", "");
    return demoResponse(
      {
        order_id: orderId,
        phone: `DEMO-PHONE-${sequence}`,
        phone_masked: detail.phone_masked,
      },
      this.state.generatedAt,
    );
  }

  saveFollowUp(
    orderId: string,
    payload: ClueFollowUpPayload,
  ): ApiResponse<ClueFollowUpRecord> {
    const detail = this.state.orderDetails[orderId];
    if (!detail) {
      throw new ClueDemoRepositoryError(404, "演示线索不存在");
    }
    const round = detail.rounds.find(
      (candidate) =>
        candidate.assignment_round_id === payload.assignment_round_id,
    );
    if (!round) {
      throw new ClueDemoRepositoryError(404, "演示分配轮次不存在");
    }
    if (!round.is_current_round || !round.can_operate_current_round) {
      throw new ClueDemoRepositoryError(409, "只能操作当前有效分配轮次");
    }

    const createdAt = new Date().toISOString();
    const record: ClueFollowUpRecord = {
      follow_up_record_id: this.nextId("DEMO-FOLLOW-UP-"),
      order_id: orderId,
      assignment_round_id: round.assignment_round_id,
      round_no: round.round_no,
      assigned_store_id: round.assigned_store_id,
      assigned_store_name: round.assigned_store_name,
      follow_result: payload.follow_result,
      note: payload.note,
      timing_state: "protected",
      status_reason: "演示跟进保护期内",
      is_deleted: false,
      deleted_at: null,
      deleted_by_user_id: null,
      deleted_by_username: null,
      deletion_reason: null,
      operator_user_id: "DEMO-USER-ADMIN",
      operator_username: "演示最高管理员",
      created_at: createdAt,
    };
    this.state.followUpRecords.push(record);
    detail.follow_up_records.push(record);
    round.followed_at = createdAt;
    round.follow_result = payload.follow_result;

    if (
      payload.follow_result === "lost" ||
      payload.follow_result === "request_store_change"
    ) {
      round.round_effective_status = "inactive";
      round.can_operate_current_round = false;
      round.is_current_round = false;
      round.round_status = "failed_pending_reassign";
      round.store_display_status = "主动战败";
      round.lead_status = "pending_reassign";
      round.expires_at = createdAt;
      round.remaining_reassign_seconds = 0;
      round.reassign_reason =
        payload.follow_result === "lost"
          ? "follow_lost"
          : "request_store_change";
      round.reassigned_at = createdAt;
      this.advanceAfterRoundFailure(orderId, round, round.reassign_reason);
    } else {
      round.round_status = "active_followed";
      round.store_display_status = "已跟进";
      round.follow_result = payload.follow_result;
      round.followed_at = createdAt;
      round.timing_state = "protected";
      round.status_reason = "演示跟进保护期内";
      round.expires_at = new Date(
        new Date(createdAt).getTime() + 7 * 24 * 60 * 60 * 1000,
      ).toISOString();
      round.remaining_reassign_seconds = 7 * 24 * 60 * 60;
      detail.lead_status = "active";
      for (const candidate of detail.rounds) {
        candidate.current_round_status = round.round_status;
      }
    }

    this.state.generatedAt = createdAt;
    return demoResponse(record, createdAt);
  }

  deleteFollowUpRecord(
    followUpRecordId: string,
  ): ApiResponse<ClueFollowUpRecord> {
    const record = this.state.followUpRecords.find(
      (candidate) => candidate.follow_up_record_id === followUpRecordId,
    );
    if (!record) {
      throw new ClueDemoRepositoryError(404, "演示跟进记录不存在");
    }
    if (record.is_deleted) {
      throw new ClueDemoRepositoryError(409, "演示跟进记录已撤销");
    }
    const deletedAt = new Date().toISOString();
    record.is_deleted = true;
    record.deleted_at = deletedAt;
    record.deleted_by_user_id = "DEMO-USER-ADMIN";
    record.deleted_by_username = "演示最高管理员";
    record.deletion_reason = "reversed_by_highest_admin";
    this.state.generatedAt = deletedAt;
    return demoResponse(record, deletedAt);
  }

  exportAssignmentRounds(
    filters: ClueOverviewFilters = {},
  ): ClueDemoExportFile {
    const headers = [
      "订单ID",
      "轮次",
      "状态",
      "分配时间",
      "演示门店",
      "演示手机号（脱敏）",
      "商品",
      "跟进结果",
      "流转原因",
      "核销时间",
    ];
    const rows = this.filterRounds(filters).map((round) => [
      round.order_id,
      String(round.round_no),
      round.store_display_status ?? round.round_status,
      round.assigned_at ?? "",
      round.assigned_store_name ?? "",
      round.phone_masked,
      round.product_name ?? "",
      round.follow_result,
      round.reassign_reason ?? "",
      round.verified_at ?? "",
    ]);
    const content = [headers, ...rows]
      .map((row) => row.map((value) => this.escapeCsv(value)).join(","))
      .join("\r\n");
    return {
      filename: `demo-clue-assignment-rounds-${this.state.generatedAt.slice(0, 10)}.csv`,
      content: `\ufeff${content}`,
      mimeType: "text/csv;charset=utf-8",
    };
  }

  getEligibleLeads(): ApiResponse<ClueAllocationEligibleLeadData> {
    const rows = [...this.state.eligibleLeads].sort((left, right) =>
      right.updated_at.localeCompare(left.updated_at),
    );
    return demoResponse(paginate(rows, 1, 100), this.state.generatedAt);
  }

  getHeadquartersPool(
    filters: ClueDemoHeadquartersFilters = {},
  ): ApiResponse<ClueHeadquartersPoolData> {
    if (
      filters.entered_date_start &&
      filters.entered_date_end &&
      filters.entered_date_end < filters.entered_date_start
    ) {
      throw new ClueDemoRepositoryError(422, "进入日期止不能早于进入日期起");
    }
    const rows = this.state.headquartersPool
      .filter((entry) => {
        const enteredDate = entry.entered_at.slice(0, 10);
        if (filters.pool_status && entry.status !== filters.pool_status) return false;
        if (filters.reason && entry.reason !== filters.reason) return false;
        if (
          filters.entered_date_start &&
          enteredDate < filters.entered_date_start
        ) {
          return false;
        }
        if (filters.entered_date_end && enteredDate > filters.entered_date_end) {
          return false;
        }
        if (filters.order_status && entry.order_status !== filters.order_status) {
          return false;
        }
        if (
          filters.order_id &&
          !entry.order_id?.toLowerCase().includes(filters.order_id.toLowerCase())
        ) {
          return false;
        }
        return true;
      })
      .sort((left, right) => right.entered_at.localeCompare(left.entered_at));
    const paged = paginate(rows, filters.page ?? 1, filters.page_size ?? 50);
    return demoResponse(
      {
        ...paged,
        summary: {
          current_inventory: this.state.headquartersPool.filter(
            (entry) => entry.status === "active",
          ).length,
          filtered_total: rows.length,
        },
        filter_options: {
          pool_statuses: uniqueSorted(
            this.state.headquartersPool.map((entry) => entry.status),
          ),
          reasons: uniqueSorted(
            this.state.headquartersPool.map((entry) => entry.reason),
          ),
          order_statuses: uniqueSorted(
            this.state.headquartersPool.map((entry) => entry.order_status),
          ),
        },
      },
      this.state.generatedAt,
    );
  }

  getCycles(): ApiResponse<ClueAllocationCycleData> {
    const rows = [...this.state.cycles].sort((left, right) =>
      right.created_at.localeCompare(left.created_at),
    );
    return demoResponse(paginate(rows, 1, 100), this.state.generatedAt);
  }

  getAuditLogs(): ApiResponse<ClueAllocationAuditLogData> {
    const rows = [...this.state.auditLogs].sort((left, right) =>
      right.created_at.localeCompare(left.created_at),
    );
    return demoResponse(paginate(rows, 1, 100), this.state.generatedAt);
  }

  previewCycle(
    payload: ClueAllocationCyclePreviewRequest,
  ): ApiResponse<ClueAllocationCyclePreview> {
    const operation = payload.operation ?? "trial";
    let sourceCycleId: string | null = null;
    let requestedLeadKeys: string[];
    if (operation === "rebuild") {
      sourceCycleId = payload.source_cycle_id ?? null;
      const sourceCycle = this.state.cycles.find(
        (cycle) => cycle.allocation_cycle_id === sourceCycleId,
      );
      if (!sourceCycle) {
        throw new ClueDemoRepositoryError(404, "来源试运行批次不存在");
      }
      requestedLeadKeys = [...sourceCycle.selected_lead_keys];
    } else {
      requestedLeadKeys = [...new Set(payload.lead_keys ?? [])].sort();
      if (!requestedLeadKeys.length) {
        throw new ClueDemoRepositoryError(422, "请至少选择一条演示线索");
      }
    }

    const activeLeadKeySet = new Set(
      operation === "trial"
        ? this.state.eligibleLeads.map((lead) => lead.lead_key)
        : Object.values(this.state.orderDetails).map((detail) =>
            detail.order_id.replace("DEMO-ORDER-", "DEMO-LEAD-"),
          ),
    );
    const activeLeadKeys = requestedLeadKeys.filter((leadKey) =>
      activeLeadKeySet.has(leadKey),
    );
    const createdAt = new Date().toISOString();
    const expiresAt = new Date(
      new Date(createdAt).getTime() + 5 * 60 * 1000,
    ).toISOString();
    const token = this.nextId("DEMO-PREVIEW-");
    this.state.previewTokens.set(token, {
      token,
      operation,
      leadKeys: activeLeadKeys,
      sourceCycleId,
      expiresAt,
    });
    const summary = {
      assigned: activeLeadKeys.length,
      headquarters: 0,
      skipped: requestedLeadKeys.length - activeLeadKeys.length,
    };
    this.appendAudit(
      "cycle_previewed",
      sourceCycleId,
      {},
      summary,
      { operation, preview_token: token },
      Boolean(payload.privileged_confirmation),
    );
    this.state.generatedAt = createdAt;
    return demoResponse(
      {
        requested_lead_count: requestedLeadKeys.length,
        active_lead_count: activeLeadKeys.length,
        lead_keys: activeLeadKeys,
        summary,
        operation,
        source_cycle_id: sourceCycleId,
        preview_token: token,
        preview_expires_at: expiresAt,
      },
      createdAt,
    );
  }

  runTrial(
    payload: ClueAllocationCycleRequest,
  ): ApiResponse<ClueAllocationCycleExecution> {
    if (!payload.confirm) {
      throw new ClueDemoRepositoryError(422, "试运行需要明确确认");
    }
    const preview = this.requirePreviewToken(
      payload.preview_token,
      "trial",
      payload.lead_keys,
      null,
    );
    return this.executeCycle({
      cycleType: "trial",
      preview,
      parentCycleId: null,
      privilegedConfirmation: false,
    });
  }

  rebuildTrial(
    payload: ClueAllocationCycleRebuildRequest,
  ): ApiResponse<ClueAllocationCycleExecution> {
    if (!payload.confirm || !payload.privileged_confirmation) {
      throw new ClueDemoRepositoryError(422, "重建需要最高管理员二次确认");
    }
    if (
      !this.state.cycles.some(
        (cycle) => cycle.allocation_cycle_id === payload.source_cycle_id,
      )
    ) {
      throw new ClueDemoRepositoryError(404, "来源试运行批次不存在");
    }
    const preview = this.requirePreviewToken(
      payload.preview_token,
      "rebuild",
      undefined,
      payload.source_cycle_id,
    );
    return this.executeCycle({
      cycleType: "rebuild",
      preview,
      parentCycleId: payload.source_cycle_id,
      privilegedConfirmation: true,
    });
  }

  getRules(): ApiResponse<ClueAllocationRuleListData> {
    const rows = this.state.rules
      .map((bundle) => bundle.rule)
      .sort((left, right) => right.updated_at.localeCompare(left.updated_at));
    return demoResponse(paginate(rows, 1, 100), this.state.generatedAt);
  }

  getRuleDetail(ruleId: string): ApiResponse<ClueAllocationRuleDetailData> {
    const bundle = this.state.rules.find((candidate) => candidate.rule.rule_id === ruleId);
    if (!bundle) {
      throw new ClueDemoRepositoryError(404, "演示分配规则不存在");
    }
    return demoResponse(
      {
        rule: bundle.rule,
        versions: [...bundle.versions].sort(
          (left, right) => right.version_no - left.version_no,
        ),
      },
      this.state.generatedAt,
    );
  }

  getDecisions(): ApiResponse<ClueAllocationDecisionData> {
    const rows = [...this.state.decisions].sort((left, right) =>
      right.executed_at.localeCompare(left.executed_at),
    );
    return demoResponse(paginate(rows, 1, 100), this.state.generatedAt);
  }

  getStoreScores(): ApiResponse<StoreScoreSnapshotData> {
    const generatedDate = new Date(this.state.generatedAt);
    const windowStart = new Date(
      generatedDate.getTime() - 30 * 24 * 60 * 60 * 1000,
    );
    return demoResponse(
      {
        run: {
          snapshot_run_id: "DEMO-SCORE-RUN-001",
          snapshot_date: this.state.generatedAt.slice(0, 10),
          run_mode: "demo",
          window_start: windowStart.toISOString(),
          window_end: this.state.generatedAt,
          candidate_store_count: this.state.stores.length,
          snapshot_count: this.state.storeScores.length,
          triggered_by: "DEMO-USER-ADMIN",
          computed_at: this.state.generatedAt,
        },
        rows: [...this.state.storeScores].sort(
          (left, right) => right.composite_score - left.composite_score,
        ),
        pagination: {
          page: 1,
          page_size: this.state.storeScores.length,
          total: this.state.storeScores.length,
          total_pages: 1,
        },
      },
      this.state.generatedAt,
    );
  }

  createRule(
    payload: ClueAllocationRuleCreate,
  ): ApiResponse<ClueAllocationRule> {
    const name = payload.name.trim();
    if (!name) {
      throw new ClueDemoRepositoryError(422, "规则名称不能为空");
    }
    if (this.state.rules.some((bundle) => bundle.rule.name === name)) {
      throw new ClueDemoRepositoryError(409, "规则名称已存在");
    }
    const createdAt = new Date().toISOString();
    const rule: ClueAllocationRule = {
      rule_id: this.nextId("DEMO-RULE-"),
      name,
      scope: structuredClone(payload.scope),
      created_at: createdAt,
      updated_at: createdAt,
    };
    this.state.rules.push({ rule, versions: [] });
    this.appendAudit(
      "rule_created",
      null,
      {},
      { rule_id: rule.rule_id },
      { name: rule.name, scope: rule.scope },
      false,
    );
    this.state.generatedAt = createdAt;
    return demoResponse(rule, createdAt);
  }

  createRuleVersion(
    ruleId: string,
    payload: ClueAllocationRuleVersionWrite,
  ): ApiResponse<ClueAllocationRuleVersion> {
    const bundle = this.state.rules.find((candidate) => candidate.rule.rule_id === ruleId);
    if (!bundle) {
      throw new ClueDemoRepositoryError(404, "演示分配规则不存在");
    }
    const createdAt = new Date().toISOString();
    const versionNo = Math.max(0, ...bundle.versions.map((version) => version.version_no)) + 1;
    const version: ClueAllocationRuleVersion = {
      rule_version_id: this.nextId("DEMO-RULE-VERSION-"),
      rule_id: ruleId,
      version_no: versionNo,
      status: "draft",
      auto_expiry_enabled: payload.auto_expiry_enabled,
      first_follow_up_sla_hours: payload.first_follow_up_sla_hours,
      protection_days: payload.protection_days,
      conversion_weight: payload.conversion_weight,
      follow_24h_weight: payload.follow_24h_weight,
      lookback_days: payload.lookback_days,
      min_samples: payload.min_samples,
      strategy_configs: structuredClone(payload.strategy_configs),
      created_at: createdAt,
      updated_at: createdAt,
      published_at: null,
      retired_at: null,
    };
    bundle.versions.push(version);
    bundle.rule.updated_at = createdAt;
    this.appendAudit(
      "rule_version_created",
      null,
      {},
      { rule_version_id: version.rule_version_id, status: version.status },
      { rule_id: ruleId, version_no: versionNo },
      false,
    );
    this.state.generatedAt = createdAt;
    return demoResponse(version, createdAt);
  }

  publishRuleVersion(
    ruleVersionId: string,
  ): ApiResponse<ClueAllocationRuleVersion> {
    const located = this.findRuleVersion(ruleVersionId);
    if (located.version.status !== "draft") {
      throw new ClueDemoRepositoryError(409, "只有草案版本可以发布");
    }
    const updatedAt = new Date().toISOString();
    for (const version of located.bundle.versions) {
      if (version.status === "published") {
        version.status = "retired";
        version.retired_at = updatedAt;
        version.updated_at = updatedAt;
      }
    }
    located.version.status = "published";
    located.version.published_at = updatedAt;
    located.version.retired_at = null;
    located.version.updated_at = updatedAt;
    located.bundle.rule.updated_at = updatedAt;
    this.appendAudit(
      "rule_version_published",
      null,
      { status: "draft" },
      { status: "published" },
      { rule_version_id: ruleVersionId },
      false,
    );
    this.state.generatedAt = updatedAt;
    return demoResponse(located.version, updatedAt);
  }

  retireRuleVersion(
    ruleVersionId: string,
  ): ApiResponse<ClueAllocationRuleVersion> {
    const located = this.findRuleVersion(ruleVersionId);
    if (located.version.status !== "published") {
      throw new ClueDemoRepositoryError(409, "只有已发布版本可以退役");
    }
    const updatedAt = new Date().toISOString();
    located.version.status = "retired";
    located.version.retired_at = updatedAt;
    located.version.updated_at = updatedAt;
    located.bundle.rule.updated_at = updatedAt;
    this.appendAudit(
      "rule_version_retired",
      null,
      { status: "published" },
      { status: "retired" },
      { rule_version_id: ruleVersionId },
      false,
    );
    this.state.generatedAt = updatedAt;
    return demoResponse(located.version, updatedAt);
  }

  private requirePreviewToken(
    tokenValue: string | undefined,
    operation: "trial" | "rebuild",
    leadKeys: string[] | undefined,
    sourceCycleId: string | null,
  ): ClueDemoPreviewToken {
    const preview = tokenValue
      ? this.state.previewTokens.get(tokenValue)
      : undefined;
    if (!preview) {
      throw new ClueDemoRepositoryError(409, "预览令牌不存在或已失效");
    }
    if (new Date(preview.expiresAt).getTime() <= Date.now()) {
      this.state.previewTokens.delete(preview.token);
      throw new ClueDemoRepositoryError(409, "预览令牌已过期，请重新预览");
    }
    if (
      preview.operation !== operation ||
      preview.sourceCycleId !== sourceCycleId
    ) {
      throw new ClueDemoRepositoryError(409, "预览令牌与当前操作不匹配");
    }
    if (leadKeys) {
      const requested = [...new Set(leadKeys)].sort();
      if (requested.join("|") !== preview.leadKeys.join("|")) {
        throw new ClueDemoRepositoryError(409, "线索选择已变化，请重新预览");
      }
    }
    return preview;
  }

  private executeCycle({
    cycleType,
    preview,
    parentCycleId,
    privilegedConfirmation,
  }: {
    cycleType: "trial" | "rebuild";
    preview: ClueDemoPreviewToken;
    parentCycleId: string | null;
    privilegedConfirmation: boolean;
  }): ApiResponse<ClueAllocationCycleExecution> {
    const createdAt = new Date().toISOString();
    const cycleId = this.nextId("DEMO-CYCLE-");
    const summary = { assigned: 0, headquarters: 0, skipped: 0 };
    for (const leadKey of preview.leadKeys) {
      const result = this.allocateLead(
        leadKey,
        cycleId,
        cycleType,
        parentCycleId,
      );
      summary[result] += 1;
    }
    const activeLeadCount = summary.assigned + summary.headquarters;
    const cycle: ClueAllocationCycle = {
      allocation_cycle_id: cycleId,
      cycle_type: cycleType,
      execution_mode: "trial",
      status: "completed",
      parent_cycle_id: parentCycleId,
      selected_lead_keys: [...preview.leadKeys],
      requested_lead_count: preview.leadKeys.length,
      active_lead_count: activeLeadCount,
      planned_impact: {
        assigned: preview.leadKeys.length,
        headquarters: 0,
        skipped: 0,
      },
      actual_impact: { ...summary },
      actor: "DEMO-USER-ADMIN",
      privileged_confirmation: privilegedConfirmation,
      created_at: createdAt,
      executed_at: createdAt,
      completed_at: createdAt,
    };
    this.state.cycles.push(cycle);
    const selected = new Set(preview.leadKeys);
    this.state.eligibleLeads = this.state.eligibleLeads.filter(
      (lead) => !selected.has(lead.lead_key),
    );
    this.state.previewTokens.delete(preview.token);
    this.appendAudit(
      cycleType === "rebuild" ? "cycle_rebuilt" : "cycle_executed",
      cycleId,
      { eligible_lead_count: this.state.eligibleLeads.length + activeLeadCount },
      summary,
      { parent_cycle_id: parentCycleId, selected_lead_keys: preview.leadKeys },
      privilegedConfirmation,
    );
    this.state.generatedAt = createdAt;
    return demoResponse(
      {
        allocation_cycle_id: cycleId,
        cycle_type: cycleType,
        execution_mode: "trial",
        status: "completed",
        requested_lead_count: preview.leadKeys.length,
        active_lead_count: activeLeadCount,
        privileged_confirmation: privilegedConfirmation,
        parent_cycle_id: parentCycleId,
        summary,
      },
      createdAt,
    );
  }

  private allocateLead(
    leadKey: string,
    cycleId: string,
    cycleType: "trial" | "rebuild",
    sourceCycleId: string | null,
  ): "assigned" | "headquarters" | "skipped" {
    const eligibleLead = this.state.eligibleLeads.find(
      (lead) => lead.lead_key === leadKey,
    );
    const orderId =
      eligibleLead?.order_id ?? leadKey.replace("DEMO-LEAD-", "DEMO-ORDER-");
    const detail = orderId ? this.state.orderDetails[orderId] : undefined;
    if (!detail || !orderId) return "skipped";

    const previousRound = [...detail.rounds].sort(
      (left, right) => right.round_no - left.round_no,
    )[0];
    const usedStoreIds = new Set(
      detail.rounds
        .map((round) => round.assigned_store_id)
        .filter((storeId): storeId is string => Boolean(storeId)),
    );
    const nextStore = this.state.stores.find(
      (store) =>
        store.city === detail.assigned_city && !usedStoreIds.has(store.store_id),
    );
    const executedAt = new Date().toISOString();
    for (const round of detail.rounds) {
      if (round.is_current_round) {
        round.is_current_round = false;
        round.can_operate_current_round = false;
        round.round_effective_status = "inactive";
        round.round_status = "failed_pending_reassign";
        round.store_display_status = "主动战败";
        round.reassign_reason = cycleType === "rebuild" ? "demo_rebuild" : "demo_trial";
        round.reassigned_at = executedAt;
      }
    }

    const matchingRule = this.state.rules.find(
      (bundle) => bundle.rule.scope.city_code === nextStore?.city_code,
    ) ?? this.state.rules[0];
    const publishedVersion = matchingRule?.versions.find(
      (version) => version.status === "published",
    );

    if (!nextStore) {
      detail.lead_status = "headquarters";
      for (const round of detail.rounds) {
        round.current_assignment_round_id = null;
        round.current_assigned_store_id = null;
        round.current_assigned_store_name = null;
        round.current_round_status = "headquarters";
      }
      if (
        !this.state.headquartersPool.some(
          (entry) => entry.lead_key === leadKey && entry.status === "active",
        )
      ) {
        this.state.headquartersPool.push({
          headquarters_pool_entry_id: this.nextId("DEMO-HQ-"),
          lead_key: leadKey,
          canonical_clue_id: detail.canonical_clue_id,
          order_id: orderId,
          order_status: previousRound?.order_current_status ?? "fulfilling",
          raw_order_status: "DEMO_FULFILLING",
          status: "active",
          reason: "all_strategies_exhausted",
          entered_at: executedAt,
          closed_at: null,
          close_reason: null,
          anchor_store_id: previousRound?.assigned_store_id ?? null,
          anchor_city: detail.assigned_city,
          anchor_city_code:
            this.state.stores.find(
              (store) => store.store_id === previousRound?.assigned_store_id,
            )?.city_code ?? null,
          source_assignment_round_id:
            previousRound?.assignment_round_id ?? null,
          source_decision_id: null,
          source_rule_version_id: publishedVersion?.rule_version_id ?? null,
          allocation_cycle_id: cycleId,
        });
      }
      this.state.decisions.push({
        decision_id: this.nextId("DEMO-DECISION-"),
        lead_key: leadKey,
        order_id: orderId,
        rule_id: matchingRule?.rule.rule_id ?? null,
        rule_version_id: publishedVersion?.rule_version_id ?? null,
        scope_type: matchingRule?.rule.scope.scope_type ?? null,
        scope_key: detail.assigned_city,
        strategy_type: "city_fallback",
        execution_order: null,
        allocation_cycle_id: cycleId,
        execution_mode: "trial",
        assignment_round_id: null,
        round_no: null,
        selected_store_id: null,
        selected_store_name: null,
        decision_status: "headquarters",
        reason: "all_strategies_exhausted",
        payload: { synthetic: true, supersedes_cycle_id: sourceCycleId },
        actor: "DEMO-USER-ADMIN",
        executed_at: executedAt,
      });
      return "headquarters";
    }

    const roundNumber = (previousRound?.round_no ?? 0) + 1;
    const assignmentRoundId = `DEMO-ROUND-${orderId.replace("DEMO-ORDER-", "")}-${String(roundNumber).padStart(2, "0")}`;
    const nextRound: ClueAssignmentRound = {
      assignment_round_id: assignmentRoundId,
      order_id: orderId,
      round_no: roundNumber,
      store_display_status: "待跟进",
      lead_status: "active",
      order_current_status: previousRound?.order_current_status ?? "fulfilling",
      current_assignment_round_id: assignmentRoundId,
      current_round_no: roundNumber,
      current_round_status: "active_unfollowed",
      current_assigned_store_id: nextStore.store_id,
      current_assigned_store_name: nextStore.store_name,
      is_current_round: true,
      round_effective_status: "active",
      can_operate_current_round: true,
      timing_state: "active",
      status_reason: cycleType === "rebuild" ? "试运行重建生成" : "试运行生成",
      round_status: "active_unfollowed",
      assigned_at: executedAt,
      expires_at: new Date(
        new Date(executedAt).getTime() + 24 * 60 * 60 * 1000,
      ).toISOString(),
      remaining_reassign_seconds: 24 * 60 * 60,
      assigned_store_id: nextStore.store_id,
      assigned_store_name: nextStore.store_name,
      phone_masked: detail.phone_masked,
      product_name: detail.product_name,
      product_type: detail.product_type,
      author_nickname: detail.author_nickname,
      followed_at: null,
      follow_result: "pending",
      reassign_reason: cycleType === "rebuild" ? "demo_rebuild" : "demo_trial",
      reassigned_at: null,
      verified_store_id: null,
      verified_store_name: null,
      verified_at: null,
      is_self_store_verified: false,
    };
    for (const round of detail.rounds) {
      round.current_assignment_round_id = assignmentRoundId;
      round.current_round_no = roundNumber;
      round.current_round_status = "active_unfollowed";
      round.current_assigned_store_id = nextStore.store_id;
      round.current_assigned_store_name = nextStore.store_name;
    }
    detail.lead_status = "active";
    detail.rounds.push(nextRound);
    this.state.rounds.push(nextRound);
    this.state.decisions.push({
      decision_id: this.nextId("DEMO-DECISION-"),
      lead_key: leadKey,
      order_id: orderId,
      rule_id: matchingRule?.rule.rule_id ?? null,
      rule_version_id: publishedVersion?.rule_version_id ?? null,
      scope_type: matchingRule?.rule.scope.scope_type ?? null,
      scope_key: nextStore.city_code,
      strategy_type: previousRound ? "nearby_city_optimization" : "sales_store_priority",
      execution_order: roundNumber,
      allocation_cycle_id: cycleId,
      execution_mode: "trial",
      assignment_round_id: assignmentRoundId,
      round_no: roundNumber,
      selected_store_id: nextStore.store_id,
      selected_store_name: nextStore.store_name,
      decision_status: "assigned",
      reason: cycleType === "rebuild" ? "demo_rebuild" : "demo_trial",
      payload: { synthetic: true, supersedes_cycle_id: sourceCycleId },
      actor: "DEMO-USER-ADMIN",
      executed_at: executedAt,
    });
    return "assigned";
  }

  private appendAudit(
    eventType: string,
    allocationCycleId: string | null,
    beforeSnapshot: Record<string, unknown>,
    afterSnapshot: Record<string, unknown>,
    detail: Record<string, unknown>,
    privilegedConfirmation: boolean,
  ): void {
    this.state.auditLogs.push({
      audit_log_id: this.nextId("DEMO-AUDIT-"),
      event_type: eventType,
      allocation_cycle_id: allocationCycleId,
      actor: "DEMO-USER-ADMIN",
      privileged_confirmation: privilegedConfirmation,
      before_snapshot: structuredClone(beforeSnapshot),
      after_snapshot: structuredClone(afterSnapshot),
      detail: structuredClone(detail),
      created_at: new Date().toISOString(),
    });
  }

  private findRuleVersion(ruleVersionId: string): {
    bundle: ClueDemoState["rules"][number];
    version: ClueAllocationRuleVersion;
  } {
    for (const bundle of this.state.rules) {
      const version = bundle.versions.find(
        (candidate) => candidate.rule_version_id === ruleVersionId,
      );
      if (version) return { bundle, version };
    }
    throw new ClueDemoRepositoryError(404, "演示规则版本不存在");
  }

  private advanceAfterRoundFailure(
    orderId: string,
    round: ClueAssignmentRound,
    reason: string,
  ): void {
    const detail = this.state.orderDetails[orderId];
    const usedStoreIds = new Set(
      detail.rounds
        .map((candidate) => candidate.assigned_store_id)
        .filter((storeId): storeId is string => Boolean(storeId)),
    );
    const nextStore = this.state.stores.find(
      (store) =>
        store.city === detail.assigned_city && !usedStoreIds.has(store.store_id),
    );
    const createdAt = new Date().toISOString();

    if (!nextStore) {
      detail.lead_status = "headquarters";
      for (const candidate of detail.rounds) {
        candidate.current_assignment_round_id = null;
        candidate.current_assigned_store_id = null;
        candidate.current_assigned_store_name = null;
        candidate.current_round_status = "headquarters";
        candidate.is_current_round = false;
        candidate.can_operate_current_round = false;
      }
      this.state.headquartersPool.push({
        headquarters_pool_entry_id: this.nextId("DEMO-HQ-"),
        lead_key: orderId.replace("DEMO-ORDER-", "DEMO-LEAD-"),
        canonical_clue_id: detail.canonical_clue_id,
        order_id: orderId,
        order_status: round.order_current_status,
        raw_order_status: "DEMO_FULFILLING",
        status: "active",
        reason: "all_strategies_exhausted",
        entered_at: createdAt,
        closed_at: null,
        close_reason: null,
        anchor_store_id: round.assigned_store_id,
        anchor_city: detail.assigned_city,
        anchor_city_code:
          this.state.stores.find(
            (store) => store.store_id === round.assigned_store_id,
          )?.city_code ?? null,
        source_assignment_round_id: round.assignment_round_id,
        source_decision_id: null,
        source_rule_version_id: null,
        allocation_cycle_id: null,
      });
      return;
    }

    const roundNumber = Math.max(...detail.rounds.map((item) => item.round_no)) + 1;
    const assignmentRoundId = `DEMO-ROUND-${orderId.replace("DEMO-ORDER-", "")}-${String(roundNumber).padStart(2, "0")}`;
    const nextRound: ClueAssignmentRound = {
      assignment_round_id: assignmentRoundId,
      order_id: orderId,
      round_no: roundNumber,
      store_display_status: "待跟进",
      lead_status: "active",
      order_current_status: round.order_current_status,
      current_assignment_round_id: assignmentRoundId,
      current_round_no: roundNumber,
      current_round_status: "active_unfollowed",
      current_assigned_store_id: nextStore.store_id,
      current_assigned_store_name: nextStore.store_name,
      is_current_round: true,
      round_effective_status: "active",
      can_operate_current_round: true,
      timing_state: "active",
      status_reason: "新一轮首次跟进时限内",
      round_status: "active_unfollowed",
      assigned_at: createdAt,
      expires_at: new Date(
        new Date(createdAt).getTime() + 24 * 60 * 60 * 1000,
      ).toISOString(),
      remaining_reassign_seconds: 24 * 60 * 60,
      assigned_store_id: nextStore.store_id,
      assigned_store_name: nextStore.store_name,
      phone_masked: detail.phone_masked,
      product_name: detail.product_name,
      product_type: detail.product_type,
      author_nickname: detail.author_nickname,
      followed_at: null,
      follow_result: "pending",
      reassign_reason: reason,
      reassigned_at: null,
      verified_store_id: null,
      verified_store_name: null,
      verified_at: null,
      is_self_store_verified: false,
    };

    for (const candidate of detail.rounds) {
      candidate.current_assignment_round_id = assignmentRoundId;
      candidate.current_round_no = roundNumber;
      candidate.current_round_status = "active_unfollowed";
      candidate.current_assigned_store_id = nextStore.store_id;
      candidate.current_assigned_store_name = nextStore.store_name;
      candidate.is_current_round = false;
      candidate.can_operate_current_round = false;
    }
    detail.lead_status = "active";
    detail.rounds.push(nextRound);
    this.state.rounds.push(nextRound);
    this.state.eligibleLeads = this.state.eligibleLeads.filter(
      (lead) => lead.order_id !== orderId,
    );
    this.state.decisions.push({
      decision_id: this.nextId("DEMO-DECISION-"),
      lead_key: orderId.replace("DEMO-ORDER-", "DEMO-LEAD-"),
      order_id: orderId,
      rule_id: this.state.rules[0]?.rule.rule_id ?? null,
      rule_version_id:
        this.state.rules[0]?.versions.find((version) => version.status === "published")
          ?.rule_version_id ?? null,
      scope_type: "city",
      scope_key: nextStore.city_code,
      strategy_type: "city_fallback",
      execution_order: roundNumber,
      allocation_cycle_id: null,
      execution_mode: "demo",
      assignment_round_id: assignmentRoundId,
      round_no: roundNumber,
      selected_store_id: nextStore.store_id,
      selected_store_name: nextStore.store_name,
      decision_status: "assigned",
      reason,
      payload: { synthetic: true, transition_from: round.assignment_round_id },
      actor: "DEMO-USER-ADMIN",
      executed_at: createdAt,
    });
  }

  private escapeCsv(value: string): string {
    return /[",\r\n]/.test(value)
      ? `"${value.replace(/"/g, '""')}"`
      : value;
  }

  private nextId(prefix: string): string {
    this.state.sequence += 1;
    return `${prefix}${String(this.state.sequence).padStart(6, "0")}`;
  }

  private filterRounds(filters: ClueOverviewFilters): ClueAssignmentRound[] {
    const storeById = new Map(
      this.state.stores.map((store) => [store.store_id, store]),
    );
    return this.state.rounds.filter((round) => {
      const store = round.assigned_store_id
        ? storeById.get(round.assigned_store_id)
        : undefined;
      const assignedDate = round.assigned_at?.slice(0, 10) ?? "";
      if (
        filters.assigned_store_id &&
        round.assigned_store_id !== filters.assigned_store_id
      ) {
        return false;
      }
      if (
        filters.assigned_date_start &&
        assignedDate < filters.assigned_date_start
      ) {
        return false;
      }
      if (
        filters.assigned_date_end &&
        assignedDate > filters.assigned_date_end
      ) {
        return false;
      }
      if (filters.lead_status && round.lead_status !== filters.lead_status) {
        return false;
      }
      if (
        filters.store_display_status &&
        round.store_display_status !== filters.store_display_status
      ) {
        return false;
      }
      if (
        filters.round_status &&
        round.round_status !== filters.round_status
      ) {
        return false;
      }
      if (
        filters.product_type &&
        filters.product_type !== "all" &&
        round.product_type !== filters.product_type
      ) {
        return false;
      }
      if (filters.province && store?.province !== filters.province) {
        return false;
      }
      if (filters.city && store?.city !== filters.city) {
        return false;
      }
      return true;
    });
  }
}

export const clueDemoRepository = new ClueDemoRepository();
