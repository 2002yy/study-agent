import { test, expect } from "@playwright/test";
import { installApiFixture } from "../api-fixture";
test("repair candidates wait for final publication", async ({ page }, info) => {
 await installApiFixture(page); await page.goto("/");
 await page.evaluate(async () => {
  const load = (url: string) => import(/* @vite-ignore */ url);
  const reactModule = await load("/node_modules/.vite/deps/react.js");
  const domModule = await load("/node_modules/.vite/deps/react-dom_client.js"); const { createRoot } = domModule.default ?? domModule; const React = reactModule.default ?? reactModule;
  const { MarkdownMessage } = await load("/src/components/MarkdownMessage.tsx");
  const host = document.createElement("div"); document.body.replaceChildren(host); const root = createRoot(host);
  const block = (revision: number) => "```study-ui\n" + JSON.stringify({type:"interactive",id:"repair",revision,title:"版本"+revision,summary:"离线候选",html:"<p>版本"+revision+"</p>"})+"\n```";
  (window as any).showRepair = (phase: string) => root.render(React.createElement("div",null,
   React.createElement(MarkdownMessage,{content:block(1),interactive:true}),
   React.createElement(MarkdownMessage,{content:phase === "rejected" ? "界面未更新\n\n````text\n"+block(2)+"\n````" : block(2),interactive:true,streaming:phase === "streaming"})));
  (window as any).showRepair("streaming");
 });
 await expect(page.getByRole("region",{name:"版本1",exact:true})).toBeVisible();
 await expect(page.getByText("正在准备交互内容…")).toBeVisible();
 await expect(page.getByRole("region",{name:"版本2",exact:true})).toHaveCount(0);
 await page.evaluate(() => (window as any).showRepair("rejected"));
 await expect(page.getByText("界面未更新",{exact:true})).toBeVisible();
 await expect(page.getByRole("region",{name:"版本2",exact:true})).toHaveCount(0);
 await page.screenshot({path:info.outputPath("rejected.png"),fullPage:true});
 await page.evaluate(() => (window as any).showRepair("accepted"));
 await expect(page.getByRole("region",{name:"版本2",exact:true})).toBeVisible();
 await expect(page.getByRole("region",{name:"版本1",exact:true})).toBeVisible();
 await page.screenshot({path:info.outputPath("accepted.png"),fullPage:true});
});

