import type {
  ClueAllocationAuditLog,
  ClueAllocationCycle,
  ClueAllocationDecision,
  ClueAllocationEligibleLead,
  ClueAllocationRuleVersion,
  ClueAssignmentRound,
  ClueFollowUpRecord,
  ClueFollowUpResult,
  ClueHeadquartersPoolEntry,
  ClueOrderDetail,
} from "../types/dashboard";
import {
  CLUE_DEMO_PROFILE,
  DEMO_AUTHOR_LABELS,
  DEMO_FOLLOW_UP_NOTES,
  DEMO_PRODUCTS,
  DEMO_REGIONS,
  DEMO_STORE_LABELS,
} from "./clueDemoProfile";
import type {
  ClueDemoRuleBundle,
  ClueDemoState,
  ClueDemoStore,
} from "./clueDemoTypes";

interface CreateClueDemoStateOptions {
  seed?: number;
  now?: Date;
}

interface FinalRoundOutcome {
  leadStatus: string;
  orderStatus: string;
  roundStatus: string;
  displayStatus: string;
  hasCurrentRound: boolean;
  canOperate: boolean;
  timingState: string | null;
  statusReason: string | null;
  followResult: string;
}

const HISTORICAL_REASONS = [
  "follow_lost",
  "request_store_change",
  "timeout",
  "protection_expired",
] as const;

function createSeededRandom(seed: number): () => number {
  let value = seed >>> 0;
  return () => {
    value += 0x6d2b79f5;
    let next = value;
    next = Math.imul(next ^ (next >>> 15), next | 1);
    next ^= next + Math.imul(next ^ (next >>> 7), next | 61);
    return ((next ^ (next >>> 14)) >>> 0) / 4294967296;
  };
}

function pad(value: number, width = 4): string {
  return String(value).padStart(width, "0");
}

function shiftedIso(base: Date, days: number, minutes = 0): string {
  return new Date(
    base.getTime() + days * 24 * 60 * 60 * 1000 + minutes * 60 * 1000,
  ).toISOString();
}

function addHours(value: string, hours: number): string {
  return new Date(new Date(value).getTime() + hours * 60 * 60 * 1000).toISOString();
}

function createStores(): ClueDemoStore[] {
  return DEMO_REGIONS.flatMap((region, regionIndex) =>
    DEMO_STORE_LABELS.map((label, storeIndex) => {
      const sequence = regionIndex * DEMO_STORE_LABELS.length + storeIndex + 1;
      return {
        store_id: `DEMO-STORE-${pad(sequence, 3)}`,
        store_name: `${region.city}${label}演示门店`,
        province: region.province,
        city: region.city,
        city_code: region.cityCode,
        latitude: region.latitude + storeIndex * 0.012,
        longitude: region.longitude + storeIndex * 0.014,
      };
    }),
  );
}

function pickRegion(random: () => number): (typeof DEMO_REGIONS)[number] {
  const totalWeight = DEMO_REGIONS.reduce((sum, region) => sum + region.weight, 0);
  let point = random() * totalWeight;
  for (const region of DEMO_REGIONS) {
    point -= region.weight;
    if (point <= 0) return region;
  }
  return DEMO_REGIONS[0];
}

function roundCountForAllocatedLead(index: number): 1 | 2 | 3 {
  if (index < 230) return 1;
  if (index < 320) return 2;
  return 3;
}

function followUpCountForRound(roundIndex: number): number {
  if (roundIndex % 11 === 0) return 0;
  return Math.min(
    4,
    1 + (roundIndex % 3 === 0 ? 1 : 0) + (roundIndex % 7 === 0 ? 1 : 0),
  );
}

