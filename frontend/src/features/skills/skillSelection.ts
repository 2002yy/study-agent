/** In-memory identity-only selection, consumed by the next single-chat request. */
let selected: string[] = [];
const listeners = new Set<() => void>();
export const getPendingSkillSelection = () => selected;
export function subscribeSkillSelection(listener: () => void) {
  listeners.add(listener);
  return () => { listeners.delete(listener); };
}
export function setPendingSkillSelection(ids: string[]) {
  const unique = [...new Set(ids)];
  if (unique.length > 3) throw new Error("下条消息最多使用三个 Skill。");
  selected = unique;
  listeners.forEach(listener => listener());
}
export function consumePendingSkillSelection(): string[] {
  const result = selected;
  setPendingSkillSelection([]);
  return result;
}
