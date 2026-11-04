/**
 * Direct-vs-product-sandbox parity harness.
 *
 * The reference pages are normally rendered with `page.setContent`. The real
 * product puts the same HTML through `makeInteractiveDocument` (sanitising,
 * CSP, an outer trusted frame and an inner opaque-origin frame) and talks to it
 * through the `studyUI` bridge. This module mounts that real path and captures
 * the same evidence from both environments, without mixing their scores.
 */
import type { Frame, Page } from "@playwright/test";

import { capture } from "./observer";

export type Host = Page | Frame;

export type Op =
  | { kind: "click"; name: string }
  | { kind: "input"; selector: string; value: string };

export type Snapshot = {
  text: string;
  declared: Record<string, number>;
  observed: Record<string, number>;
  canvases: Array<{
    pixels: number[] | null;
    marker: { x: number; y: number; radius: number } | null;
    verticalMarks: number[];
  }>;
  fontSizes: number[];
  controlSizes: number[];
  overflow: boolean;
};

export type Environment = {
  runtime: "pass" | "fail";
  runtime_errors: string[];
  text_before: string;
  text_after: string;
  declared_after: Record<string, number>;
  observed_after: Record<string, number>;
  canvas_after: string[];
  markers_after: Array<{ x: number; y: number; radius: number } | null>;
  marks_after: number[][];
  min_font: number | null;
  min_control: number | null;
  overflow: boolean;
  state_after: unknown;
};

export type ParityReport = {
  case_id: string;
  source_sha256: string;
  steps: string[];
  deterministic_canvas: boolean;
  has_canvas: boolean;
  canvas_compared: boolean;
  direct: Environment;
  sandbox: Environment;
  behavioral_differences: string[];
  environment_differences: string[];
  verdict: "same" | "different" | "indeterminate";
};

export type Watcher = { consoleErrors: string[]; pageErrors: string[] };

const CHANNEL = "m4c-parity";

export function normalizeText(text: string): string {
  return text.replace(/\s+/g, " ").trim();
}

function snapshotFrom(evidence: Awaited<ReturnType<typeof capture>>): Snapshot {
  return {
    text: normalizeText(evidence.text),
    declared: evidence.declared,
    observed: evidence.observed,
    canvases: evidence.canvases.map(canvas => ({
      pixels: canvas.pixels,
      marker: canvas.marker,
      verticalMarks: canvas.verticalMarks,
    })),
    fontSizes: evidence.fontSizes,
    controlSizes: evidence.controlSizes,
    overflow: evidence.horizontalOverflow,
  };
}

export async function snapshot(host: Host): Promise<Snapshot> {
  return snapshotFrom(await capture(host));
}

export async function applyOps(host: Host, ops: Op[]): Promise<void> {
  for (const op of ops) {
    if (op.kind === "click") {
      await host.getByRole("button", { name: op.name }).first().click();
      continue;
    }
    await host.locator(op.selector).evaluate((element, value) => {
      const input = element as HTMLInputElement;
      input.value = value;
      input.dispatchEvent(new Event("input", { bubbles: true }));
    }, op.value);
  }
}

/** Records `window.studyUI.setState` calls in direct rendering. */
function withRecorder(html: string): string {
  const recorder = `<script>window.__m4cStates=[];Object.defineProperty(window,"studyUI",{configurable:true,value:{setState:function(value){window.__m4cStates.push(value)},onRestore:function(){}}});<\/script>`;
  if (/<body[^>]*>/i.test(html)) {
    return html.replace(/<body[^>]*>/i, match => match + recorder);
  }
  return recorder + html;
}

export async function runDirect(
  page: Page,
  html: string,
  ops: Op[],
  errors: Watcher
): Promise<{ before: Snapshot; after: Snapshot; states: unknown[]; errors: string[] }> {
  errors.consoleErrors.length = 0;
  errors.pageErrors.length = 0;
  await page.setContent(withRecorder(html), { waitUntil: "load" });
  await page.waitForTimeout(120);
  const before = await snapshot(page);
  await applyOps(page, ops);
  await page.waitForTimeout(80);
  const after = await snapshot(page);
  const states = await page.evaluate(
    () => (window as unknown as { __m4cStates?: unknown[] }).__m4cStates ?? []
  );
  return {
    before,
    after,
    states,
    errors: [...errors.consoleErrors, ...errors.pageErrors],
  };
}

type SandboxMessage = { channel?: string; type?: string; value?: unknown };

export async function readMessages(page: Page): Promise<SandboxMessage[]> {
  return page.evaluate(
    () => (window as unknown as { __m4cMessages?: SandboxMessage[] }).__m4cMessages ?? []
  );
}

/**
 * Mount the real product path: `makeInteractiveDocument` plus an outer
 * `sandbox="allow-scripts"` iframe. The returned frame is the inner document.
 */
