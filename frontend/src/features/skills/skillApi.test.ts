import { afterEach, expect, it, vi } from "vitest";
import { deleteLocalSkill, importLocalSkill, listLocalSkills, setLocalSkillEnabled, sendChat, sendWechatMessage } from "../../api";
import { setPendingSkillSelection, getPendingSkillSelection } from "./skillSelection";
import { CHAT_SETTINGS_DEFAULTS, RAG_SETTINGS_DEFAULTS } from "../settings/SettingsPanel";
afterEach(() => { setPendingSkillSelection([]); vi.unstubAllGlobals(); });

it("sends skill identities once on single chat, never content, text commands or group chat", async () => {
  const fetchMock = vi.fn(async () => new Response("{}", { status: 200 }));
  vi.stubGlobal("fetch", fetchMock);
  const options = { chatSettings: CHAT_SETTINGS_DEFAULTS, ragSettings: RAG_SETTINGS_DEFAULTS, ragEnabled: false };
  setPendingSkillSelection(["s1", "s2"]);
  await sendWechatMessage("group question", options);
  expect(getPendingSkillSelection()).toEqual(["s1", "s2"]);
  await sendChat("unchanged question", [], options);
  await sendChat("next question", [], options);
  const payloads = fetchMock.mock.calls.map(call => JSON.parse(String((call as unknown as [string, RequestInit])[1].body)));
  expect(payloads[0]).not.toHaveProperty("selected_skill_ids");
  expect(payloads[1].selected_skill_ids).toEqual(["s1", "s2"]);
  expect(payloads[1].user_input).toBe("unchanged question");
  expect(payloads[1]).not.toHaveProperty("skills");
  expect(payloads[2].selected_skill_ids).toEqual([]);
});

it("uses the skill management API without sending the body during enable/delete", async () => {
  const fetchMock = vi.fn(async () => new Response("{}", { status: 200 }));
  vi.stubGlobal("fetch", fetchMock);
  await listLocalSkills(); await importLocalSkill("plain text");
  await setLocalSkillEnabled("id/one", true); await deleteLocalSkill("id/one");
  const calls = fetchMock.mock.calls as unknown as [string, RequestInit][];
  expect(calls[0][0]).toBe("/skills");
  expect(JSON.parse(String(calls[1][1].body))).toEqual({ content: "plain text" });
  expect(calls[2][0]).toBe("/skills/id%2Fone");
  expect(JSON.parse(String(calls[2][1].body))).toEqual({ enabled: true });
  expect(calls[3][1].method).toBe("DELETE");
});
