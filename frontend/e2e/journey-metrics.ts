import {
  existsSync,
  mkdirSync,
  readFileSync,
  writeFileSync,
} from "node:fs";
import { basename, dirname, resolve } from "node:path";

import type { Page, TestInfo } from "@playwright/test";

import {
  GOLDEN_JOURNEY_METRICS_PATH,
  GOLDEN_JOURNEY_SUCCESS_DIR,
  GOLDEN_JOURNEY_SUCCESS_MANIFEST_PATH,
} from "./global-setup";

const ACTION_STORAGE_KEY = "study-agent-golden-journey-actions-v1";

export type JourneyAction = {
  kind: "click" | "keydown" | "send" | "scroll";
  label: string;
  at: number;
  decision: boolean;
  recovery: boolean;
  surface_switch: boolean;
};

export type JourneyActionSummary = {
  clicks: number;
  keyboard_events: number;
  sends: number;
  scrolls: number;
  decision_actions: number;
  recovery_actions: number;
  surface_switches: number;
  actions: JourneyAction[];
};

export type JourneyMetric = {
  journey: string;
  project: string;
  viewport: { width: number; height: number } | null;
  required_clicks: number;
  required_decisions: number;
  product_surfaces: number;
  recovery_clicks: number;
  has_actionable_failure: boolean;
  keyboard_only: boolean;
  refresh_restore: boolean;
  no_horizontal_overflow: boolean;
  action_summary?: JourneyActionSummary;
  product_surface_names?: string[];
  success_artifacts?: string[];
};

export type SuccessArtifact = {
  journey: string;
  project: string;
  step: string;
  file: string;
  viewport: { width: number; height: number } | null;
  scroll_y: number;
  document_height: number;
  screenshot_mode: "viewport";
  product_surfaces: string[];
};

export async function installJourneyRecorder(page: Page) {
  await page.addInitScript(({ storageKey }) => {
    type BrowserAction = {
      kind: "click" | "keydown" | "send" | "scroll";
      label: string;
      at: number;
      decision: boolean;
      recovery: boolean;
      surface_switch: boolean;
    };

    const read = (): BrowserAction[] => {
      try {
        const raw = window.sessionStorage.getItem(storageKey);
        return raw ? (JSON.parse(raw) as BrowserAction[]) : [];
      } catch {
        return [];
      }
    };
    const write = (actions: BrowserAction[]) => {
      try {
        window.sessionStorage.setItem(storageKey, JSON.stringify(actions));
      } catch {
        // Diagnostic-only recorder: never block the product journey.
      }
    };
    const push = (action: BrowserAction) => write([...read(), action]);
    const compact = (value: string) => value.replace(/\s+/g, " ").trim().slice(0, 160);
    const labelFor = (target: EventTarget | null) => {
      const node = target instanceof Element
        ? target.closest('button, a, summary, [role="button"], [role="menuitem"], input, textarea')
        : null;
      if (!node) return "";
      return compact(
        node.getAttribute("aria-label")
          ?? node.getAttribute("title")
          ?? node.getAttribute("value")
          ?? node.textContent
          ?? node.tagName.toLowerCase(),
      );
    };
    const recoveryPattern = /继续这里|从断点继续|重新生成|归档并新建/;
    const decisionPattern = /继续这里|开始系统学习|确认并保存学习成果|归档并新建/;
    const surfacePattern = /上传学习资料|打开更多学习工具|学习成果|资料与来源|开发者诊断|关闭/;

    document.addEventListener("click", (event) => {
      const label = labelFor(event.target);
      push({
        kind: "click",
        label,
        at: Date.now(),
        decision: decisionPattern.test(label),
        recovery: recoveryPattern.test(label),
        surface_switch: surfacePattern.test(label),
      });
    }, true);

    document.addEventListener("keydown", (event) => {
      if (!(event instanceof KeyboardEvent)) return;
      if (!["Tab", "Enter", "Escape", "PageDown", "PageUp", "Home", "End"].includes(event.key)) return;
      push({
        kind: event.key === "PageDown" || event.key === "PageUp" || event.key === "Home" || event.key === "End"
          ? "scroll"
          : "keydown",
        label: event.key,
        at: Date.now(),
        decision: false,
        recovery: false,
        surface_switch: false,
      });
    }, true);

    document.addEventListener("submit", (event) => {
      const form = event.target instanceof HTMLFormElement ? event.target : null;
      if (!form?.matches("form.composer")) return;
      push({
        kind: "send",
        label: "composer-submit",
        at: Date.now(),
        decision: false,
        recovery: false,
        surface_switch: false,
      });
    }, true);

    window.addEventListener("wheel", (event) => {
      if (!(event instanceof WheelEvent) || Math.abs(event.deltaY) < 16) return;
      push({
        kind: "scroll",
        label: `wheel:${Math.round(event.deltaY)}`,
        at: Date.now(),
        decision: false,
        recovery: false,
        surface_switch: false,
      });
    }, { passive: true });

    let touchStartY: number | null = null;
    window.addEventListener("touchstart", (event) => {
      touchStartY = event.touches.item(0)?.clientY ?? null;
    }, { passive: true });
    window.addEventListener("touchend", (event) => {
      const endY = event.changedTouches.item(0)?.clientY ?? null;
      if (touchStartY === null || endY === null) return;
      const delta = touchStartY - endY;
      touchStartY = null;
      if (Math.abs(delta) < 24) return;
      push({
        kind: "scroll",
        label: `touch:${Math.round(delta)}`,
        at: Date.now(),
        decision: false,
        recovery: false,
        surface_switch: false,
      });
    }, { passive: true });
  }, { storageKey: ACTION_STORAGE_KEY });
}

