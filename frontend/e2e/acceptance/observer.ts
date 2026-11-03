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
  observed: Record<string, number>;
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
  /** Centre of the dominant saturated colour, in canvas pixels. */
  marker: { x: number; y: number; radius: number } | null;
  /** Columns of tall vertical strokes, used as an amplitude reference. */
  verticalMarks: number[];
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

export async function capture(page: Page, rootSelector = "body"): Promise<RawEvidence> {
  return page.evaluate((selector: string) => {
    const root = document.querySelector(selector) ?? document.body;
    const declaredNode = root.matches("[data-acceptance-declared]")
      ? root
      : root.querySelector("[data-acceptance-declared]");
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
    root.querySelectorAll("rect[data-node]").forEach(element => {
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
    root.querySelectorAll("line[data-arrow]").forEach(element => {
      if (element.hasAttribute("hidden") || getComputedStyle(element).display === "none") return;
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
      root.querySelectorAll("p, span, div, button, label, li, td, th, h1, h2, h3")
    )
      .filter(visible)
      .map(element => Number.parseFloat(getComputedStyle(element).fontSize))
      .filter(value => Number.isFinite(value));
    const controlSizes = Array.from(
      root.querySelectorAll("button, input, select, textarea")
    )
      .filter(visible)
      .map(element => {
        const rect = element.getBoundingClientRect();
        return Math.min(rect.width, rect.height);
      })
      .filter(value => Number.isFinite(value));

    const observed: Record<string, number> = {};
    root.querySelectorAll("[data-value]").forEach(element => {
      const key = element.getAttribute("data-value") ?? "";
      const value = Number.parseFloat((element.textContent ?? "").trim());
      if (key && Number.isFinite(value)) observed[key] = value;
    });

    return {
      text: (root as HTMLElement).innerText ?? root.textContent ?? "",
      declared,
      observed,
      svg,
      canvases: Array.from(root.querySelectorAll("canvas")).map((canvas, index) => {
        const id = canvas.getAttribute("data-canvas") ?? `canvas-${index}`;
        try {
          const context = canvas.getContext("2d");
          if (!context) {
            return {
              id,
              width: canvas.width,
              height: canvas.height,
              pixels: null,
              marker: null,
              verticalMarks: [],
              error: "no-2d-context",
            };
          }
          const data = context.getImageData(0, 0, canvas.width, canvas.height).data;
          // A full-pixel hash: an 8x8 sample can alias when a moving element
          // never crosses a sample point, which would hide real motion.
          let hash = 2166136261;
          for (let offset = 0; offset < data.length; offset += 4) {
            hash ^= data[offset] + 3 * data[offset + 1] + 7 * data[offset + 2] + 11 * data[offset + 3];
            hash = Math.imul(hash, 16777619);
          }
          const pixels = [hash >>> 0, canvas.width, canvas.height];

          // The drawn object is the dominant saturated colour. Counting colour
          // frequency is enough because a filled marker has far more pixels
          // than labels or strokes of the same hue.
          const buckets = new Map<number, number>();
          for (let offset = 0; offset < data.length; offset += 4) {
            if (data[offset + 3] < 128) continue;
            const r = data[offset];
            const g = data[offset + 1];
            const b = data[offset + 2];
            const high = Math.max(r, g, b);
            const low = Math.min(r, g, b);
            if (high < 70 || high - low < 45) continue;
            const key = ((r >> 3) << 10) | ((g >> 3) << 5) | (b >> 3);
            buckets.set(key, (buckets.get(key) ?? 0) + 1);
          }
          let dominant: number | null = null;
          let dominantCount = 0;
          buckets.forEach((count, key) => {
            if (count > dominantCount) {
              dominant = key;
              dominantCount = count;
            }
          });
          let marker: { x: number; y: number; radius: number } | null = null;
          if (dominant !== null && dominantCount >= 24) {
            const dr = ((dominant >> 10) & 31) << 3;
            const dg = ((dominant >> 5) & 31) << 3;
            const db = (dominant & 31) << 3;
            let sumX = 0;
            let sumY = 0;
            let matched = 0;
            for (let offset = 0; offset < data.length; offset += 4) {
              const diffR = data[offset] - dr;
              const diffG = data[offset + 1] - dg;
              const diffB = data[offset + 2] - db;
              if (diffR * diffR + diffG * diffG + diffB * diffB > 3600) continue;
              const pixel = offset / 4;
              sumX += pixel % canvas.width;
              sumY += Math.floor(pixel / canvas.width);
              matched++;
            }
            if (matched) {
              marker = {
                x: sumX / matched,
                y: sumY / matched,
                radius: Math.sqrt(matched / Math.PI),
              };
            }
          }

          // Tall vertical strokes are the drawn amplitude reference. The ball
          // itself is excluded by its measured radius, and short zig-zag
          // strokes stay below the run threshold.
          const verticalMarks: number[] = [];
          const backgroundR = data[0];
          const backgroundG = data[1];
          const backgroundB = data[2];
          const minRun = Math.max(8, Math.round(canvas.height * 0.2));
          const yStart = Math.max(0, Math.floor(canvas.height * 0.1));
          const yEnd = Math.min(canvas.height - 1, Math.ceil(canvas.height * 0.9));
          for (let x = 0; x < canvas.width; x++) {
            if (marker && Math.abs(x - marker.x) <= marker.radius + 2) continue;
            let run = 0;
            let longest = 0;
            for (let y = yStart; y <= yEnd; y++) {
              const offset = (y * canvas.width + x) * 4;
              const differs =
                Math.abs(data[offset] - backgroundR) +
                  Math.abs(data[offset + 1] - backgroundG) +
                  Math.abs(data[offset + 2] - backgroundB) >
                36;
              if (differs) {
                run++;
                if (run > longest) longest = run;
              } else {
                run = 0;
              }
            }
            if (longest >= minRun) verticalMarks.push(x);
          }
          const merged: number[] = [];
          for (const x of verticalMarks) {
            if (!merged.length || x - merged[merged.length - 1] > 2) merged.push(x);
            else merged[merged.length - 1] = (merged[merged.length - 1] + x) / 2;
          }

          return {
            id,
            width: canvas.width,
            height: canvas.height,
            pixels,
            marker,
            verticalMarks: merged,
            error: null,
          };
        } catch (error) {
          // A tainted canvas cannot be read; that is missing evidence, not a pass.
          return {
            id,
            width: canvas.width,
            height: canvas.height,
            pixels: null,
            marker: null,
            verticalMarks: [],
            error: String(error).slice(0, 200),
          };
        }
      }),
      fontSizes,
      controlSizes,
      horizontalOverflow: document.documentElement.scrollWidth > window.innerWidth + 1,
    };
  }, rootSelector) as Promise<RawEvidence>;
}
