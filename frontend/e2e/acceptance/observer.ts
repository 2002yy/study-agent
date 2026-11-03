/**
 * Real-page evidence collector (M4-C2a).
 *
 * The observer only measures what the page really did: runtime errors, text,
 * controls, font sizes, overflow, and SVG geometry. It never decides whether
 * the page is correct; that stays in `src/acceptance/model.ts`.
 *
 * Numbers the page prints are collected as `declared`. They are not evidence
 * on their own; task adapters derive `observed` values from geometry.
 */
import type { Page } from "@playwright/test";

import type { SvgShape } from "../../src/acceptance/model";

export type ErrorCapture = { consoleErrors: string[]; pageErrors: string[] };

export type RawEvidence = {
  text: string;
  declared: Record<string, number>;
  svg: SvgShape[];
  canvases: CanvasCapture[];
  fontSizes: number[];
  controlSizes: number[];
  horizontalOverflow: boolean;
};

export type CanvasCapture = {
  id: string;
  width: number;
  height: number;
  /** Sampled RGBA grid, or null when the canvas cannot be read. */
  pixels: number[] | null;
  error: string | null;
};

/** Listeners must be attached before navigation, otherwise early errors are lost. */
export function watchErrors(page: Page): ErrorCapture {
  const capture: ErrorCapture = { consoleErrors: [], pageErrors: [] };
  page.on("console", message => {
    if (message.type() === "error") capture.consoleErrors.push(message.text().slice(0, 500));
  });
  page.on("pageerror", error => {
    capture.pageErrors.push(String(error.message ?? error).slice(0, 500));
  });
  return capture;
}

export async function capture(page: Page): Promise<RawEvidence> {
  return page.evaluate(() => {
    const declaredNode = document.querySelector("[data-acceptance-declared]");
    let declared: Record<string, number> = {};
    try {
      const raw =
        declaredNode?.getAttribute("data-acceptance-declared") ??
        declaredNode?.textContent ??
        "{}";
      const parsed = JSON.parse(raw) as Record<string, unknown>;
      declared = Object.fromEntries(
        Object.entries(parsed).filter(([, value]) => typeof value === "number")
      ) as Record<string, number>;
    } catch {
      declared = {};
    }

    const svg: SvgShape[] = [];
    document.querySelectorAll("rect[data-node]").forEach(element => {
      const id = element.getAttribute("data-node") ?? "";
      if (!id || !(element instanceof SVGGraphicsElement)) return;
      const box = element.getBBox();
      svg.push({
        id,
        kind: "node",
        x: box.x,
        y: box.y,
        width: box.width,
        height: box.height,
      });
    });
    document.querySelectorAll("line[data-arrow]").forEach(element => {
      const id = element.getAttribute("data-arrow") ?? "";
      if (!id) return;
      const x1 = Number(element.getAttribute("x1"));
      const y1 = Number(element.getAttribute("y1"));
      const x2 = Number(element.getAttribute("x2"));
      const y2 = Number(element.getAttribute("y2"));
      svg.push({
        id,
        kind: "arrow",
        x: 0,
        y: 0,
        width: 0,
        height: 0,
        from: { x: x1, y: y1 },
        to: { x: x2, y: y2 },
        fromNode: element.getAttribute("data-from") ?? undefined,
        toNode: element.getAttribute("data-to") ?? undefined,
      });
    });

    const visible = (element: Element): boolean => {
      const rect = element.getBoundingClientRect();
      const style = getComputedStyle(element);
      return rect.width > 0 && rect.height > 0 && style.visibility !== "hidden" && style.display !== "none";
    };
    const fontSizes = Array.from(
      document.querySelectorAll("p, span, div, button, label, li, td, th, h1, h2, h3")
    )
      .filter(visible)
      .map(element => Number.parseFloat(getComputedStyle(element).fontSize))
      .filter(value => Number.isFinite(value));
    const controlSizes = Array.from(
      document.querySelectorAll("button, input, select, textarea")
    )
      .filter(visible)
      .map(element => {
        const rect = element.getBoundingClientRect();
        return Math.min(rect.width, rect.height);
      })
      .filter(value => Number.isFinite(value));

    return {
      text: document.body.innerText,
      declared,
      svg,
      canvases: Array.from(document.querySelectorAll("canvas")).map((canvas, index) => {
        const id = canvas.getAttribute("data-canvas") ?? `canvas-${index}`;
        try {
          const context = canvas.getContext("2d");
          if (!context) {
            return { id, width: canvas.width, height: canvas.height, pixels: null, error: "no-2d-context" };
          }
          const data = context.getImageData(0, 0, canvas.width, canvas.height).data;
          const pixels: number[] = [];
          const grid = 8;
          for (let row = 0; row < grid; row++) {
            for (let column = 0; column < grid; column++) {
              const x = Math.min(canvas.width - 1, Math.floor(((column + 0.5) * canvas.width) / grid));
              const y = Math.min(canvas.height - 1, Math.floor(((row + 0.5) * canvas.height) / grid));
              const offset = (y * canvas.width + x) * 4;
              pixels.push(data[offset], data[offset + 1], data[offset + 2], data[offset + 3]);
            }
          }
          return { id, width: canvas.width, height: canvas.height, pixels, error: null };
        } catch (error) {
          // A tainted canvas cannot be read; that is missing evidence, not a pass.
          return {
            id,
            width: canvas.width,
            height: canvas.height,
            pixels: null,
            error: String(error).slice(0, 200),
          };
        }
      }),
      fontSizes,
      controlSizes,
      horizontalOverflow: document.documentElement.scrollWidth > window.innerWidth + 1,
    };
  }) as Promise<RawEvidence>;
}