export async function mountSandbox(
  page: Page,
  html: string,
  viewport = { width: 900, height: 700 }
): Promise<Frame> {
  await page.setContent("<!doctype html><html><body></body></html>");
  const wrapped = await page.evaluate(
    async ({ source, channel }) => {
      const modulePath = "/src/features/answer-ui/interactiveRuntime.ts";
      const module = (await import(modulePath)) as {
        makeInteractiveDocument: (html: string, name: string) => string;
      };
      return module.makeInteractiveDocument(source, channel);
    },
    { source: html, channel: CHANNEL }
  );
  await page.evaluate(
    ({ source, channel, size }) => {
      const target = window as unknown as { __m4cMessages: SandboxMessage[] };
      target.__m4cMessages = [];
      window.addEventListener("message", event => {
        const data = event.data as SandboxMessage | null;
        if (data && typeof data === "object" && data.channel === channel) {
          target.__m4cMessages.push(data);
        }
      });
      const frame = document.createElement("iframe");
      frame.id = "m4c-outer";
      frame.setAttribute("sandbox", "allow-scripts");
      frame.setAttribute("referrerpolicy", "no-referrer");
      document.body.style.margin = "0";
      frame.style.border = "0";
      frame.style.width = `${size.width}px`;
      frame.style.height = `${size.height}px`;
      frame.srcdoc = source;
      document.body.append(frame);
    },
    { source: wrapped, channel: CHANNEL, size: viewport }
  );

  const deadline = Date.now() + 8000;
  let inner: Frame | undefined;
  while (Date.now() < deadline) {
    inner = page.frames().find(frame => frame.parentFrame()?.parentFrame() === page.mainFrame());
    if (inner) {
      const messages = await readMessages(page);
      if (messages.some(message => message.type === "ready")) return inner;
    }
    await page.waitForTimeout(50);
  }
  if (!inner) {
    throw new Error(`sandbox did not mount: ${normalizeText(html).slice(0, 80)}`);
  }
  return inner;
}

export function environmentOf(
  snapshotValue: Snapshot,
  beforeText: string,
  errors: string[],
  state: unknown
): Environment {
  return {
    runtime: errors.length ? "fail" : "pass",
    runtime_errors: errors,
    text_before: beforeText,
    text_after: snapshotValue.text,
    declared_after: snapshotValue.declared,
    observed_after: snapshotValue.observed,
    canvas_after: snapshotValue.canvases.map(canvas =>
      canvas.pixels ? canvas.pixels.join(",") : "unreadable"
    ),
    markers_after: snapshotValue.canvases.map(canvas => canvas.marker),
    marks_after: snapshotValue.canvases.map(canvas => canvas.verticalMarks),
    min_font: snapshotValue.fontSizes.length ? Math.min(...snapshotValue.fontSizes) : null,
    min_control: snapshotValue.controlSizes.length
      ? Math.min(...snapshotValue.controlSizes)
      : null,
    overflow: snapshotValue.overflow,
    state_after: state,
  };
}

export function stripControls(value: unknown): unknown {
  if (!value || typeof value !== "object" || Array.isArray(value)) return value;
  const { controls, ...rest } = value as Record<string, unknown>;
  return rest;
}

export function compare(
  caseId: string,
  sourceSha: string,
  steps: string[],
  direct: Environment,
  sandbox: Environment,
  deterministicCanvas: boolean
): ParityReport {
  const behavioral: string[] = [];
  const environment: string[] = [];
  const hasCanvas =
    direct.canvas_after.length > 0 || sandbox.canvas_after.length > 0;
  const canvasCompared = hasCanvas && deterministicCanvas;

  if (direct.text_before !== sandbox.text_before) behavioral.push("load text differs");
  if (direct.text_after !== sandbox.text_after) behavioral.push("text after operation differs");
  if (JSON.stringify(direct.declared_after) !== JSON.stringify(sandbox.declared_after)) {
    behavioral.push("declared values differ");
  }
  if (JSON.stringify(direct.observed_after) !== JSON.stringify(sandbox.observed_after)) {
    behavioral.push("observed values differ");
  }
  if (direct.runtime !== sandbox.runtime) behavioral.push("error presence differs");
  if (JSON.stringify(direct.state_after) !== JSON.stringify(sandbox.state_after)) {
    behavioral.push("bridge state differs");
  }
  if (deterministicCanvas) {
    if (JSON.stringify(direct.canvas_after) !== JSON.stringify(sandbox.canvas_after)) {
      behavioral.push("canvas pixels differ");
    }
    if (JSON.stringify(direct.markers_after) !== JSON.stringify(sandbox.markers_after)) {
      behavioral.push("canvas marker differs");
    }
    if (JSON.stringify(direct.marks_after) !== JSON.stringify(sandbox.marks_after)) {
      behavioral.push("amplitude marks differ");
    }
  }

  if (direct.min_font !== sandbox.min_font) {
    environment.push(`min font ${direct.min_font ?? "n/a"} vs ${sandbox.min_font ?? "n/a"}`);
  }
  if (direct.min_control !== sandbox.min_control) {
    environment.push(
      `min control ${direct.min_control ?? "n/a"} vs ${sandbox.min_control ?? "n/a"}`
    );
  }
  if (direct.overflow !== sandbox.overflow) {
    environment.push(`overflow ${direct.overflow} vs ${sandbox.overflow}`);
  }

  return {
    case_id: caseId,
    source_sha256: sourceSha,
    steps,
    deterministic_canvas: deterministicCanvas,
    has_canvas: hasCanvas,
    canvas_compared: canvasCompared,
    direct,
    sandbox,
    behavioral_differences: behavioral,
    environment_differences: environment,
    verdict: behavioral.length
      ? "different"
      : hasCanvas && !deterministicCanvas
        ? "indeterminate"
        : "same",
  };
}
