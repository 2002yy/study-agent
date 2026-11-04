import { expect, test } from "@playwright/test";
import { installApiFixture } from "../api-fixture";
import { noHorizontalOverflow } from "../journey-metrics";

test("imports inert local skills and sends the enabled choice only on the next message", async ({ page }, info) => {
  await installApiFixture(page);
  const rows: Array<{ id: string; name: string; description: string; content: string; enabled: boolean }> = [];
  await page.route("**/skills**", async route => {
    const request = route.request();
    const path = new URL(request.url()).pathname;
    if (path !== "/skills" && !path.startsWith("/skills/")) { await route.fallback(); return; }
    let body: unknown;
    if (request.method() === "GET") body = { skills: rows };
    else if (request.method() === "POST") {
      const content = request.postDataJSON().content;
      rows.push({ id: "local-1", name: "explain", description: "Explain clearly", content, enabled: false });
      body = rows[0];
    } else if (request.method() === "PATCH") {
      rows[0].enabled = request.postDataJSON().enabled;
      body = rows[0];
    } else { rows.splice(0); body = { deleted: true }; }
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(body) });
  });
  await page.goto("/");
  const more = page.getByLabel("打开更多学习工具").filter({ visible: true });
  if (!(await more.isVisible())) await page.getByLabel("打开会话历史").click();
  await more.click();
  await page.getByRole("menuitem", { name: /设置/ }).click();
  const panel = page.getByRole("region", { name: "本地 Skill", exact: true });
  await panel.getByLabel("粘贴 SKILL.md").fill("---\nname: explain\ndescription: Explain clearly\n---\n<script>window.skillScriptRan=true</script>");
  await panel.getByRole("button", { name: "安装 Skill", exact: true }).click();
  const choose = panel.getByRole("button", { name: "下条消息使用 explain", exact: true });
  await expect(choose).toBeDisabled();
  await panel.getByRole("checkbox", { name: "启用 explain", exact: true }).click();
  await expect(panel.getByRole("checkbox", { name: "启用 explain", exact: true })).toBeChecked();
  await expect(choose).toBeEnabled();
  await choose.click();
  await expect(panel.getByRole("status")).toContainText("1/3：explain");
  expect(await page.evaluate(() => (window as unknown as { skillScriptRan?: boolean }).skillScriptRan)).toBeUndefined();
  expect(await noHorizontalOverflow(page)).toBe(true);
  await panel.getByRole("status").scrollIntoViewIfNeeded();
  await page.screenshot({ path: info.outputPath("skill-selected.png"), fullPage: true });
  await page.getByRole("button", { name: "关闭设置", exact: true }).click();
  const sent = page.waitForRequest(request => new URL(request.url()).pathname === "/chat/stream" && request.method() === "POST");
  await page.getByLabel("输入学习问题").fill("请解释二分查找。");
  await page.getByRole("button", { name: "发送", exact: true }).click();
  const payload = (await sent).postDataJSON();
  expect(payload.selected_skill_ids).toEqual(["local-1"]);
  expect(payload.user_input).toBe("请解释二分查找。");
  expect(payload).not.toHaveProperty("skills");
  expect(payload.conversation_instruction ?? "").not.toContain("skillScriptRan");
});
