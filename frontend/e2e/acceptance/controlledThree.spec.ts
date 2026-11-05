import { expect, test, type Frame, type Page } from "@playwright/test";
import { writeFileSync } from "node:fs";
import { controlledCube, controlledOscillator } from "../fixtures/controlled-three";
import { installApiFixture, makeLearningSession, seedWorkspaceRecovery } from "../api-fixture";

const channel = "controlled-three-acceptance";

async function mount(page: Page, html: string, viewport: { width: number; height: number }) {
  await page.goto("/m4c-harness.html");
  await page.evaluate(async ({ html, channel, viewport }) => {
    const runtimePath = "/src/features/answer-ui/interactiveRuntime.ts";
    const sourcePath = "/src/features/answer-ui/threeSource.ts";
    const runtime = await import(runtimePath);
    const loader = await import(sourcePath);
    const source = await loader.loadThreeSource();
    document.body.replaceChildren();
    (window as any).__threeState = null;
    window.addEventListener("message", event => {
      if (event.data?.channel === channel && event.data.type === "state") (window as any).__threeState = event.data.value;
    });
    const outer = document.createElement("iframe");
    outer.id = "three-host"; outer.sandbox.add("allow-scripts");
    outer.style.cssText = `border:0;width:100%;height:${viewport.height}px`;
    outer.srcdoc = runtime.makeInteractiveDocument(html, channel, ["three"], source);
    document.body.style.margin = "0";
    document.body.append(outer);
  }, { html, channel, viewport });
  await expect.poll(() => page.frames().filter(frame => frame.parentFrame()?.parentFrame() === page.mainFrame()).length).toBe(1);
  const inner = page.frames().find(frame => frame.parentFrame()?.parentFrame() === page.mainFrame())!;
  // Missing WebGL is an explicit failed capability, never a skipped/passing test.
  await expect(inner.locator("#support")).toHaveText("WebGL2 已就绪");
  await expect(inner.locator("canvas")).toBeVisible();
  return inner;
}

for (const viewport of [{ width: 1280, height: 800 }, { width: 390, height: 844 }]) {
  for (const card of [controlledCube, controlledOscillator]) {
    test(`React product replay ${card.id} at ${viewport.width}`, async ({ page }, testInfo) => {
      test.skip(testInfo.project.name !== "desktop-chromium", "explicit dual viewport React matrix");
      await page.setViewportSize(viewport);
      const session = makeLearningSession();
      const reply = "确定性离线能力示例。\n\n```study-ui\n" + JSON.stringify(card) + "\n```";
      session.detail.messages[1].content = reply;
      session.detail.turns[0].assistant_message = reply;
      // Existing fixture seeds localStorage with unguarded init scripts. Scope
      // those host-only seeds to top, so they never execute in opaque iframes.
      const addInitScript = page.addInitScript.bind(page);
      page.addInitScript = async (script, arg) => {
        if (typeof script !== "function") throw new Error("Expected fixture function seed");
        await addInitScript({ content: `if (window === window.top) { (${script.toString()})(${JSON.stringify(arg)}); }` });
      };
      const fixture = await installApiFixture(page, { session });
      await seedWorkspaceRecovery(page, session.row.session_id);
      page.addInitScript = addInitScript;
      const errors: string[] = [], outbound: string[] = [];
      page.on("pageerror", error => errors.push(error.message));
      page.on("request", request => { if (request.frame() !== page.mainFrame()) outbound.push(request.url()); });
      await page.goto("/");
      const region = page.getByRole("region", { name: card.title, exact: true });
      const nested = region.frameLocator("iframe").frameLocator("iframe");
      await expect(nested.locator("#support")).toHaveText("WebGL2 已就绪");
      const srcdoc = await region.locator("iframe").getAttribute("srcdoc");
      expect(srcdoc).toBeTruthy();
      writeFileSync(testInfo.outputPath(`${card.id}-demo.html`), `<!doctype html><meta charset="utf-8"><iframe sandbox="allow-scripts" style="border:0;width:100%;height:95vh" srcdoc="${srcdoc!.replace(/&/g, "&amp;").replace(/"/g, "&quot;")}"></iframe>`, "utf8");
      const inner = page.frames().find(frame => frame.parentFrame()?.parentFrame() === page.mainFrame())!;
      await checkPixels(inner);
      if (card.id === controlledCube.id) {
        const before = await nested.locator("canvas").screenshot();
        await nested.locator("#length").fill("3");
        await nested.locator("#width").fill("2");
        await nested.locator("#height").fill("2");
        await nested.locator("#rotation").fill("75");
        await expect(nested.locator("#reading")).toHaveText("体积 = 12.00");
        expect((await nested.locator("canvas").screenshot()).equals(before)).toBe(false);
        await region.getByRole("button", { name: "带着当前状态继续问" }).click();
        await expect(page.getByLabel("输入学习问题")).toHaveValue(/"volume":12/);
      } else {
        await nested.locator("#frequency").fill("2");
        await nested.locator("#phase").fill("1.5707963267948966");
        await expect(nested.locator("#reading")).toHaveText("t = 0.000 s; x = 2.000");
        await nested.getByRole("button", { name: "播放", exact: true }).click();
        await expect(nested.locator("#reading")).not.toHaveText("t = 0.000 s; x = 2.000");
        await nested.getByRole("button", { name: "暂停", exact: true }).click();
        const paused = await nested.locator("#reading").textContent();
        await page.waitForTimeout(160);
        await expect(nested.locator("#reading")).toHaveText(paused!);
        await checkPixels(inner);
        await nested.getByRole("button", { name: "播放", exact: true }).click();
        await expect(nested.locator("#reading")).not.toHaveText(paused!);
        await nested.getByRole("button", { name: "暂停", exact: true }).click();
      }
      await region.scrollIntoViewIfNeeded();
      await page.screenshot({ path: testInfo.outputPath(`react-${card.id}-${viewport.width}.png`) });
      expect(await region.getByRole("alert").count()).toBe(0);
      expect(outbound).toEqual([]);
      expect(errors).toEqual([]);
      expect(fixture.unexpectedApiPaths).toEqual([]);
    });
  }
}

