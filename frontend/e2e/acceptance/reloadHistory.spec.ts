import { expect, test } from "@playwright/test";
import { installApiFixture, makeLearningSession, seedWorkspaceRecovery } from "../api-fixture";

for (const status of ["interrupted", "cancelled"]) {
  test(`reload ${status} draft and send saved history`, async ({ page }) => {
    const session = makeLearningSession();
    const original = "请保留 OLD_LIMIT_42";
    const answer = "OLD_ANSWER_21";
    const card = "```study-ui\n" + JSON.stringify({ type: "interactive", id: "draft", revision: 1, title: "Unfinished draft", summary: "pending", html: "<p>must not run</p>" }) + "\n```";
    session.detail.messages = [
      { role: "user", content: original, turnId: "old", turnStatus: "completed" },
      { role: "assistant", content: answer, turnId: "old", turnStatus: "completed" },
      { role: "user", content: "生成界面", turnId: "draft", turnStatus: status },
      { role: "assistant", content: card, turnId: "draft", turnStatus: status },
    ];
    await installApiFixture(page, { session });
    await seedWorkspaceRecovery(page, session.row.session_id);
    let loads = 0;
    page.on("request", request => {
      if (request.method() === "GET" && request.url().endsWith(`/sessions/${session.row.session_id}`)) loads++;
    });
    await page.goto("/");
    await expect(page.getByText("生成已停止，交互内容尚未完成，未运行。", { exact: true })).toBeVisible();
    const before = loads;
    await page.reload();
    await expect.poll(() => loads).toBeGreaterThan(before);
    await expect(page.getByText("生成已停止，交互内容尚未完成，未运行。", { exact: true })).toBeVisible();
    await expect(page.getByRole("region", { name: "Unfinished draft", exact: true })).toHaveCount(0);
    await expect(page.getByText("正在准备交互内容…", { exact: true })).toHaveCount(0);
    const request = page.waitForRequest(req => req.url().endsWith("/chat/stream") && req.method() === "POST");
    await page.getByLabel("输入学习问题").fill("再加入 NEW_LIMIT_7");
    await page.getByRole("button", { name: "发送", exact: true }).click();
    const payload = (await request).postDataJSON();
    expect(payload.chat_history).toEqual(expect.arrayContaining([
      expect.objectContaining({ role: "user", content: original }),
      expect.objectContaining({ role: "assistant", content: answer }),
    ]));
    expect(payload.user_input).toBe("再加入 NEW_LIMIT_7");
  });
}
