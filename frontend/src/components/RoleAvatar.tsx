import { Bot, User } from "lucide-react";
import { roleAvatarUrl } from "../features/roles/roleCatalog";

export function RoleAvatar({ roleId, fallback }: { roleId?: string; fallback: "user" | "assistant" }) {
  const avatarUrl = roleAvatarUrl(roleId);
  return (
    <div aria-hidden="true" className={`avatar ${avatarUrl ? "avatar-image" : ""}`}>
      {avatarUrl ? (
        <img alt="" src={avatarUrl} />
      ) : fallback === "user" ? (
        <User size={16} />
      ) : (
        <Bot size={16} />
      )}
    </div>
  );
}
