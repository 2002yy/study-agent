const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "";
const API_TOKEN = import.meta.env.VITE_STUDY_AGENT_API_TOKEN ?? "";

export type AbandonTurnResponse = {
  session_id: string;
  turn_id: string;
  status: "abandoned" | string;
  changed: boolean;
};

export async function abandonInterruptedTurn(
  sessionId: string,
  turnId: string
): Promise<AbandonTurnResponse> {
  const response = await fetch(
    `${API_BASE_URL}/sessions/${encodeURIComponent(sessionId)}/turns/${encodeURIComponent(turnId)}/abandon`,
    {
      method: "POST",
      headers: {
        ...(API_TOKEN ? { "X-Study-Agent-Token": API_TOKEN } : {}),
      },
    }
  );
  if (!response.ok) {
    const body = await response.text();
    throw new Error(
      `${response.status} ${response.statusText}${body ? `: ${body}` : ""}`
    );
  }
  return response.json() as Promise<AbandonTurnResponse>;
}
