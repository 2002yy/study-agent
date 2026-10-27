import { useSyncExternalStore } from "react";
import { isAuthRequired, subscribeAuthRequired } from "../apiAuthState";

/** True while the server has refused a request for a missing token. */
export function useAuthRequired(): boolean {
  return useSyncExternalStore(subscribeAuthRequired, isAuthRequired, () => false);
}
