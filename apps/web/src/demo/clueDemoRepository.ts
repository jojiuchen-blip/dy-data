import type {
  ApiResponse,
  ClueAssignmentRound,
  ClueAssignmentRoundData,
  ClueFilterMetadata,
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
