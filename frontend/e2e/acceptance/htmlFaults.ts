/**
 * Twenty-four known defects injected into the real reference HTML.
 *
 * The observation-level catalogue measures the judge. These measure the whole
 * chain: a page is mutated, the observer measures it, and the judge must report
 * the defect on the named check. Twenty-four is the same count as the frozen
 * catalogue: eight runtime, eight state and eight visual.
 */
import type { Layer } from "../../src/acceptance/model";

import * as fixtures from "./fixtures";

export type HtmlFault = {
  id: string;
  taskId: "J01" | "M01" | "P01" | "M02" | "A02";
  layer: Extract<Layer, "runtime" | "state" | "geometry" | "usability">;
  checkId: string;
  description: string;
  html: string;
};

function inject(html: string, code: string): string {
  return html.replace("</body>", `<script>${code}</script></body>`);
}

function withFont(html: string, size: number): string {
  return html.replace("font: 16px", `font: ${size}px`);
}

function withOverflow(html: string): string {
  return html.replace("</body>", `<div style="width:2000px">溢出内容</div></body>`);
}

const J01_DECLARED = '{"objectOfA":1,"objectOfB":2}';

function j01Declared(values: { objectOfA: number; objectOfB: number }): string {
  return fixtures.J01_CORRECT.replace(
    J01_DECLARED,
    JSON.stringify({ objectOfA: values.objectOfA, objectOfB: values.objectOfB })
  );
}

export const HTML_FAULTS: HtmlFault[] = [
  // runtime: eight
  {
    id: "HR01",
    taskId: "J01",
    layer: "runtime",
    checkId: "runtime",
    description: "初始化抛错",
    html: inject(fixtures.J01_CORRECT, 'throw new Error("init failed");'),
  },
  {
    id: "HR02",
    taskId: "J01",
    layer: "runtime",
    checkId: "runtime",
    description: "点击处理里打印错误",
    html: inject(fixtures.J01_CORRECT, 'console.error("handler failed");'),
  },
  {
    id: "HR03",
    taskId: "J01",
    layer: "runtime",
    checkId: "runtime",
    description: "未处理的 Promise 拒绝",
    html: inject(fixtures.J01_CORRECT, 'Promise.reject(new Error("async failed"));'),
  },
  {
    id: "HR04",
    taskId: "M01",
    layer: "runtime",
    checkId: "runtime",
    description: "绘制函数抛错",
    html: inject(fixtures.M01_CANVAS, 'throw new Error("draw failed");'),
  },
  {
    id: "HR05",
    taskId: "M01",
    layer: "runtime",
    checkId: "runtime",
    description: "输入监听打印错误",
    html: inject(fixtures.M01_CANVAS, 'console.error("input failed");'),
  },
  {
    id: "HR06",
    taskId: "P01",
    layer: "runtime",
    checkId: "runtime",
    description: "动画首帧抛错",
    html: inject(fixtures.P01_ANIMATED, 'throw new Error("frame failed");'),
  },
  {
    id: "HR07",
    taskId: "P01",
    layer: "runtime",
    checkId: "runtime",
    description: "暂停回调打印错误",
    html: inject(fixtures.P01_ANIMATED, 'console.error("pause failed");'),
  },
  {
    id: "HR08",
    taskId: "P01",
    layer: "runtime",
    checkId: "runtime",
    description: "未处理的 Promise 拒绝",
    html: inject(fixtures.P01_ANIMATED, 'Promise.reject(new Error("loop failed"));'),
  },

  // state: eight (the page shows a wrong or missing value)
  {
    id: "HS01",
    taskId: "J01",
    layer: "state",
    checkId: "reassigned-objects",
    description: "重新指向后仍写同一个对象",
    html: j01Declared({ objectOfA: 1, objectOfB: 1 }),
  },
  {
    id: "HS02",
    taskId: "J01",
    layer: "state",
    checkId: "reassigned-objects",
    description: "把 a 的对象数写成 2",
    html: j01Declared({ objectOfA: 2, objectOfB: 2 }),
  },
  {
    id: "HS03",
    taskId: "J01",
    layer: "state",
    checkId: "reassigned-objects",
    description: "两个计数都写成 0",
    html: j01Declared({ objectOfA: 0, objectOfB: 0 }),
  },
  {
    id: "HS04",
    taskId: "J01",
    layer: "state",
    checkId: "reassigned-objects",
    description: "计数写反",
    html: j01Declared({ objectOfA: 2, objectOfB: 1 }),
  },
  {
    id: "HS05",
    taskId: "M01",
    layer: "state",
    checkId: "value-at-3",
    description: "函数值少算常数项",
    html: fixtures.M01_CANVAS.replace("const y = 2 * x + 1;", "const y = 2 * x;"),
  },
  {
    id: "HS06",
    taskId: "M01",
    layer: "state",
    checkId: "value-at-3",
    description: "函数值多加一",
    html: fixtures.M01_CANVAS.replace("const y = 2 * x + 1;", "const y = 2 * x + 2;"),
  },
  {
    id: "HS07",
    taskId: "M01",
    layer: "state",
    checkId: "value-at-minus-1",
    description: "斜率为负",
    html: fixtures.M01_CANVAS.replace("const y = 2 * x + 1;", "const y = -2 * x + 1;"),
  },
  {
    id: "HS08",
    taskId: "M01",
    layer: "state",
    checkId: "value-at-minus-1",
    description: "函数值恒为 0",
    html: fixtures.M01_CANVAS.replace("const y = 2 * x + 1;", "const y = 0;"),
  },

  // visual and usability: eight
  {
    id: "HV01",
    taskId: "J01",
    layer: "geometry",
    checkId: "arrow-points-at-its-object",
    description: "箭头终点指向空白",
    html: fixtures.J01_CORRECT.replace('x2="260" y2="50"', 'x2="180" y2="205"'),
  },
  {
    id: "HV02",
    taskId: "J01",
    layer: "geometry",
    checkId: "arrow-points-at-its-object",
    description: "箭头指向另一个对象",
    html: fixtures.J01_CORRECT.replace('x2="260" y2="50"', 'x2="60" y2="40"'),
  },
  {
    id: "HV03",
    taskId: "M01",
    layer: "geometry",
    checkId: "chart-follows-x",
    description: "数值变了但画布不重绘",
    html: fixtures.M01_CANVAS.replace("input.addEventListener('input', draw);", "input.addEventListener('input', () => {});"),
  },
  {
    id: "HV04",
    taskId: "P01",
    layer: "geometry",
    checkId: "paused",
    description: "暂停按钮无效",
    html: fixtures.P01_ANIMATED.replace("running = false;", "running = true;"),
  },
  {
    id: "HV05",
    taskId: "M02",
    layer: "usability",
    checkId: "readable",
    description: "坐标文字缩到 12px",
    html: withFont(fixtures.TINY_FONT, 12),
  },
  {
    id: "HV06",
    taskId: "M02",
    layer: "usability",
    checkId: "readable",
    description: "坐标文字缩到 11px",
    html: withFont(fixtures.TINY_FONT, 11),
  },
  {
    id: "HV07",
    taskId: "A02",
    layer: "usability",
    checkId: "no-overflow",
    description: "画布页面横向溢出",
    html: withOverflow(fixtures.M01_CANVAS),
  },
  {
    id: "HV08",
    taskId: "A02",
    layer: "usability",
    checkId: "no-overflow",
    description: "动画页面横向溢出",
    html: withOverflow(fixtures.P01_ANIMATED),
  },
];
