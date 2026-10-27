import type { ClueOverviewFilters } from "./dashboard";

export interface ClueListFilters extends ClueOverviewFilters {
  assigned_store_ids?: string[] | null;
  phone?: string | null;
}

export interface ClueSelectedStore {
  store_id: string;
  store_name: string;
  matches?: { identifier: string; sources: ("account" | "poi")[] }[];
}

export interface ClueStoreResolution {
  stores: ClueSelectedStore[];
  input_count: number;
  unique_count: number;
  duplicate_count: number;
  matched_identifier_count: number;
  matched_store_count: number;
  unmatched_identifiers: string[];
}