function finalRoundOutcome(index: number): FinalRoundOutcome {
  switch (index % 8) {
    case 0:
      return {
        leadStatus: "active",
        orderStatus: "fulfilling",
        roundStatus: "active_unfollowed",
        displayStatus: "待跟进",
        hasCurrentRound: true,
        canOperate: true,
        timingState: "active",
        statusReason: "allocated_to_store",
        followResult: "pending",
      };
    case 1:
      return {
        leadStatus: "active",
        orderStatus: "fulfilling",
        roundStatus: "active_followed",
        displayStatus: "已跟进",
        hasCurrentRound: true,
        canOperate: true,
        timingState: "protected",
        statusReason: "核销保护期内",
        followResult: "further_follow_up",
      };
    case 2:
      return {
        leadStatus: "converted",
        orderStatus: "verified",
        roundStatus: "active_followed",
        displayStatus: "已核销",
        hasCurrentRound: true,
        canOperate: false,
        timingState: "converted",
        statusReason: "order_verified",
        followResult: "success",
      };
    case 3:
      return {
        leadStatus: "refunded",
        orderStatus: "refunded",
        roundStatus: "active_followed",
        displayStatus: "已退款",
        hasCurrentRound: true,
        canOperate: false,
        timingState: "closed",
        statusReason: "order_refunded",
        followResult: "success",
      };
    case 4:
      return {
        leadStatus: "pending_reassign",
        orderStatus: "fulfilling",
        roundStatus: "expired_pending_reassign",
        displayStatus: "超期失效",
        hasCurrentRound: false,
        canOperate: false,
        timingState: "expired",
        statusReason: "sla_expired",
        followResult: "unreachable",
      };
    case 5:
      return {
        leadStatus: "pending_reassign",
        orderStatus: "fulfilling",
        roundStatus: "failed_pending_reassign",
        displayStatus: "主动战败",
        hasCurrentRound: false,
        canOperate: false,
        timingState: "inactive",
        statusReason: "follow_lost",
        followResult: "lost",
      };
    case 6:
      return {
        leadStatus: "headquarters",
        orderStatus: "fulfilling",
        roundStatus: "failed_pending_reassign",
        displayStatus: "不可跟进",
        hasCurrentRound: false,
        canOperate: false,
        timingState: "inactive",
        statusReason: "strategies_exhausted",
        followResult: "request_store_change",
      };
    default:
      return {
        leadStatus: "active",
        orderStatus: "fulfilling",
        roundStatus: "active_followed",
        displayStatus: "已跟进",
        hasCurrentRound: true,
        canOperate: true,
        timingState: "protected",
        statusReason: "核销保护期内",
        followResult: "appointment",
      };
  }
}

function createRuleBundles(now: Date): ClueDemoRuleBundle[] {
  const createdAt = shiftedIso(now, -180);
  const updatedAt = shiftedIso(now, -10);
  const definitions = [
    { id: "001", name: "全国演示线索分配规则", scopeType: "global" as const, cityCode: null },
    { id: "002", name: "深圳演示线索分配规则", scopeType: "city" as const, cityCode: "440300" },
    { id: "003", name: "广州演示线索分配规则", scopeType: "city" as const, cityCode: "440100" },
  ];

  return definitions.map((definition) => {
    const ruleId = `DEMO-RULE-${definition.id}`;
    const baseVersion = (version: number, status: ClueAllocationRuleVersion["status"]): ClueAllocationRuleVersion => ({
      rule_version_id: `DEMO-RULE-VERSION-${definition.id}-${pad(version, 2)}`,
      rule_id: ruleId,
      version_no: version,
      status,
      auto_expiry_enabled: true,
      first_follow_up_sla_hours: 24,
      protection_days: 7,
      conversion_weight: 0.65,
      follow_24h_weight: 0.35,
      lookback_days: 30,
      min_samples: 10,
      strategy_configs: [
        {
          strategy_type: "sales_store_priority",
          enabled: true,
          execution_order: 1,
          params: { description: "优先归属演示门店" },
        },
        {
          strategy_type: "nearby_city_optimization",
          enabled: true,
          execution_order: 2,
          params: { description: "同城门店综合评分" },
        },
        {
          strategy_type: "city_fallback",
          enabled: true,
          execution_order: 3,
          params: { description: "同城兜底分配" },
        },
      ],
      created_at: version === 1 ? createdAt : shiftedIso(now, -30),
      updated_at: version === 1 ? shiftedIso(now, -31) : updatedAt,
      published_at: status === "published" ? shiftedIso(now, -29) : shiftedIso(now, -170),
      retired_at: status === "retired" ? shiftedIso(now, -30) : null,
    });

    return {
      rule: {
        rule_id: ruleId,
        name: definition.name,
        scope: {
          scope_type: definition.scopeType,
          city_code: definition.cityCode,
          store_group_id: null,
          anchor_store_id: null,
        },
        created_at: createdAt,
        updated_at: updatedAt,
      },
      versions: [baseVersion(1, "retired"), baseVersion(2, "published")],
    };
  });
}

