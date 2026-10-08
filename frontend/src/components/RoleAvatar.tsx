import { Bot, User } from "lucide-react";
import { useState } from "react";
import { roleAvatarUrl } from "../features/roles/roleCatalog";

export function RoleAvatar({ roleId, fallback }: { roleId?: string; fallback: "user" | "assistant" }) {
  const avatarUrl = roleAvatarUrl(roleId);
  const [failedUrl, setFailedUrl] = useState("");
  const showImage = Boolean(avatarUrl && failedUrl !== avatarUrl);
  return (
    <div aria-hidden="true" className={`avatar ${showImage ? "avatar-image" : ""}`}>
      {showImage ? (
        <img alt="" src={avatarUrl} onError={() => setFailedUrl(avatarUrl)} />
      ) : fallback === "user" ? (
        <User size={16} />
      ) : (
        <Bot size={16} />
      )}
    </div>
  );
}
