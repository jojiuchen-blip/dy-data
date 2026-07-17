import type {
  ApiResponse,
  ClueAssignmentRound,
  ClueAssignmentRoundData,
  ClueFilterMetadata,
  ClueFollowUpPayload,
  ClueFollowUpRecord,
  ClueOrderDetail,
  ClueOverviewFilters,
  ClueOverviewMetrics,
  CluePhoneReveal,
  Pagination,
} from "../types/dashboard";
import { createClueDemoState } from "./clueDemoGenerator";
import type { ClueDemoState } from "./clueDemoTypes";

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