function createHistoricalCycles(now: Date): ClueAllocationCycle[] {
  return Array.from({ length: 8 }, (_, index) => {
    const cycleId = `DEMO-CYCLE-HISTORY-${pad(index + 1, 3)}`;
    const selectedLeadKeys = Array.from(
      { length: 12 + (index % 4) },
      (_, offset) => `DEMO-LEAD-${pad(index * 15 + offset + 1)}`,
    );
    return {
      allocation_cycle_id: cycleId,
      cycle_type: index % 3 === 0 ? "rebuild" : "trial",
      execution_mode: "trial",
      status: "completed",
      parent_cycle_id: index % 3 === 0 && index > 0 ? `DEMO-CYCLE-HISTORY-${pad(index, 3)}` : null,
      selected_lead_keys: selectedLeadKeys,
      requested_lead_count: selectedLeadKeys.length,
      active_lead_count: selectedLeadKeys.length,
      planned_impact: { assigned: selectedLeadKeys.length, headquarters: 0, skipped: 0 },
      actual_impact: { assigned: selectedLeadKeys.length - 1, headquarters: 1, skipped: 0 },
      actor: "DEMO-USER-ADMIN",
      privileged_confirmation: index % 3 === 0,
      created_at: shiftedIso(now, -(80 - index * 8)),
      executed_at: shiftedIso(now, -(80 - index * 8), 5),
      completed_at: shiftedIso(now, -(80 - index * 8), 9),
    };
  });
}

function createHistoricalAudits(
  now: Date,
  cycles: ClueAllocationCycle[],
): ClueAllocationAuditLog[] {
  return Array.from({ length: 24 }, (_, index) => ({
    audit_log_id: `DEMO-AUDIT-HISTORY-${pad(index + 1, 4)}`,
    event_type: index % 3 === 0 ? "cycle_previewed" : index % 3 === 1 ? "cycle_executed" : "rule_published",
    allocation_cycle_id: cycles[index % cycles.length].allocation_cycle_id,
    actor: "DEMO-USER-ADMIN",
    privileged_confirmation: index % 6 === 0,
    before_snapshot: { stage: "before", sequence: index },
    after_snapshot: { stage: "after", sequence: index + 1 },
    detail: { source: "synthetic_demo", note: "合成审计记录" },
    created_at: shiftedIso(now, -(75 - index * 2), index * 3),
  }));
}

function makeFollowUpRecord(
  sequence: number,
  round: ClueAssignmentRound,
  result: ClueFollowUpResult,
  createdAt: string,
  noteIndex: number,
): ClueFollowUpRecord {
  return {
    follow_up_record_id: `DEMO-FOLLOW-UP-${pad(sequence, 6)}`,
    order_id: round.order_id,
    assignment_round_id: round.assignment_round_id,
    round_no: round.round_no,
    assigned_store_id: round.assigned_store_id,
    assigned_store_name: round.assigned_store_name,
    follow_result: result,
    note: DEMO_FOLLOW_UP_NOTES[noteIndex % DEMO_FOLLOW_UP_NOTES.length],
    timing_state: result === "appointment" ? "protected" : "active",
    status_reason: result === "appointment" ? "核销保护期内" : null,
    is_deleted: false,
    deleted_at: null,
    deleted_by_user_id: null,
    deleted_by_username: null,
    deletion_reason: null,
    operator_user_id: `DEMO-STORE-USER-${pad((noteIndex % 48) + 1, 3)}`,
    operator_username: `演示门店账号${pad((noteIndex % 48) + 1, 2)}`,
    created_at: createdAt,
  };
}

