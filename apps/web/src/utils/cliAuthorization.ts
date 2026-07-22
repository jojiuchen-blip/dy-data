export function normalizeCliAuthorizationCode(userCode: string): string {
  return userCode.replace(/\s+/g, "").toUpperCase();
}

export function readCliAuthorizationCode(search: string): string {
  return normalizeCliAuthorizationCode(
    new URLSearchParams(search).get("user_code") ?? "",
  );
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
  const requestUserCode = normalizeCliAuthorizationCode(request.userCode);
  const currentUserCode = normalizeCliAuthorizationCode(current.userCode);
  const normalizedResponseUserCode =
    responseUserCode === undefined
      ? undefined
      : normalizeCliAuthorizationCode(responseUserCode);

  return (
    request.generation === current.generation &&
    requestUserCode === currentUserCode &&
    (normalizedResponseUserCode === undefined ||
      normalizedResponseUserCode === requestUserCode)
  );
}
