import { expect, test } from "@playwright/test";
import { installApiFixture, makeLearningSession, seedWorkspaceRecovery } from "../api-fixture";

for (const viewport of [{ width: 1280, height: 800 }, { width: 390, height: 844 }]) {
  test(`host layout evidence produces only an unsent repair draft at ${viewport.width}`, async ({ page }, info) => {
    test.skip(info.project.name !== "desktop-chromium", "explicit desktop/mobile viewport matrix");
    await page.setViewportSize(viewport);
    const broken = {
      type: "interactive", id: "layout-broken", revision: 2, title: "排版故障负控", summary: "固定离线样例，不调用模型。",
      html: `<style>#small{font-size:13px}#tiny{width:20px;height:20px;min-height:0;padding:0;border:0;font-size:16px}#wide{width:1600px;height:30px;background:#ddd}</style><p id="small">实际小字号</p><button id="tiny">+</button><div id="wide">固定宽度内容</div>`,
    };
    const compliant = {
      type: "interactive", id: "layout-compliant", revision: 1, title: "排版合规对照", summary: "只证明已覆盖的排版项目。",
      html: `<p id="readable" style="font-size:16px">清晰文字</p><button id="large" style="width:100px;height:44px">普通控件</button>`,
    };
    const session = makeLearningSession();
    const reply = [broken, compliant].map(card => "```study-ui\n" + JSON.stringify(card) + "\n```").join("\n\n");
    session.detail.messages[1].content = reply;
    session.detail.turns[0].assistant_message = reply;
    // Keep fixture localStorage seed scripts out of opaque-origin frames.
    const addInitScript = page.addInitScript.bind(page);
    page.addInitScript = async (script, arg) => {
      if (typeof script !== "function") throw new Error("Expected fixture function seed");
      await addInitScript({ content: `if (window === window.top) { (${script.toString()})(${JSON.stringify(arg)}); }` });
    };
    const fixture = await installApiFixture(page, { session });
    await seedWorkspaceRecovery(page, session.row.session_id);
    page.addInitScript = addInitScript;
    const errors: string[] = [];
    page.on("pageerror", error => errors.push(error.message));
    await page.goto("/");
    const region = page.getByRole("region", { name: broken.title, exact: true });
    const nested = region.frameLocator("iframe").frameLocator("iframe");
    await expect(nested.locator("#small")).toBeVisible();
    const expected = await nested.locator("#small").evaluate(el => ({
      font: parseFloat(getComputedStyle(el).fontSize),
      width: document.getElementById("tiny")!.getBoundingClientRect().width,
      height: document.getElementById("tiny")!.getBoundingClientRect().height,
      overflow: Math.max(document.documentElement.scrollWidth, document.body.scrollWidth) - innerWidth,
    }));
    expect(expected.font).toBe(13);
    expect(expected.width).toBe(20);
    expect(expected.height).toBe(20);
    expect(expected.overflow).toBeGreaterThan(0);
    await region.getByRole("button", { name: "检查排版", exact: true }).click();
    const diagnostics = region.getByRole("region", { name: "界面排版检查" });
    await expect(diagnostics).toContainText("#small · usability-font：实测 13.0 px，阈值 14 px");
    await expect(diagnostics).toContainText("#tiny · control-width：实测 20.0 px，阈值 40 px");
    await expect(diagnostics).toContainText("#tiny · control-height：实测 20.0 px，阈值 40 px");
    await expect(diagnostics).toContainText(`document · horizontal-overflow：实测 ${expected.overflow.toFixed(1)} px，阈值 0 px`);
    await region.getByRole("button", { name: "生成修复草稿", exact: true }).click();
    const composer = page.getByLabel("输入学习问题");
    await expect(composer).toHaveValue(/"checkId":"usability-font","elementId":"#small","measured":13,"threshold":14/);
    expect(await composer.inputValue()).toContain("当前版本：2；新版本：3");
    expect(fixture.chatAttempts).toBe(0);
    await page.screenshot({ path: info.outputPath(`repair-draft-${viewport.width}.png`) });

    const good = page.getByRole("region", { name: compliant.title, exact: true });
    await good.getByRole("button", { name: "检查排版", exact: true }).click();
    await expect(good).toContainText("已覆盖的排版项目未发现问题；这不代表内容或交互逻辑正确。");
    await expect(good.getByRole("button", { name: "生成修复草稿", exact: true })).toHaveCount(0);
    const csp = await nested.locator('meta[http-equiv="Content-Security-Policy"]').getAttribute("content");
    expect(csp).toContain("connect-src 'none'");
    expect(csp).toContain("frame-src 'none'");
    expect(await region.locator("iframe").getAttribute("sandbox")).toBe("allow-scripts");
    expect(fixture.chatAttempts).toBe(0);
    expect(fixture.unexpectedApiPaths).toEqual([]);
    expect(errors).toEqual([]);
    await page.screenshot({ path: info.outputPath(`repair-compliant-${viewport.width}.png`) });
  });
}
