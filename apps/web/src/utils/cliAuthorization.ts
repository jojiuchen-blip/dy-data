export function readCliAuthorizationCode(search: string): string {
  return new URLSearchParams(search).get("user_code")?.trim() ?? "";
}

export interface CliAuthorizationRequest {
  generation: number;
  userCode: string;
}

export function isCurrentCliAuthorizationRequest(
  request: CliAuthorizationRequest,
  current: CliAuthorizationRequest,
  responseUserCode?: string,
): boolean {
  return (
    request.generation === current.generation &&
    request.userCode === current.userCode &&
    (responseUserCode === undefined || responseUserCode === request.userCode)
  );
}
