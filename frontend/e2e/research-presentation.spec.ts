import { expect, test } from "@playwright/test";
import { installApiFixture, makeLearningSession, seedWorkspaceRecovery } from "./api-fixture";
import { noHorizontalOverflow } from "./journey-metrics";

test("research stages update sources without rewriting the answer and survive refresh", async ({ page }, testInfo) => {
  const session = makeLearningSession();
  await installApiFixture(page, { session });
  await seedWorkspaceRecovery(page, session.row.session_id);
  let phase = 1;
  await page.route("**/research-presentation", async route => {
    const blocks = ["lookup", ...(phase >= 2 ? ["standard"] : []), ...(phase >= 3 ? ["deep"] : [])].map((tier, i) => ({
      block_id: `${tier}-run:research`, run_id: `${tier}-run`, revision: phase, tier,
      research_status: tier === "deep" ? "partial" : "completed", stage: "completed",
      publication_status: "observation_only", candidate_count: i === 0 ? 3 : null,
      read_count: i === 0 ? null : 1, read_attempt_count: i === 1 ? 1 : null,
      open_critical_gap_count: 1, updated_at: "2026-10-08T10:00:00Z", sources_truncated: false,
      bindings: [], research_phase: "completed", wave: tier === "deep" ? 2 : null, stop_reason: "", evidence_gate_status: null, conflict_count: null,
      sources: [{ block_id: `${tier}-run:source:1`, run_id: `${tier}-run`, source_id: "1", source_truth_version: 1,
        title: `${tier} 浏览器验收来源样例`, url: "https://example.com/price", read_status: i === 0 ? "unknown" : "read",
        publication_status: "observation_only" }],
      gaps: i === 1 ? [{ block_id: "standard-run:gap:price", field: "价格单位", research_state: "SOURCE_ACQUIRED",
        support_status: "NOT_EVALUATED", publication_status: "observation_only" }] : [],
    }));
    await route.fulfill({ contentType: "application/json", body: JSON.stringify({ protocol_version: 1,
      snapshot_kind: "turn", turn_updated_at: `2026-10-08T10:00:0${phase}Z`,
      session_id: session.row.session_id, turn_id: "turn-returning-1", publication_status: "observation_only",
      publication_authority: false, blocks, watch: false, truncated: false, audit_status: phase === 3 ? "audited" : null, audit_integrity: phase === 3 ? "valid" : "absent" }) });
  });
  await page.goto("/");
  const workspace = page.getByRole("region", { name: "研究工作区" });
  await expect(workspace).toBeVisible();
  const answer = page.locator(".message.assistant .markdown-message").last();
  const original = await answer.innerText();
  await workspace.getByText("Lookup · 快速查找", { exact: true }).click();
  await expect(workspace.getByText(/读取状态未提供/)).toBeVisible();
  phase = 2;
  await workspace.getByRole("button", { name: "刷新研究状态" }).click();
  await workspace.getByText("Standard · 对照核验", { exact: true }).click();
  await expect(workspace.getByText("尚未判断支持关系", { exact: true })).toBeVisible();
  expect(await answer.innerText()).toBe(original);
  phase = 3;
  await workspace.getByRole("button", { name: "刷新研究状态" }).click();
  await expect(workspace.getByText(/审计候选已就绪，尚未获准发布/)).toBeVisible();
  expect(await answer.innerText()).toBe(original);
  await page.reload();
  await expect(workspace.getByText(/审计候选已就绪，尚未获准发布/)).toBeVisible();
  await expect(workspace.locator("details")).toHaveCount(3);
  expect(await noHorizontalOverflow(page)).toBe(true);
  await expect(workspace.getByRole("slider")).toHaveCount(0);
  await workspace.getByRole("button", { name: "刷新研究状态" }).focus();
  await expect(workspace.getByRole("button", { name: "刷新研究状态" })).toBeFocused();
  for (const details of await workspace.locator("details").all()) {
    if (!(await details.getAttribute("open"))) await details.locator("summary").click();
  }
  await page.screenshot({ path: `D:/study-agent-validation/reading-notebook-ui-evidence/research-presentation-${testInfo.project.name}.png`, fullPage: true });
});