export async function readJourneyActions(page: Page): Promise<JourneyAction[]> {
  return page.evaluate(({ storageKey }) => {
    try {
      const raw = window.sessionStorage.getItem(storageKey);
      return raw ? JSON.parse(raw) : [];
    } catch {
      return [];
    }
  }, { storageKey: ACTION_STORAGE_KEY });
}

export async function journeyActionSummary(page: Page): Promise<JourneyActionSummary> {
  const actions = await readJourneyActions(page);
  return {
    clicks: actions.filter((action) => action.kind === "click").length,
    keyboard_events: actions.filter((action) => action.kind === "keydown").length,
    sends: actions.filter((action) => action.kind === "send").length,
    scrolls: actions.filter((action) => action.kind === "scroll").length,
    decision_actions: actions.filter((action) => action.decision).length,
    recovery_actions: actions.filter((action) => action.recovery).length,
    surface_switches: actions.filter((action) => action.surface_switch).length,
    actions,
  };
}

export async function focusComposerWithKeyboard(page: Page) {
  const composer = page.getByLabel("输入学习问题");
  for (let presses = 0; presses < 40; presses += 1) {
    if (await composer.evaluate((element) => document.activeElement === element)) {
      return presses;
    }
    await page.keyboard.press("Tab");
  }
  throw new Error("Keyboard focus could not reach the learning composer");
}

export async function requiredComposerDecisions(page: Page) {
  return page.locator(
    'form.composer select:visible, form.composer [aria-required="true"]:visible',
  ).count();
}

export async function visibleProductSurfaceNames(page: Page) {
  const candidates = [
    ["main", page.locator("main#chat")],
    ["dialog", page.getByRole("dialog")],
    ["returning_restore", page.getByRole("region", { name: "继续当前任务" })],
    ["interrupted_recovery", page.getByRole("region", { name: "中断任务恢复" })],
    ["upload_handoff", page.getByText("资料已准备好", { exact: true })],
    ["adopted_evidence", page.getByRole("region", { name: "已核验引用" })],
    ["closure_review", page.getByTestId("learning-closure-review")],
  ] as const;
  const visible: string[] = [];
  for (const [name, locator] of candidates) {
    if (await locator.first().isVisible().catch(() => false)) visible.push(name);
  }
  return visible;
}

export async function visibleProductSurfaces(page: Page) {
  return (await visibleProductSurfaceNames(page)).length;
}

export async function noHorizontalOverflow(page: Page) {
  return page.evaluate(() =>
    document.documentElement.scrollWidth <= document.documentElement.clientWidth + 1,
  );
}

function safeSegment(value: string) {
  return value.toLowerCase().replace(/[^a-z0-9_-]+/g, "-").replace(/^-+|-+$/g, "");
}

