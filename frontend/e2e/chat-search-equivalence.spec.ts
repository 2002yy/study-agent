import { expect, test } from "@playwright/test";
import { FIRST_REPLY, installApiFixture } from "./api-fixture";

test("search and an explicit chat search request share the same request and answer surface", async ({ browser }) => {
  const requests: Record<string, unknown>[] = [];
  for (const mode of ["search", "chat"]) {
    const context = await browser.newContext();
    const page = await context.newPage();
    await installApiFixture(page);
    page.on("request", request => {
      if (request.method() === "POST" && /\/chat(?:\/stream)?$/.test(new URL(request.url()).pathname)) {
        const { turn_id: _turn, operation_id: _operation, ...payload } = request.postDataJSON();
        requests.push(payload);
      }
    });
    await page.goto("/");
    if (mode === "search") await page.getByRole("group", { name: "输入方式" }).getByRole("button", { name: "搜索" }).click();
    await page.getByLabel("输入学习问题").fill(mode === "search" ? "注意力机制" : "帮我搜索：注意力机制");
    await page.locator(".composer button[type=submit]").click();
    await expect(page.getByText(FIRST_REPLY, { exact: true })).toBeVisible();
    await expect(page.locator(".conversation .message.assistant")).toHaveCount(1);
    await context.close();
  }
  expect(requests).toHaveLength(2);
  expect(requests[0].user_input).toBe("帮我搜索：注意力机制");
  expect(requests[0]).toEqual(requests[1]);
});
