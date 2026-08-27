const YUAN_AMOUNT_PATTERN = /^(-?)(\d+)(?:\.(\d{1,2}))?$/;
const MAX_SAFE_CENT = BigInt(Number.MAX_SAFE_INTEGER);
const MIN_SAFE_CENT = BigInt(Number.MIN_SAFE_INTEGER);

export function parseYuanToCent(value: string): number | null {
  const match = YUAN_AMOUNT_PATTERN.exec(value);
  if (!match) return null;

  const [, sign, yuan, fraction = ""] = match;
  const absoluteCent = BigInt(yuan) * 100n + BigInt(fraction.padEnd(2, "0"));
  const signedCent = sign === "-" ? -absoluteCent : absoluteCent;
  if (
    signedCent === 0n ||
    signedCent > MAX_SAFE_CENT ||
    signedCent < MIN_SAFE_CENT
  ) {
    return null;
  }
  return Number(signedCent);
}
