/**
 * "The server wants a token" as observable client state.
 *
 * A2 makes the API refuse without a token. Every feature fetches on its own, so
 * without a shared flag the app just looks empty: the user has no way to learn
 * that a token is the reason. One module records the fact; the shell renders a
 * notice and the settings field clears it.
 */

type Listener = () => void;

const listeners = new Set<Listener>();
let authRequired = false;

function emit(): void {
  for (const listener of listeners) listener();
}

export function noteAuthRequired(status: number): void {
  if (status !== 401 || authRequired) return;
  authRequired = true;
  emit();
}

export function clearAuthRequired(): void {
  if (!authRequired) return;
  authRequired = false;
  emit();
}

export function isAuthRequired(): boolean {
  return authRequired;
}

export function subscribeAuthRequired(listener: Listener): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}