function successManifest(): SuccessArtifact[] {
  return existsSync(GOLDEN_JOURNEY_SUCCESS_MANIFEST_PATH)
    ? JSON.parse(readFileSync(GOLDEN_JOURNEY_SUCCESS_MANIFEST_PATH, "utf8")) as SuccessArtifact[]
    : [];
}

export async function captureSuccessStep(
  page: Page,
  testInfo: TestInfo,
  journey: string,
  step: string,
): Promise<string> {
  const filename = `${safeSegment(journey)}--${safeSegment(testInfo.project.name)}--${safeSegment(step)}.png`;
  const path = resolve(GOLDEN_JOURNEY_SUCCESS_DIR, filename);
  mkdirSync(dirname(path), { recursive: true });
  const surfaces = await visibleProductSurfaceNames(page);
  const pagePosition = await page.evaluate(() => ({
    scrollY: Math.round(window.scrollY),
    documentHeight: document.documentElement.scrollHeight,
  }));
  await page.screenshot({ path, fullPage: false, animations: "disabled" });
  const artifact: SuccessArtifact = {
    journey,
    project: testInfo.project.name,
    step,
    file: filename,
    viewport: page.viewportSize(),
    scroll_y: pagePosition.scrollY,
    document_height: pagePosition.documentHeight,
    screenshot_mode: "viewport",
    product_surfaces: surfaces,
  };
  const next = successManifest()
    .filter((item) => !(item.journey === journey && item.project === testInfo.project.name && item.step === step))
    .concat(artifact)
    .sort((left, right) =>
      `${left.journey}:${left.project}:${left.step}`.localeCompare(
        `${right.journey}:${right.project}:${right.step}`,
      ),
    );
  writeFileSync(
    GOLDEN_JOURNEY_SUCCESS_MANIFEST_PATH,
    `${JSON.stringify(next, null, 2)}\n`,
  );
  await testInfo.attach(`success:${journey}:${step}`, {
    path,
    contentType: "image/png",
  });
  return basename(path);
}

export async function recordObservedMetric(
  page: Page,
  testInfo: TestInfo,
  input: {
    journey: string;
    refresh_restore: boolean;
    has_actionable_failure: boolean;
    success_artifacts: string[];
    composer_decisions?: number;
  },
) {
  const actionSummary = await journeyActionSummary(page);
  const currentSurfaceNames = await visibleProductSurfaceNames(page);
  const artifactSurfaceNames = successManifest()
    .filter((item) =>
      item.journey === input.journey
      && item.project === testInfo.project.name
      && input.success_artifacts.includes(item.file),
    )
    .flatMap((item) => item.product_surfaces);
  const surfaceNames = [...new Set([...currentSurfaceNames, ...artifactSurfaceNames])].sort();
  await recordMetric(testInfo, {
    journey: input.journey,
    project: testInfo.project.name,
    viewport: page.viewportSize(),
    required_clicks: actionSummary.clicks,
    required_decisions: actionSummary.decision_actions + (input.composer_decisions ?? 0),
    product_surfaces: surfaceNames.length,
    recovery_clicks: actionSummary.recovery_actions,
    has_actionable_failure: input.has_actionable_failure,
    keyboard_only: actionSummary.clicks === 0 && actionSummary.keyboard_events > 0,
    refresh_restore: input.refresh_restore,
    no_horizontal_overflow: await noHorizontalOverflow(page),
    action_summary: actionSummary,
    product_surface_names: surfaceNames,
    success_artifacts: input.success_artifacts,
  });
}

export async function recordMetric(testInfo: TestInfo, metric: JourneyMetric) {
  const current: JourneyMetric[] = existsSync(GOLDEN_JOURNEY_METRICS_PATH)
    ? JSON.parse(readFileSync(GOLDEN_JOURNEY_METRICS_PATH, "utf8")) as JourneyMetric[]
    : [];
  const next = current
    .filter((item) => !(item.journey === metric.journey && item.project === metric.project))
    .concat(metric)
    .sort((left, right) =>
      `${left.journey}:${left.project}`.localeCompare(`${right.journey}:${right.project}`),
    );
  writeFileSync(GOLDEN_JOURNEY_METRICS_PATH, `${JSON.stringify(next, null, 2)}\n`);
  await testInfo.attach("golden-journey-metric", {
    body: Buffer.from(JSON.stringify(metric, null, 2)),
    contentType: "application/json",
  });
}
