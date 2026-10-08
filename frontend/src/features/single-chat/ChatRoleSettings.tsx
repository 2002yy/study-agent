import { RoleAvatar } from "../../components/RoleAvatar";
import { roleLabel, roleOptions } from "../roles/roleCatalog";

export function ChatRoleSettings({ id, selectedRole, disabled, onSelect, onClose }: {
  id: string;
  selectedRole: string;
  disabled: boolean;
  onSelect: (role: string) => void;
  onClose: () => void;
}) {
  return (
    <section className="chat-role-settings" id={id} aria-label="对话角色设置"
      onKeyDown={event => {
        if (event.key === "Escape") { event.preventDefault(); onClose(); }
      }}>
      <div className="chat-role-settings-heading">
        <span>{selectedRole === "auto" ? "自动选择角色" : `当前：${roleLabel(selectedRole)}`}</span>
        <button type="button" disabled={disabled} aria-pressed={selectedRole === "auto"}
          onClick={() => onSelect("auto")}>自动</button>
      </div>
      <div className="chat-role-options" role="group" aria-label="选择对话角色">
        {roleOptions.filter(([role]) => role !== "auto").map(([role, label]) => (
          <button key={role} type="button" disabled={disabled} aria-pressed={selectedRole === role}
            onClick={() => onSelect(role)}>
            <RoleAvatar roleId={role} fallback="assistant"/>
            <span>{label}</span>
          </button>
        ))}
      </div>
    </section>
  );
}
