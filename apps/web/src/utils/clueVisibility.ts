/** Shanghai-local lower bound for user-facing formal clue assignment data. */
export const CLUE_VISIBLE_ASSIGNED_AT = "2026-09-01T00:00:00+08:00";

const CLUE_VISIBLE_ASSIGNED_AT_MS = Date.parse(CLUE_VISIBLE_ASSIGNED_AT);
const SHANGHAI_OFFSET_MS = 8 * 60 * 60 * 1000;

export function isClueAssignedAtVisible(
  assignedAt: string | null | undefined,
): boolean {
  const timestamp = Date.parse(assignedAt ?? "");
  return Number.isFinite(timestamp) && timestamp >= CLUE_VISIBLE_ASSIGNED_AT_MS;
}

export function clueAssignedDateInShanghai(
  assignedAt: string | null | undefined,
): string {
  const timestamp = Date.parse(assignedAt ?? "");
  if (!Number.isFinite(timestamp)) return "";
  return new Date(timestamp + SHANGHAI_OFFSET_MS).toISOString().slice(0, 10);
}
