// @vitest-environment jsdom
import "@testing-library/jest-dom/vitest";
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import * as api from "../../api";
import { SkillPanel } from "./SkillPanel";
import { consumePendingSkillSelection, getPendingSkillSelection, setPendingSkillSelection } from "./skillSelection";

vi.mock("../../api", () => ({ listLocalSkills: vi.fn(), importLocalSkill: vi.fn(), setLocalSkillEnabled: vi.fn(), deleteLocalSkill: vi.fn() }));
const skill = { id: "s1", name: "explain", description: "Readable explanation", enabled: false,
  content: "---\nname: explain\ndescription: Readable explanation\n---\n<script>window.bad=1</script>" };
beforeEach(() => { vi.clearAllMocks(); setPendingSkillSelection([]); vi.mocked(api.listLocalSkills).mockResolvedValue({ skills: [] }); });
afterEach(cleanup);

it("imports inert text disabled, requires enabling to select, and removes deleted selections", async () => {
  vi.mocked(api.importLocalSkill).mockResolvedValue(skill);
  vi.mocked(api.setLocalSkillEnabled).mockResolvedValue({ ...skill, enabled: true });
  vi.mocked(api.deleteLocalSkill).mockResolvedValue({ deleted: true });
  const view = render(<SkillPanel />);
  fireEvent.change(screen.getByLabelText("粘贴 SKILL.md"), { target: { value: skill.content } });
  await waitFor(() => expect(screen.getByRole("button", { name: "安装 Skill" })).toBeEnabled());
  fireEvent.click(screen.getByRole("button", { name: "安装 Skill" }));
  expect(await screen.findByRole("heading", { name: skill.name })).toBeVisible();
  expect(api.importLocalSkill).toHaveBeenCalledWith(skill.content);
  expect(view.container.querySelector("script,iframe,img")).toBeNull();
  expect(screen.getByRole("button", { name: "下条消息使用 explain" })).toBeDisabled();
  fireEvent.click(screen.getByRole("checkbox", { name: "启用 explain" }));
  await waitFor(() => expect(screen.getByRole("button", { name: "下条消息使用 explain" })).toBeEnabled());
  fireEvent.click(screen.getByRole("button", { name: "下条消息使用 explain" }));
  expect(getPendingSkillSelection()).toEqual(["s1"]);
  fireEvent.click(screen.getByRole("button", { name: "删除 explain" }));
  await waitFor(() => expect(getPendingSkillSelection()).toEqual([]));
});

it("enforces three selections and clears the visible selection when the next request consumes it", async () => {
  vi.mocked(api.listLocalSkills).mockResolvedValue({ skills: [1, 2, 3, 4].map(i => ({ ...skill, id: `s${i}`, name: `skill${i}`, enabled: true })) });
  render(<SkillPanel />);
  await screen.findByRole("heading", { name: "skill4" });
  for (const i of [1, 2, 3, 4]) fireEvent.click(screen.getByRole("button", { name: `下条消息使用 skill${i}` }));
  expect(getPendingSkillSelection()).toEqual(["s1", "s2", "s3"]);
  expect(screen.getByRole("alert")).toHaveTextContent("最多使用三个");
  act(() => { expect(consumePendingSkillSelection()).toEqual(["s1", "s2", "s3"]); });
  expect(screen.getByRole("status")).toHaveTextContent("0/3");
  expect(consumePendingSkillSelection()).toEqual([]);
});

it("reads an uploaded markdown file as text without automatically installing it", async () => {
  render(<SkillPanel />);
  const file = new File([skill.content], "SKILL.md", { type: "text/markdown" });
  Object.defineProperty(file, "text", { value: async () => skill.content });
  fireEvent.change(screen.getByLabelText("上传 SKILL.md"), { target: { files: [file] } });
  await waitFor(() => expect(screen.getByLabelText("粘贴 SKILL.md")).toHaveValue(skill.content));
  expect(api.importLocalSkill).not.toHaveBeenCalled();
});
