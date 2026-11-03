/**
 * Semantic locators for real saved documents (M4-C, no model calls).
 *
 * The reference pages expose structured evidence through test attributes. Real
 * answers do not, so this module locates the same facts the way a reader would:
 * by the controls' visible text, by node labels, and by the geometry the page
 * actually drew. Anything it cannot locate stays absent, and the judge turns
 * that into `indeterminate` rather than a pass.
 */
import type { Page } from "@playwright/test";

import type { Observation, Phase, SvgShape } from "../../src/acceptance/model";
import { capture, type ErrorCapture } from "./observer";

export type Box = { x: number; y: number; width: number; height: number };
type Arrow = { x1: number; y1: number; x2: number; y2: number };
type VariableNode = { name: string; box: Box; declaredTarget: number | null; geometricTarget: number | null };
type ObjectNode = { index: number; box: Box; hits: number | null; label: string };
type Snapshot = {
  step: number | null;
  text: string;
  variables: VariableNode[];
  objects: ObjectNode[];
  arrows: Arrow[];
};

export type GenericBehavior = {
  motion: "pass" | "fail" | "indeterminate";
  pause: "pass" | "fail" | "indeterminate";
  detail: string;
};

const ARROW_START_TOLERANCE = 12;
const ARROW_TARGET_TOLERANCE = 16;

function distanceToBox(box: Box, point: { x: number; y: number }): number {
  const dx = Math.max(box.x - point.x, 0, point.x - (box.x + box.width));
  const dy = Math.max(box.y - point.y, 0, point.y - (box.y + box.height));
  return Math.hypot(dx, dy);
}

/** Read labels and geometry without assuming any test attribute exists. */
async function readSnapshot(page: Page): Promise<Snapshot> {
  return page.evaluate(() => {
    const VARIABLE = /^[A-Za-z_][A-Za-z0-9_]*$/;
    const OBJECT = /^对象\s*(\d+)/;
    const GHOST = /尚未创建|未创建/;

    const arrowSvg =
      document.querySelector("svg.arrows") ?? document.querySelector("svg");
    const ctm =
      arrowSvg && typeof (arrowSvg as SVGSVGElement).getScreenCTM === "function"
        ? (arrowSvg as SVGSVGElement).getScreenCTM()
        : null;
    const toUser = (point: { x: number; y: number }): { x: number; y: number } =>
      ctm && ctm.a && ctm.d
        ? { x: (point.x - ctm.e) / ctm.a, y: (point.y - ctm.f) / ctm.d }
        : point;

    const variables: VariableNode[] = [];
    const objects: ObjectNode[] = [];

    const addVariable = (name: string, box: Box, targetText: string) => {
      if (!VARIABLE.test(name) || box.width <= 0 || box.height <= 0) return;
      if (variables.some(node => node.name === name)) return;
      const match = /(?:→|指向)\s*对象\s*(\d+)/.exec(targetText);
      variables.push({
        name,
        box,
        declaredTarget: match ? Number(match[1]) : null,
        geometricTarget: null,
      });
    };
    const addObject = (label: string, box: Box, body: string) => {
      const match = OBJECT.exec(label);
      if (!match || GHOST.test(label) || box.width <= 0 || box.height <= 0) return;
      const index = Number(match[1]);
      if (objects.some(node => node.index === index)) return;
      const hits = /hits\s*=\s*(-?\d+(?:\.\d+)?)/.exec(body);
      objects.push({
        index,
        box,
        hits: hits ? Number(hits[1]) : null,
        label,
      });
    };

    // Layout A: SVG groups (rect plus text labels).
    document.querySelectorAll("svg g").forEach(group => {
      const rect = group.querySelector("rect");
      if (!rect || !(rect instanceof SVGGraphicsElement)) return;
      const texts = Array.from(group.querySelectorAll("text"))
        .map(text => (text.textContent ?? "").trim())
        .filter(Boolean);
      if (!texts.length) return;
      const bounds = rect.getBBox();
      const box = { x: bounds.x, y: bounds.y, width: bounds.width, height: bounds.height };
      const label = texts[0];
      const second = texts[1] ?? "";
      if (VARIABLE.test(label)) addVariable(label, box, second);
      else addObject(label, box, second);
    });

    // Layout B: HTML boxes. Pick the deepest label element, then climb to the
    // enclosing node while the label stays the same and no sibling label joins.
    const firstLine = (element: Element): string => {
      const text = ((element as HTMLElement).innerText ?? element.textContent ?? "").trim();
      return text.split(/\r?\n/)[0].trim();
    };
    const isLabel = (line: string): boolean => VARIABLE.test(line) || OBJECT.test(line);
    const candidates = Array.from(
      document.querySelectorAll("div, section, li, span, p")
    );
    for (const element of candidates) {
      if (element.closest("svg, pre, script, style")) continue;
      const line = firstLine(element);
      if (!isLabel(line) || GHOST.test(line)) continue;
      const childSame = Array.from(
        element.querySelectorAll("div, section, li, span, p")
      ).some(child => firstLine(child) === line);
      if (childSame) continue;

      let chosen: Element = element;
      let parent = element.parentElement;
      while (parent && parent !== document.body && parent.tagName !== "HTML") {
        if (firstLine(parent) !== line) break;
        const joined = Array.from(
          parent.querySelectorAll("div, section, li, span, p")
        ).some(
          child =>
            child !== chosen &&
            isLabel(firstLine(child)) &&
            firstLine(child) !== line &&
            !GHOST.test(firstLine(child))
        );
        if (joined) break;
        chosen = parent;
        parent = parent.parentElement;
      }

      const rectangle = chosen.getBoundingClientRect();
      const topLeft = toUser({ x: rectangle.left, y: rectangle.top });
      const bottomRight = toUser({ x: rectangle.right, y: rectangle.bottom });
      const box = {
        x: topLeft.x,
        y: topLeft.y,
        width: bottomRight.x - topLeft.x,
        height: bottomRight.y - topLeft.y,
      };
      const fullText = ((chosen as HTMLElement).innerText ?? chosen.textContent ?? "").trim();
      if (VARIABLE.test(line)) addVariable(line, box, fullText);
      else addObject(line, box, fullText);
    }

    const arrows: Arrow[] = [];
    document.querySelectorAll("line").forEach(line => {
      const x1 = Number(line.getAttribute("x1"));
      const y1 = Number(line.getAttribute("y1"));
      const x2 = Number(line.getAttribute("x2"));
      const y2 = Number(line.getAttribute("y2"));
      if ([x1, y1, x2, y2].every(Number.isFinite)) {
        arrows.push({ x1, y1, x2, y2 });
      }
    });

    const bodyText = (document.body as HTMLElement).innerText ?? document.body.textContent ?? "";
    const executed = /执行完第\s*(\d+)\s*行/.exec(bodyText);
    const step = executed ? Number(executed[1]) : /执行前/.test(bodyText) ? 0 : null;

    return {
      step,
      text: bodyText,
      variables,
      objects,
      arrows,
    };
  });
}

