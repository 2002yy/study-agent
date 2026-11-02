export const roleOptions = [
  ["auto", "自动"],
  ["march7", "三月七"],
  ["keqing", "刻晴"],
  ["nahida", "纳西妲"],
  ["firefly", "流萤"]
] as const;

export const roleAvatarPaths: Record<string, string> = {
  march7: "/assets/avatars/march7.png",
  keqing: "/assets/avatars/keqing.png",
  nahida: "/assets/avatars/nahida.png",
  firefly: "/assets/avatars/firefly.png"
};

export const roleVoices: Record<string, string> = {
  auto: "随问题自动选择，也可固定一位伙伴",
  nahida: "温和拆解，连接原理",
  march7: "轻快好奇，抓住反直觉",
  firefly: "细致陪练，一步步看清",
  keqing: "直接清醒，砍到下一步",
};

export const speakerToRole: Record<string, string> = {
  三月七: "march7",
  刻晴: "keqing",
  纳西妲: "nahida",
  流萤: "firefly",
  用户: "user"
};

export function roleAvatarUrl(roleId: string | undefined): string {
  return roleId ? roleAvatarPaths[roleId] ?? "" : "";
}

export function roleLabel(roleId: string | undefined): string {
  if (!roleId || roleId === "auto") {
    return "学习助手";
  }
  return roleOptions.find(([value]) => value === roleId)?.[1] ?? "学习助手";
}
