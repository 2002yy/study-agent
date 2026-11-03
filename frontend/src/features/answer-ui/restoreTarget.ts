/**
 * One-shot record of the older version the learner chose to continue from.
 *
 * The composer sends the whole message on the next submit, so the choice has to
 * survive between the click and that submit. It is consumed by the request
 * builder, exactly like the per-turn task-intent override, and never persisted
 * as conversation text.
 */
export type RestoreTarget = { id: string; revision: number; title: string };

let pending: RestoreTarget | null = null;

export function setPendingRestoreTarget(target: RestoreTarget | null): void {
  pending = target;
}

export function peekPendingRestoreTarget(): RestoreTarget | null {
  return pending;
}

export function clearPendingRestoreTarget(): void {
  pending = null;
}

export function consumePendingRestoreTarget(): RestoreTarget | null {
  const value = pending;
  pending = null;
  return value;
}