/** Derive which object each variable points at from the arrows, not the text. */
function assignGeometry(snapshot: Snapshot): void {
  for (const variable of snapshot.variables) {
    const edge = {
      x: variable.box.x + variable.box.width,
      y: variable.box.y + variable.box.height / 2,
    };
    let start: { arrow: Arrow; distance: number } | null = null;
    for (const arrow of snapshot.arrows) {
      const distance = Math.hypot(arrow.x1 - edge.x, arrow.y1 - edge.y);
      if (!start || distance < start.distance) start = { arrow, distance };
    }
    variable.geometricTarget = null;
    if (!start || start.distance > ARROW_START_TOLERANCE) continue;

    let target: { object: ObjectNode; distance: number } | null = null;
    for (const object of snapshot.objects) {
      const distance = distanceToBox(object.box, { x: start.arrow.x2, y: start.arrow.y2 });
      if (!target || distance < target.distance) target = { object, distance };
    }
    if (target && target.distance <= ARROW_TARGET_TOLERANCE) {
      variable.geometricTarget = target.object.index;
    }
  }
}

function canonicalShapes(snapshot: Snapshot): SvgShape[] {
  const shapes: SvgShape[] = [];
  const variable = (name: string) => snapshot.variables.find(node => node.name === name);
  const object = (index: number) => snapshot.objects.find(node => node.index === index);

  const b = variable("b");
  if (b) {
    shapes.push({ id: "node-b", kind: "node", ...b.box });
  }
  const newObject = object(2);
  if (newObject) {
    shapes.push({ id: "node-new-object", kind: "node", ...newObject.box });
  }
  if (b) {
    const edge = { x: b.box.x + b.box.width, y: b.box.y + b.box.height / 2 };
    let best: { arrow: Arrow; distance: number } | null = null;
    for (const arrow of snapshot.arrows) {
      const distance = Math.hypot(arrow.x1 - edge.x, arrow.y1 - edge.y);
      if (!best || distance < best.distance) best = { arrow, distance };
    }
    if (best && best.distance <= ARROW_START_TOLERANCE) {
      shapes.push({
        id: "arrow-b",
        kind: "arrow",
        x: 0,
        y: 0,
        width: 0,
        height: 0,
        from: { x: best.arrow.x1, y: best.arrow.y1 },
        to: { x: best.arrow.x2, y: best.arrow.y2 },
        fromNode: "node-b",
        toNode: b.geometricTarget ? `node-object-${b.geometricTarget}` : undefined,
      });
    }
  }
  return shapes;
}

