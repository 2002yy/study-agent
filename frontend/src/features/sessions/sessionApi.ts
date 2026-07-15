import type { SemanticSessionRow } from "./sessionNavigation";

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "";
const API_TOKEN = import.meta.env.VITE_STUDY_AGENT_API_TOKEN ?? "";

export async function updateSessionTitle(
  sessionId: string,
  title: string
): Promise<SemanticSessionRow> {
  const response = await fetch(
    `${API_BASE_URL}/sessions/${encodeURIComponent(sessionId)}/title`,
    {
      method: "PATCH",
      headers: {
        "Content-Type": "application/json",
        ...(API_TOKEN ? { "X-Study-Agent-Token": API_TOKEN } : {}),
      },
      body: JSON.stringify({ title }),
    }
  );
  if (!response.ok) {
    const body = await response.text();
    throw new Error(
      `${response.status} ${response.statusText}${body ? `: ${body}` : ""}`
    );
  }
  const payload = (await response.json()) as { session: SemanticSessionRow };
  return payload.session;
}
