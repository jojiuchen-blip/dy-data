export function readCliAuthorizationCode(search: string): string {
  return new URLSearchParams(search).get("user_code")?.trim() ?? "";
}
