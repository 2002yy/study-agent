/**
 * Twenty-four known defects injected into the real reference HTML, two per task
 * across the frozen twelve. The observation-level catalogue measures the judge;
 * these measure the whole chain: mutate a page, measure it, and require the
 * judge to report the defect on the named check.
 */
import type { Layer } from "../../src/acceptance/model";

import * as fixtures from "./fixtures";

export type HtmlFault = {
  id: string;
  taskId:
    | "J01"
    | "J02"
    | "A01"
    | "A02"
    | "D01"
    | "D02"
    | "C01"
    | "M01"
    | "M02"
    | "P01"
    | "S01"
    | "N01";
  layer: Extract<Layer, "runtime" | "state" | "geometry" | "usability">;
  checkId: string;
  description: string;
  html: string;
  phases?: Array<{ name: string; selector: string }>;
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

const SINGLE: Record<string, Array<{ name: string; selector: string }>> = {
  J02: [{ name: "call", selector: '[data-phase="call"]' }],
  A01: [{ name: "found", selector: '[data-phase="found"]' }],
  A02: [{ name: "result", selector: '[data-phase="result"]' }],
  C01: [{ name: "running", selector: '[data-phase="running"]' }],
  S01: [{ name: "metrics", selector: '[data-phase="metrics"]' }],
  N01: [{ name: "complete", selector: '[data-phase="complete"]' }],
  D01: [
    { name: "committed", selector: '[data-phase="committed"]' },
    { name: "rolled_back", selector: '[data-phase="rolled_back"]' },
  ],
  D02: [
    { name: "interleaved", selector: '[data-phase="interleaved"]' },
    { name: "serialized", selector: '[data-phase="serialized"]' },
  ],
  M02: [
    { name: "base", selector: '[data-phase="base"]' },
    { name: "adjusted", selector: '[data-phase="adjusted"]' },
  ],
};

export const HTML_FAULTS: HtmlFault[] = [
  // runtime: eight, spread across tasks
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
    taskId: "A01",
    layer: "runtime",
    checkId: "runtime",
    description: "查找脚本报错",
    html: inject(fixtures.A01_PAGE, 'console.error("search failed");'),
  },
  {
    id: "HR03",
    taskId: "D01",
    layer: "runtime",
    checkId: "runtime",
    description: "回滚脚本抛错",
    html: inject(fixtures.D01_PAGES, 'throw new Error("rollback failed");'),
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
    taskId: "S01",
    layer: "runtime",
    checkId: "runtime",
    description: "矩阵计算报错",
    html: inject(fixtures.S01_PAGE, 'console.error("matrix failed");'),
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
    taskId: "N01",
    layer: "runtime",
    checkId: "runtime",
    description: "时序推进抛错",
    html: inject(fixtures.N01_PAGE, 'throw new Error("handshake failed");'),
  },
  {
    id: "HR08",
    taskId: "C01",
    layer: "runtime",
    checkId: "runtime",
    description: "许可释放回调报错",
    html: inject(fixtures.C01_PAGE, 'console.error("release failed");'),
  },

  // state: eight, one per remaining task
  {
    id: "HS01",
    taskId: "J02",
    layer: "state",
    checkId: "dynamic-dispatch",
    description: "声明没有发生动态分派",
    html: fixtures.J02_PAGE.replace('"dispatchedImplementations":1', '"dispatchedImplementations":0'),
    phases: SINGLE.J02,
  },
  {
    id: "HS02",
    taskId: "J01",
    layer: "state",
    checkId: "reassigned-objects",
    description: "重新指向后仍写同一个对象",
    html: fixtures.J01_CORRECT.replace('"objectOfB":2', '"objectOfB":1'),
  },
  {
    id: "HS03",
    taskId: "A02",
    layer: "state",
    checkId: "shortest-distance",
    description: "把 A-C-D 当成最短路（8）",
    html: fixtures.A02_PAGE.replace('"distance":6', '"distance":8'),
    phases: SINGLE.A02,
  },
  {
    id: "HS04",
    taskId: "A01",
    layer: "state",
    checkId: "checked-indexes",
    description: "从索引 0 开始线性扫描",
    html: fixtures.A01_PAGE.replace('"firstChecked":2', '"firstChecked":0'),
    phases: SINGLE.A01,
  },
  {
    id: "HS05",
    taskId: "D01",
    layer: "state",
    checkId: "committed",
    description: "转账后总额变成 130",
    html: fixtures.D01_PAGES.replace('"A":70', '"A":60'),
    phases: SINGLE.D01,
  },
  {
    id: "HS06",
    taskId: "D02",
    layer: "state",
    checkId: "lost-update",
    description: "把丢失更新显示成 10",
    html: fixtures.D02_PAGES.replace('"stock":9', '"stock":10'),
    phases: SINGLE.D02,
  },
  {
    id: "HS07",
    taskId: "C01",
    layer: "state",
    checkId: "permits-hold",
    description: "三个任务同时运行",
    html: fixtures.C01_PAGE.replace('"running":2', '"running":3'),
    phases: SINGLE.C01,
  },
  {
    id: "HS08",
    taskId: "M02",
    layer: "state",
    checkId: "zeros-and-vertex",
    description: "顶点写成 -3",
    html: fixtures.M02_PAGES.replace('"vertexY":-4', '"vertexY":-3'),
    phases: SINGLE.M02,
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
    taskId: "N01",
    layer: "geometry",
    checkId: "ack-direction",
    description: "ACK 箭头指向反方向",
    html: fixtures.N01_PAGE.replace('x2="310" y2="20"', 'x2="10" y2="200"'),
    phases: SINGLE.N01,
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
    html: withFont(fixtures.M02_PAGES, 12),
    phases: SINGLE.M02,
  },
  {
    id: "HV06",
    taskId: "S01",
    layer: "usability",
    checkId: "readable",
    description: "矩阵标签缩到 11px",
    html: withFont(fixtures.S01_PAGE, 11),
    phases: SINGLE.S01,
  },
  {
    id: "HV07",
    taskId: "A02",
    layer: "usability",
    checkId: "no-overflow",
    description: "路径页面横向溢出",
    html: withOverflow(fixtures.A02_PAGE),
    phases: SINGLE.A02,
  },
  {
    id: "HV08",
    taskId: "D02",
    layer: "usability",
    checkId: "no-overflow",
    description: "事务时间线横向溢出",
    html: withOverflow(fixtures.D02_PAGES),
    phases: SINGLE.D02,
  },
];
