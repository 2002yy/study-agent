import { createServer, type ServerResponse } from "node:http";
import { expect, test } from "@playwright/test";
import { installApiFixture } from "../api-fixture";
for (const mode of ["accepted", "rejected", "interrupted"]) {
  test(`real SSE final ${mode}`, async ({page}) => {
    let stream: ServerResponse | undefined;
    const card = "```study-ui\n" + JSON.stringify({type:"interactive", id:"draft", revision:1, title:"Candidate", summary:"offline", html:"<p>candidate</p>"}) + "\n```";
    const event = (name:string, data:unknown) => `event: ${name}\ndata: ${JSON.stringify(data)}\n\n`;
    const server = createServer((req,res) => {req.resume(); req.on("end", () => {stream=res; res.writeHead(200,{"Content-Type":"text/event-stream","Access-Control-Allow-Origin":"*"});res.write(event("session",{session_id:"sse-test",turn_id:"sse-turn"}));res.write(event("token",{text:card}));});});
    await new Promise<void>(resolve=>server.listen(0,"127.0.0.1",resolve));
    const address=server.address() as {port:number};
    try {
      await installApiFixture(page);
      await page.route("**/chat/stream",route=>route.continue({url:`http://127.0.0.1:${address.port}/chat/stream`}));
      await page.goto("/");
      await page.getByLabel("输入学习问题").fill("演示界面");
      await page.getByRole("button",{name:"发送",exact:true}).click();
      await expect.poll(()=>Boolean(stream)).toBe(true);
      await expect(page.getByRole("region",{name:"Candidate",exact:true})).toHaveCount(0);
      if(mode==="interrupted") stream!.end();
      else stream!.end(event("done",{session_id:"sse-test",turn_id:"sse-turn",reply:mode==="accepted"?card:"界面未更新\n\n````text\n"+card+"\n````"}));
      if(mode==="accepted") await expect(page.getByRole("region",{name:"Candidate",exact:true})).toBeVisible();
      else {
        if(mode==="interrupted") { await expect(page.getByText("生成已停止，交互内容尚未完成，未运行。",{exact:true})).toBeVisible(); await expect(page.getByText("正在准备交互内容…",{exact:true})).toHaveCount(0); const unfinished=page.getByText("查看未完成内容",{exact:true}); await unfinished.focus(); await page.keyboard.press("Enter"); await expect(page.locator("pre").filter({hasText:"study-ui"}).first()).toBeVisible(); }
        await expect(page.getByText(mode==="rejected"?"界面未更新":"生成已停止，交互内容尚未完成，未运行。",{exact:false}).first()).toBeVisible();
        await expect(page.getByRole("region",{name:"Candidate",exact:true})).toHaveCount(0);
      }
    } finally {stream?.destroy();server.closeAllConnections();await new Promise<void>(resolve=>server.close(()=>resolve()));}
  });
}
