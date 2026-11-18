/** datetime-local has no timezone. Store appointments use the Beijing wall clock. */
export function toShanghaiAppointmentAt(value: string): string | null {
  if (!/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}$/.test(value)) return null;
  const wallClock = new Date(`${value}:00Z`);
  if (!Number.isFinite(wallClock.getTime()) || wallClock.toISOString().slice(0, 16) !== value) return null;
  return `${value}:00+08:00`;
}

export function toShanghaiAppointmentInput(value: string | null | undefined): string {
  if (!value) return "";
  const date = new Date(value);
  if (!Number.isFinite(date.getTime())) return "";
  const parts = new Intl.DateTimeFormat("zh-CN", {
    timeZone: "Asia/Shanghai", year: "numeric", month: "2-digit", day: "2-digit",
    hour: "2-digit", minute: "2-digit", hourCycle: "h23",
  }).formatToParts(date);
  const values = new Map(parts.map((part) => [part.type, part.value]));
  return `${values.get("year")}-${values.get("month")}-${values.get("day")}T${values.get("hour")}:${values.get("minute")}`;
}