async function state(page: Page) {
  return page.evaluate(() => (window as any).__threeState as Record<string, number | boolean>);
}

async function checkPixels(inner: Frame) {
  const dimensions = await inner.locator("canvas").evaluate(canvas => {
    const rect = canvas.getBoundingClientRect();
    return { bufferWidth: canvas.width, bufferHeight: canvas.height, displayWidth: rect.width, displayHeight: rect.height };
  });
  expect(Math.abs(dimensions.bufferWidth / dimensions.bufferHeight - dimensions.displayWidth / dimensions.displayHeight)).toBeLessThan(0.01);
  console.log("canvas geometry", JSON.stringify(dimensions));
  const pixels = await inner.locator("canvas").evaluate(canvas => {
    const gl = canvas.getContext("webgl2")!;
    const values = new Uint8Array(gl.drawingBufferWidth * gl.drawingBufferHeight * 4);
    gl.readPixels(0, 0, gl.drawingBufferWidth, gl.drawingBufferHeight, gl.RGBA, gl.UNSIGNED_BYTE, values);
    let geometry = 0;
    for (let index = 0; index < values.length; index += 4) {
      if (Math.abs(values[index] - values[0]) + Math.abs(values[index + 1] - values[1]) + Math.abs(values[index + 2] - values[2]) > 30) geometry++;
    }
    return geometry;
  });
  expect(pixels).toBeGreaterThan(100);
}

for (const viewport of [{ width: 1280, height: 800 }, { width: 390, height: 844 }]) {
  test(`controlled Three geometry and motion at ${viewport.width}`, async ({ page }, testInfo) => {
    test.skip(testInfo.project.name !== "desktop-chromium", "explicit dual viewport WebGL matrix");
    await page.setViewportSize(viewport);
    const errors: string[] = [];
    page.on("pageerror", error => errors.push(error.message));
    let inner = await mount(page, controlledCube.html, viewport);
    const originalGeometry = await inner.locator("canvas").screenshot();
    const outbound: string[] = [];
    page.on("request", request => { if (request.frame() !== page.mainFrame()) outbound.push(request.url()); });
    await inner.locator("#length").fill("3");
    await inner.locator("#width").fill("2");
    await inner.locator("#height").fill("2");
    await inner.locator("#rotation").fill("75");
    await expect(inner.locator("#reading")).toHaveText("体积 = 12.00");
    await expect.poll(async () => (await state(page))?.volume).toBe(12);
    expect((await state(page)).rotation).toBe(75);
    await checkPixels(inner);
    expect((await inner.locator("canvas").screenshot()).equals(originalGeometry)).toBe(false);
    await page.screenshot({ path: testInfo.outputPath(`cube-${viewport.width}.png`) });
    const isolation = await inner.evaluate(async () => {
      let parentBlocked = false, networkBlocked = false;
      try { void parent.document.body; } catch { parentBlocked = true; }
      try { await fetch("https://example.com/controlled-three-probe"); } catch { networkBlocked = true; }
      return { parentBlocked, networkBlocked, csp: document.querySelector('meta[http-equiv="Content-Security-Policy"]')?.getAttribute("content") };
    });
    expect(isolation.parentBlocked).toBe(true);
    expect(isolation.networkBlocked).toBe(true);
    expect(isolation.csp).toContain("connect-src 'none'");
    expect(outbound).toEqual([]);

    // The trusted loader may make host-local requests; the capability document makes none.
    inner = await mount(page, controlledOscillator.html, viewport);
    outbound.length = 0;
    await inner.locator("#phase").fill("1.5707963267948966");
    await inner.locator("#frequency").fill("2");
    await expect.poll(async () => (await state(page))?.position).toBeCloseTo(2, 5);
    await inner.getByRole("button", { name: "播放", exact: true }).click();
    await expect.poll(async () => Number((await state(page))?.time)).toBeGreaterThan(0.1);
    await inner.getByRole("button", { name: "暂停", exact: true }).click();
    await expect.poll(async () => (await state(page))?.playing).toBe(false);
    const stopped = await state(page);
    await page.waitForTimeout(160);
    expect(await state(page)).toEqual(stopped);
    expect(Number(stopped.position)).toBeCloseTo(2 * Math.sin(2 * Math.PI * 2 * Number(stopped.time) + Math.PI / 2), 6);
    await checkPixels(inner);
    await page.screenshot({ path: testInfo.outputPath(`motion-${viewport.width}.png`) });
    await inner.getByRole("button", { name: "播放", exact: true }).click();
    await expect.poll(async () => Number((await state(page))?.time)).toBeGreaterThan(Number(stopped.time) + 0.1);
    expect(outbound).toEqual([]);
    expect(errors).toEqual([]);
  });
}
