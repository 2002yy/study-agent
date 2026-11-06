export type RepairTarget = { id: string; revision: number };
let lastAttempt: { target: RepairTarget; sessionId: string; input: string } | null = null;
let pending: { target: RepairTarget; sessionId: string } | null = null;

export function setPendingRepairTarget(target: RepairTarget | null, sessionId?: string): void {
  pending = target && sessionId ? { target, sessionId } : null;
}

export function consumePendingRepairTarget(input: string, sessionId?: string): RepairTarget | null {
  const value = pending;
  pending = null;
  if (value && value.sessionId === sessionId) {
    lastAttempt = { ...value, input };
    return value.target;
  }
  // A transport failure may precede creation of a server-side parent turn.
  // Re-sending the same draft must retain its original budget identity.
  if (lastAttempt && lastAttempt.sessionId === sessionId && lastAttempt.input === input) {
    return lastAttempt.target;
  }
  lastAttempt = null;
  return null;
}


export function clearRepairTarget(): void {
  pending = null;
  lastAttempt = null;
}