function phaseOf(snapshot: Snapshot): Phase {
  assignGeometry(snapshot);
  const variable = (name: string) => snapshot.variables.find(node => node.name === name);
  const declared: Record<string, number> = {};
  const observed: Record<string, number> = {};
  for (const [key, name] of [["objectOfA", "a"], ["objectOfB", "b"]] as const) {
    const node = variable(name);
    if (node?.declaredTarget != null) declared[key] = node.declaredTarget;
    if (node?.geometricTarget != null) observed[key] = node.geometricTarget;
  }
  return {
    text: snapshot.text,
    declared,
    observed,
    svg: canonicalShapes(snapshot),
  };
}

async function stepOf(page: Page): Promise<number | null> {
  return (await readSnapshot(page)).step;
}

async function driveTo(page: Page, target: number): Promise<Snapshot | null> {
  const next = page.getByRole("button", { name: "下一步" }).first();
  for (let attempt = 0; attempt < 10; attempt++) {
    const snapshot = await readSnapshot(page);
    if (snapshot.step === target) return snapshot;
    if (snapshot.step === null || snapshot.step > target) return null;
    if ((await next.count()) === 0 || (await next.isDisabled().catch(() => true))) {
      return null;
    }
    await next.click();
    await page.waitForTimeout(25);
  }
  return null;
}

/**
 * Replay a saved J01-style document: advance to the shared and re-pointed
 * steps, then read object identity from the arrows drawn at each step.
 */
export async function observeJ01(
  page: Page,
  errors: ErrorCapture,
  html: string
): Promise<Observation> {
  await page.setContent(html, { waitUntil: "load" });
  const phases: Record<string, Phase> = {};

  const shared = await driveTo(page, 2);
  if (shared) phases.shared = phaseOf(shared);
  const reassigned = await driveTo(page, 5);
  if (reassigned) phases.reassigned = phaseOf(reassigned);

  const basis = await capture(page);
  return {
    phases,
    consoleErrors: errors.consoleErrors,
    pageErrors: errors.pageErrors,
    fontSizes: basis.fontSizes,
    controlSizes: basis.controlSizes,
    horizontalOverflow: basis.horizontalOverflow,
  };
}

function canvasSignature(evidence: Awaited<ReturnType<typeof capture>>): string | null {
  const pixels = evidence.canvases.map(canvas => canvas.pixels).find(value => value !== null);
  return pixels ? JSON.stringify(pixels) : null;
}

/**
 * Replay a saved Canvas animation: use the visible play/pause controls and the
 * canvas pixels, so the measurement does not depend on the page's own text.
 */
export async function observeSpring(
  page: Page,
  errors: ErrorCapture,
  html: string
): Promise<{ observation: Observation; behavior: GenericBehavior }> {
  await page.setContent(html, { waitUntil: "load" });
  await page.waitForTimeout(150);

  const play = page.getByRole("button", { name: /播放|开始/ }).first();
  const pause = page.getByRole("button", { name: /暂停|停止/ }).first();
  const initial = canvasSignature(await capture(page));

  let motion: GenericBehavior["motion"] = "indeterminate";
  let pauseStatus: GenericBehavior["pause"] = "indeterminate";
  const details: string[] = [];

  if (initial && (await play.count()) > 0) {
    await play.click();
    await page.waitForTimeout(350);
    const moving = canvasSignature(await capture(page));
    if (moving) motion = moving === initial ? "fail" : "pass";
    details.push(`播放后画布${moving === initial ? "没有变化" : "发生变化"}`);
  } else {
    details.push("找不到画布或播放按钮");
  }

  if ((await pause.count()) > 0) {
    await pause.click();
    await page.waitForTimeout(120);
    const first = canvasSignature(await capture(page));
    await page.waitForTimeout(250);
    const second = canvasSignature(await capture(page));
    if (first && second) pauseStatus = first === second ? "pass" : "fail";
    details.push(`暂停后画布${first === second ? "保持不变" : "仍在变化"}`);
  } else {
    details.push("找不到暂停按钮");
  }

  const basis = await capture(page);
  return {
    observation: {
      phases: {},
      consoleErrors: errors.consoleErrors,
      pageErrors: errors.pageErrors,
      fontSizes: basis.fontSizes,
      controlSizes: basis.controlSizes,
      horizontalOverflow: basis.horizontalOverflow,
    },
    behavior: { motion, pause: pauseStatus, detail: details.join("；") },
  };
}

/** Generic observation for a saved document with no matching frozen task. */
export async function observeGeneric(
  page: Page,
  errors: ErrorCapture,
  html: string
): Promise<Observation> {
  await page.setContent(html, { waitUntil: "load" });
  await page.waitForTimeout(120);
  const basis = await capture(page);
  return {
    phases: {},
    consoleErrors: errors.consoleErrors,
    pageErrors: errors.pageErrors,
    fontSizes: basis.fontSizes,
    controlSizes: basis.controlSizes,
    horizontalOverflow: basis.horizontalOverflow,
  };
}

/** Exposed for the locator unit test: current step label, or null if unreadable. */
export const readStep = stepOf;
