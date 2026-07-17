import type {
  ClueAllocationAuditLog,
  ClueAllocationCycle,
  ClueAllocationDecision,
  ClueAllocationEligibleLead,
  ClueAllocationRule,
  ClueAllocationRuleVersion,
  ClueAssignmentRound,
  ClueFollowUpRecord,
  ClueHeadquartersPoolEntry,
  ClueOrderDetail,
  StoreScoreSnapshot,
} from "../types/dashboard";

export interface ClueDemoStore {
  store_id: string;
  store_name: string;
  province: string;
  city: string;
  city_code: string;
  latitude: number;
  longitude: number;
}

export interface ClueDemoRuleBundle {
  rule: ClueAllocationRule;
  versions: ClueAllocationRuleVersion[];
}

export interface ClueDemoPreviewToken {
  token: string;
  operation: "trial" | "rebuild";
  leadKeys: string[];
  sourceCycleId: string | null;
  expiresAt: string;
}

export interface ClueDemoState {
  generatedAt: string;
  stores: ClueDemoStore[];
  rounds: ClueAssignmentRound[];
  orderDetails: Record<string, ClueOrderDetail>;
  followUpRecords: ClueFollowUpRecord[];
  eligibleLeads: ClueAllocationEligibleLead[];
  headquartersPool: ClueHeadquartersPoolEntry[];
  cycles: ClueAllocationCycle[];
  auditLogs: ClueAllocationAuditLog[];
  rules: ClueDemoRuleBundle[];
  decisions: ClueAllocationDecision[];
  storeScores: StoreScoreSnapshot[];
  previewTokens: Map<string, ClueDemoPreviewToken>;
  sequence: number;
}