function resultForGeneratedRecord(
  outcome: FinalRoundOutcome,
  historicalReason: string | null,
  recordIndex: number,
  recordCount: number,
): ClueFollowUpResult {
  if (recordIndex === recordCount - 1 && historicalReason === "follow_lost") return "lost";
  if (recordIndex === recordCount - 1 && historicalReason === "request_store_change") {
    return "request_store_change";
  }
  if (recordIndex === recordCount - 1 && outcome.followResult !== "pending") {
    return outcome.followResult as ClueFollowUpResult;
  }
  return (["unreachable", "further_follow_up", "appointment"] as const)[recordIndex % 3];
}

export function createClueDemoState(
  options: CreateClueDemoStateOptions = {},
): ClueDemoState {
  const now = options.now ? new Date(options.now) : new Date();
  const random = createSeededRandom(options.seed ?? CLUE_DEMO_PROFILE.seed);
  const stores = createStores();
  const rounds: ClueAssignmentRound[] = [];
  const orderDetails: Record<string, ClueOrderDetail> = {};
  const followUpRecords: ClueFollowUpRecord[] = [];
  const eligibleLeads: ClueAllocationEligibleLead[] = [];
  const headquartersPool: ClueHeadquartersPoolEntry[] = [];
  const cycles = createHistoricalCycles(now);
  const auditLogs = createHistoricalAudits(now, cycles);
  const rules = createRuleBundles(now);
  const decisions: ClueAllocationDecision[] = [];
  let sequence = 10000;

  for (let leadIndex = 0; leadIndex < CLUE_DEMO_PROFILE.leadCount; leadIndex += 1) {
    const leadNumber = leadIndex + 1;
    const orderId = `DEMO-ORDER-${pad(leadNumber)}`;
    const canonicalClueId = `DEMO-CLUE-${pad(leadNumber)}`;
    const leadKey = `DEMO-LEAD-${pad(leadNumber)}`;
    const region = pickRegion(random);
    const cityStores = stores.filter((store) => store.city_code === region.cityCode);
    const product = DEMO_PRODUCTS[(leadIndex + Math.floor(random() * DEMO_PRODUCTS.length)) % DEMO_PRODUCTS.length];
    const phoneMasked = `19${leadIndex % 10}****${pad((leadIndex * 37) % 10000)}`;
    const authorNickname = `演示${DEMO_AUTHOR_LABELS[leadIndex % DEMO_AUTHOR_LABELS.length]}${pad(leadNumber, 3)}`;
    const detailRounds: ClueAssignmentRound[] = [];
    const detailFollowUps: ClueFollowUpRecord[] = [];
    let detailLeadStatus = "terminal";

    if (leadIndex < 360) {
      const roundCount = roundCountForAllocatedLead(leadIndex);
      const outcome = finalRoundOutcome(leadIndex);
      const finalRoundId = `DEMO-ROUND-${pad(leadNumber)}-${pad(roundCount, 2)}`;
      const storeOffset = leadIndex % cityStores.length;
      const finalStore = cityStores[(storeOffset + roundCount - 1) % cityStores.length];
      const currentRoundId = outcome.hasCurrentRound ? finalRoundId : null;
      detailLeadStatus = outcome.leadStatus;

      for (let roundNumber = 1; roundNumber <= roundCount; roundNumber += 1) {
        const isFinalRound = roundNumber === roundCount;
        const historicalReason = isFinalRound
          ? null
          : HISTORICAL_REASONS[(leadIndex + roundNumber) % HISTORICAL_REASONS.length];
        const assignedStore = cityStores[(storeOffset + roundNumber - 1) % cityStores.length];
        const assignedAt = shiftedIso(
          now,
          -(8 + ((leadIndex * 7) % 145) - (roundNumber - 1)),
          (leadIndex * 13 + roundNumber * 17) % 720,
        );
        const verified = isFinalRound && (outcome.leadStatus === "converted" || outcome.leadStatus === "refunded");
        const verifiedStore = verified
          ? cityStores[(storeOffset + (leadIndex % 5 === 0 ? roundNumber : roundNumber - 1)) % cityStores.length]
          : null;
        const roundStatus = isFinalRound
          ? outcome.roundStatus
          : historicalReason === "timeout" || historicalReason === "protection_expired"
            ? "expired_pending_reassign"
            : "failed_pending_reassign";
        const isCurrentRound = isFinalRound && outcome.hasCurrentRound;
        const round: ClueAssignmentRound = {
          assignment_round_id: `DEMO-ROUND-${pad(leadNumber)}-${pad(roundNumber, 2)}`,
          order_id: orderId,
          round_no: roundNumber,
          store_display_status: isFinalRound
            ? outcome.displayStatus
            : roundStatus === "expired_pending_reassign" ? "超期失效" : "主动战败",
          lead_status: isFinalRound ? outcome.leadStatus : "pending_reassign",
          order_current_status: outcome.orderStatus,
          current_assignment_round_id: currentRoundId,
          current_round_no: roundCount,
          current_round_status: outcome.roundStatus,
          current_assigned_store_id: outcome.hasCurrentRound ? finalStore.store_id : null,
          current_assigned_store_name: outcome.hasCurrentRound ? finalStore.store_name : null,
          is_current_round: isCurrentRound,
          round_effective_status: isCurrentRound && outcome.canOperate ? "active" : "inactive",
          can_operate_current_round: isCurrentRound && outcome.canOperate,
          timing_state: isFinalRound ? outcome.timingState : "inactive",
          status_reason: isFinalRound
            ? outcome.statusReason
            : historicalReason ?? "reassigned",
          round_status: roundStatus,
          assigned_at: assignedAt,
          expires_at: isCurrentRound && outcome.canOperate
            ? addHours(assignedAt, outcome.timingState === "protected" ? 168 : 24)
            : addHours(assignedAt, 24),
          remaining_reassign_seconds: isCurrentRound && outcome.canOperate
            ? outcome.timingState === "protected" ? 604800 : 64800
            : 0,
          assigned_store_id: assignedStore.store_id,
          assigned_store_name: assignedStore.store_name,
          phone_masked: phoneMasked,
          product_name: product.name,
          product_type: product.type,
          author_nickname: authorNickname,
          followed_at: null,
          follow_result: isFinalRound ? outcome.followResult : "pending",
          reassign_reason: historicalReason ?? (isFinalRound && !outcome.hasCurrentRound
            ? outcome.roundStatus === "expired_pending_reassign" ? "timeout"
              : outcome.leadStatus === "headquarters" ? "all_strategies_exhausted" : "follow_lost"
            : null),
          reassigned_at: historicalReason ? addHours(assignedAt, 26) : null,
          verified_store_id: verifiedStore?.store_id ?? null,
          verified_store_name: verifiedStore?.store_name ?? null,
          verified_at: verified ? addHours(assignedAt, 36 + (leadIndex % 24)) : null,
          is_self_store_verified: Boolean(verifiedStore && verifiedStore.store_id === assignedStore.store_id),
        };

        const roundIndex = rounds.length;
        const generatedCount = isFinalRound && outcome.roundStatus === "active_unfollowed"
          ? 0
          : Math.max(historicalReason && historicalReason !== "timeout" ? 1 : 0, followUpCountForRound(roundIndex));
        for (let recordIndex = 0; recordIndex < generatedCount; recordIndex += 1) {
          sequence += 1;
          const result = resultForGeneratedRecord(
            outcome,
            historicalReason,
            recordIndex,
            generatedCount,
          );
          const record = makeFollowUpRecord(
            sequence,
            round,
            result,
            addHours(assignedAt, 1 + recordIndex * 0.75),
            leadIndex + roundNumber + recordIndex,
          );
          followUpRecords.push(record);
          detailFollowUps.push(record);
          round.followed_at = record.created_at;
          round.follow_result = record.follow_result;
        }

        rounds.push(round);
        detailRounds.push(round);
        const ruleBundle = rules.find((bundle) => bundle.rule.scope.city_code === region.cityCode) ?? rules[0];
        const ruleVersion = ruleBundle.versions.find((version) => version.status === "published") ?? ruleBundle.versions[0];
        decisions.push({
          decision_id: `DEMO-DECISION-${pad(rounds.length, 5)}`,
          lead_key: leadKey,
          order_id: orderId,
          rule_id: ruleBundle.rule.rule_id,
          rule_version_id: ruleVersion.rule_version_id,
          scope_type: ruleBundle.rule.scope.scope_type,
          scope_key: region.cityCode,
          strategy_type: roundNumber === 1 ? "sales_store_priority" : "nearby_city_optimization",
          execution_order: roundNumber,
          allocation_cycle_id: cycles[leadIndex % cycles.length].allocation_cycle_id,
          execution_mode: "demo",
          assignment_round_id: round.assignment_round_id,
          round_no: round.round_no,
          selected_store_id: assignedStore.store_id,
          selected_store_name: assignedStore.store_name,
          decision_status: "assigned",
          reason: historicalReason,
          payload: { city_code: region.cityCode, synthetic: true },
          actor: "DEMO-USER-ADMIN",
          executed_at: assignedAt,
        });
      }

      if (leadIndex % 8 === 4 || leadIndex % 8 === 5) {
        eligibleLeads.push({
          lead_key: leadKey,
          canonical_clue_id: canonicalClueId,
          order_id: orderId,
          allocation_state: "eligible_pending_reassign",
          pool_location: "allocation_pool",
          anchor_store_id: finalStore.store_id,
          anchor_city: region.city,
          anchor_city_code: region.cityCode,
          updated_at: detailRounds[detailRounds.length - 1].assigned_at ?? now.toISOString(),
        });
      }

      if (leadIndex % 8 === 6) {
        const finalRound = detailRounds[detailRounds.length - 1];
        headquartersPool.push({
          headquarters_pool_entry_id: `DEMO-HQ-EXHAUSTED-${pad(leadNumber)}`,
          lead_key: leadKey,
          canonical_clue_id: canonicalClueId,
          order_id: orderId,
          order_status: outcome.orderStatus,
          raw_order_status: "DEMO_FULFILLING",
          status: "active",
          reason: "all_strategies_exhausted",
          entered_at: addHours(finalRound.assigned_at ?? now.toISOString(), 30),
          closed_at: null,
          close_reason: null,
          anchor_store_id: finalStore.store_id,
          anchor_city: region.city,
          anchor_city_code: region.cityCode,
          source_assignment_round_id: finalRound.assignment_round_id,
          source_decision_id: decisions[decisions.length - 1].decision_id,
          source_rule_version_id: decisions[decisions.length - 1].rule_version_id,
          allocation_cycle_id: decisions[decisions.length - 1].allocation_cycle_id,
        });
      }
    } else if (leadIndex < 420) {
      detailLeadStatus = "headquarters";
      headquartersPool.push({
        headquarters_pool_entry_id: `DEMO-HQ-DIRECT-${pad(leadNumber)}`,
        lead_key: leadKey,
        canonical_clue_id: canonicalClueId,
        order_id: orderId,
        order_status: "fulfilling",
        raw_order_status: "DEMO_FULFILLING",
        status: leadIndex % 5 === 0 ? "closed" : "active",
        reason: "direct_headquarters",
        entered_at: shiftedIso(now, -(5 + (leadIndex % 90))),
        closed_at: leadIndex % 5 === 0 ? shiftedIso(now, -(2 + (leadIndex % 30))) : null,
        close_reason: leadIndex % 5 === 0 ? "demo_manual_close" : null,
        anchor_store_id: cityStores[leadIndex % cityStores.length].store_id,
        anchor_city: region.city,
        anchor_city_code: region.cityCode,
        source_assignment_round_id: null,
        source_decision_id: null,
        source_rule_version_id: null,
        allocation_cycle_id: cycles[leadIndex % cycles.length].allocation_cycle_id,
      });
    }

    orderDetails[orderId] = {
      order_id: orderId,
      canonical_clue_id: canonicalClueId,
      lead_status: detailLeadStatus,
      phone_masked: phoneMasked,
      product_id: product.productId,
      product_name: product.name,
      product_type: product.type,
      author_nickname: authorNickname,
      assigned_city: region.city,
      assigned_province: region.province,
      rounds: detailRounds,
      follow_up_records: detailFollowUps,
    };
  }

  const activeFollowedRounds = rounds.filter(
    (round) => round.is_current_round && round.can_operate_current_round && round.round_status === "active_followed",
  );
  let extraCursor = 0;
  while (followUpRecords.length < CLUE_DEMO_PROFILE.minimumFollowUpCount) {
    const round = activeFollowedRounds[extraCursor % activeFollowedRounds.length];
    sequence += 1;
    const record = makeFollowUpRecord(
      sequence,
      round,
      "further_follow_up",
      shiftedIso(now, -(extraCursor % 20), extraCursor * 7),
      extraCursor,
    );
    followUpRecords.push(record);
    orderDetails[round.order_id].follow_up_records.push(record);
    round.followed_at = record.created_at;
    round.follow_result = record.follow_result;
    extraCursor += 1;
  }

  while (followUpRecords.length > CLUE_DEMO_PROFILE.maximumFollowUpCount) {
    let removableIndex = -1;
    for (let index = followUpRecords.length - 1; index >= 0; index -= 1) {
      const result = followUpRecords[index].follow_result;
      if (result !== "lost" && result !== "request_store_change") {
        removableIndex = index;
        break;
      }
    }
    if (removableIndex < 0) break;
    const [removed] = followUpRecords.splice(removableIndex, 1);
    const detail = orderDetails[removed.order_id];
    detail.follow_up_records = detail.follow_up_records.filter(
      (record) => record.follow_up_record_id !== removed.follow_up_record_id,
    );
  }

  const storeScores = stores.map((store, index) => {
    const conversionDenominator = 18 + (index % 22);
    const conversionNumerator = 5 + (index % 13);
    const followDenominator = 20 + (index % 18);
    const followNumerator = 9 + (index % 12);
    const conversionRate = Math.min(1, conversionNumerator / conversionDenominator);
    const followRate = Math.min(1, followNumerator / followDenominator);
    const storeWeight = 0.82 + (index % 9) * 0.025;
    return {
      store_id: store.store_id,
      city_code: store.city_code,
      conversion_numerator: conversionNumerator,
      conversion_denominator: conversionDenominator,
      conversion_rate: conversionRate,
      conversion_value_source: "demo_observed",
      follow_24h_numerator: followNumerator,
      follow_24h_denominator: followDenominator,
      follow_24h_rate: followRate,
      follow_24h_value_source: "demo_observed",
      store_weight: storeWeight,
      composite_score: (conversionRate * 0.65 + followRate * 0.35) * storeWeight,
    };
  });

  const state: ClueDemoState = {
    generatedAt: now.toISOString(),
    stores,
    rounds,
    orderDetails,
    followUpRecords,
    eligibleLeads,
    headquartersPool,
    cycles,
    auditLogs,
    rules,
    decisions,
    storeScores,
    previewTokens: new Map(),
    sequence,
  };

  assertClueDemoState(state);
  return state;
}

