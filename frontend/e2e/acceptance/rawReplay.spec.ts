import { expect, test } from "@playwright/test";
import { watchErrors } from "./observer";
import { replayRaw } from "./rawReplay";
import { j01Page } from "./semanticFixtures";
import { readMessages } from "./sandboxParity";

const VIEWPORTS = [{ width: 1280, height: 800 }, { width: 390, height: 844 }];

test("raw replay records the selected host and loads Three only on opt-in", async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== "desktop-chromium", "host contract runs once");
  await page.goto("/m4c-harness.html");
  const requested: string[] = [];
  page.on("request", request => requested.push(request.url()));
  const errors = watchErrors(page);
  const html = '<p id="result">loading</p><script>const available=typeof THREE!=="undefined";document.querySelector("#result").textContent=available?"local three ready":"ordinary page";studyUI.setState({three:available});</script>';
  const size = { width: 390, height: 844 };
  const ordinary = await replayRaw(page, html, null, size, errors);
  expect(ordinary.capabilities).toEqual([]);
  expect(requested.some(url => url.includes("study-three-source"))).toBe(false);
  expect((await readMessages(page)).some(message => message.type === "state" && (message.value as { three?: boolean }).three === false)).toBe(true);
  const three = await replayRaw(page, html, null, size, errors, ["three"]);
  expect(three.capabilities).toEqual(["three"]);
  expect(requested.some(url => url.includes("study-three-source"))).toBe(true);
  expect((await readMessages(page)).some(message => message.type === "state" && (message.value as { three?: boolean }).three === true)).toBe(true);
  expect(three.runtime_errors).toEqual([]);
});

for (const viewport of VIEWPORTS) {
  test(`raw sandbox semantic controls at ${viewport.width}px`, async ({ page }, testInfo) => {
    test.skip(testInfo.project.name !== "desktop-chromium", "explicit viewport matrix");
    await page.setViewportSize(viewport);
    await page.goto("/m4c-harness.html");
    const errors = watchErrors(page);
    const good = await replayRaw(page, j01Page("html"), "J01", viewport, errors);
    expect(good.inner_width).toBe(viewport.width);
    expect(good.checks.every(check => check.status === "pass")).toBe(true);
    const broken = await replayRaw(page, j01Page("broken"), "J01", viewport, errors);
    expect(broken.checks.find(check => check.checkId === "arrow-points-at-its-object")?.status).toBe("fail");
    const unknown = await replayRaw(page, "<p>距离6，路径A-B-C-D</p>", "A02", viewport, errors);
    expect(unknown.status).toBe("indeterminate");
    expect(unknown.checks.some(check => check.status === "indeterminate")).toBe(true);
    const runtime = await replayRaw(page, "<script>throw Error('negative control')</script>", "A02", viewport, errors);
    expect(runtime.checks.find(check => check.checkId === "runtime")?.status).toBe("fail");
  });
}
