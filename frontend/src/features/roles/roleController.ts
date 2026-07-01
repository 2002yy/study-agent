import { useEffect, useState } from "react";

import { loadRole } from "../../api";
import { serverQueryCache } from "../../app/serverQueryCache";
import type { RoleResponse } from "../../types";

export function useRoleController(roleId: string) {
  const [detail, setDetail] = useState<RoleResponse | null>(null);
  const load = async () => {
    if (roleId === "auto") {
      setDetail(null);
      return;
    }
    try {
      setDetail(
        await serverQueryCache.query(
          `role:${roleId}`,
          () => loadRole(roleId),
          60_000
        )
      );
    } catch (error) {
      const message = error instanceof Error ? error.message : "角色读取失败";
      setDetail({
        id: roleId,
        label: roleId,
        prompt: "",
        summary: message,
        description: message,
      });
    }
  };
  useEffect(() => {
    setDetail(null);
    void load();
  }, [roleId]);
  return { detail, load };
}
