/** Component-local only: never persist financial request bodies or identities. */
export function createPendingRequestKey(newKey: () => string = () => crypto.randomUUID()) {
  let pending: { identity: string; key: string } | undefined;
  return {
    forRequest(target: string, payload: unknown): string {
      const identity = JSON.stringify([target, payload]);
      if (!pending || pending.identity !== identity) {
        pending = { identity, key: newKey() };
      }
      return pending.key;
    },
    clear() { pending = undefined; },
  };
}