function invariant(condition: unknown, message: string): asserts condition {
  if (!condition) throw new Error(`Clue demo invariant failed: ${message}`);
}

export function assertClueDemoState(state: ClueDemoState): void {
  const orderDetails = Object.values(state.orderDetails);
  const roundIds = new Set(state.rounds.map((round) => round.assignment_round_id));
  const storeIds = new Set(state.stores.map((store) => store.store_id));
  const orderIds = new Set(orderDetails.map((detail) => detail.order_id));
  const directHeadquartersCount = state.headquartersPool.filter(
    (entry) => entry.reason === "direct_headquarters" && !entry.source_assignment_round_id,
  ).length;
  const terminalWithoutRoundCount = orderDetails.filter(
    (detail) => detail.lead_status === "terminal" && detail.rounds.length === 0,
  ).length;

  invariant(orderDetails.length === CLUE_DEMO_PROFILE.leadCount, "lead count");
  invariant(state.stores.length === CLUE_DEMO_PROFILE.storeCount, "store count");
  invariant(new Set(state.stores.map((store) => store.city_code)).size === CLUE_DEMO_PROFILE.cityCount, "city count");
  invariant(state.rounds.length === 530, "assignment round count");
  invariant(
    orderDetails.filter((detail) => detail.rounds.length === 1).length === CLUE_DEMO_PROFILE.oneRoundLeadCount,
    "one-round lead count",
  );
  invariant(
    orderDetails.filter((detail) => detail.rounds.length === 2).length === CLUE_DEMO_PROFILE.twoRoundLeadCount,
    "two-round lead count",
  );
  invariant(
    orderDetails.filter((detail) => detail.rounds.length === 3).length === CLUE_DEMO_PROFILE.threeRoundLeadCount,
    "three-round lead count",
  );
  invariant(
    directHeadquartersCount === CLUE_DEMO_PROFILE.directHeadquartersLeadCount,
    "direct headquarters lead count",
  );
  invariant(
    terminalWithoutRoundCount === CLUE_DEMO_PROFILE.terminalWithoutRoundLeadCount,
    "terminal lead count",
  );
  invariant(
    state.followUpRecords.length >= CLUE_DEMO_PROFILE.minimumFollowUpCount &&
      state.followUpRecords.length <= CLUE_DEMO_PROFILE.maximumFollowUpCount,
    "follow-up count",
  );
  invariant(
    state.stores.every((store) =>
      store.store_id.startsWith("DEMO-") && store.store_name.includes("演示门店"),
    ),
    "synthetic stores",
  );
  invariant(
    state.followUpRecords.every(
      (record) => roundIds.has(record.assignment_round_id) &&
        orderIds.has(record.order_id) &&
        record.follow_up_record_id.startsWith("DEMO-") &&
        (!record.assigned_store_id || storeIds.has(record.assigned_store_id)),
    ),
    "follow-up references",
  );
  invariant(
    state.rounds.every((round) =>
      round.assignment_round_id.startsWith("DEMO-") &&
      round.order_id.startsWith("DEMO-") &&
      (!round.assigned_store_id || storeIds.has(round.assigned_store_id)),
    ),
    "identifier prefixes",
  );
  invariant(
    orderDetails.every((detail) =>
      detail.order_id.startsWith("DEMO-") &&
      (detail.canonical_clue_id?.startsWith("DEMO-") ?? true) &&
      detail.author_nickname?.startsWith("演示") &&
      detail.rounds.every((round, index) => round.round_no === index + 1),
    ),
    "order privacy and round sequence",
  );
  invariant(
    state.headquartersPool.every((entry) =>
      entry.headquarters_pool_entry_id.startsWith("DEMO-") && entry.lead_key.startsWith("DEMO-"),
    ) &&
      state.cycles.every((cycle) => cycle.allocation_cycle_id.startsWith("DEMO-")) &&
      state.auditLogs.every((log) => log.audit_log_id.startsWith("DEMO-")) &&
      state.rules.every((bundle) => bundle.rule.rule_id.startsWith("DEMO-")) &&
      state.decisions.every((decision) => decision.decision_id.startsWith("DEMO-")),
    "admin identifier prefixes",
  );
  invariant(Number.isInteger(state.sequence) && state.sequence > state.followUpRecords.length, "sequence");
}
