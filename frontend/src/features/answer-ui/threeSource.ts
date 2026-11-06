/** Only host-selected capability pages load this trusted local runtime chunk. */
let pending: Promise<string> | undefined;
export function loadThreeSource(): Promise<string> {
  return pending ??= import("virtual:study-three-source").then(module => module.default)
    .catch(error => { pending = undefined; throw error; });
}
