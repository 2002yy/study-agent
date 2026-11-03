/**
 * M4-C frozen acceptance model.
 *
 * The twelve tasks below are fixed. Their checks describe what a correct
 * interface must show, not how it must be built: a model is free to choose DOM,
 * SVG or Canvas. Every check is judged from an observation snapshot, and a
 * check that lacks evidence returns `indeterminate` rather than passing.
 */

export type Layer = "runtime" | "state" | "geometry" | "usability";
export type Status = "pass" | "fail" | "indeterminate";

export type SvgShape = {
  id: string;
  kind: "node" | "arrow" | "label";
  x: number;
  y: number;
  width: number;
  height: number;
  text?: string;
  from?: { x: number; y: number };
  to?: { x: number; y: number };
};

export type Phase = {
  text: string;
  /** What the page displays or reports; not independent evidence on its own. */
  declared: Record<string, number>;
  /** What the checker measured from controls, geometry or pixels. */
  observed: Record<string, number>;
  svg?: SvgShape[];
  canvas?: { pixels: number[][]; marker?: { x: number; y: number } };
};

export type Observation = {
  phases: Record<string, Phase>;
  consoleErrors: string[];
  pageErrors: string[];
  fontSizes: number[];
  controlSizes: number[];
  horizontalOverflow: boolean;
};

export type Check =
  | { kind: "runtime-clean"; id: string }
  | { kind: "text-includes"; id: string; phase: string; values: string[] }
  | {
      kind: "numbers-equal";
      id: string;
      phase: string;
      source?: "declared" | "observed";
      expected: Record<string, number>;
    }
  | {
      kind: "numbers-approx";
      id: string;
      phase: string;
      source?: "declared" | "observed";
      expected: Record<string, number>;
      tolerance: number;
    }
  | {
      kind: "cross-check";
      id: string;
      phase: string;
      declaredKey: string;
      observedKey: string;
      tolerance: number;
    }
  | {
      kind: "svg-arrow-near";
      id: string;
      phase: string;
      arrowId: string;
      sourceId?: string;
      targetId: string;
      tolerance: number;
    }
  | { kind: "canvas-differs"; id: string; first: string; second: string }
  | { kind: "canvas-same"; id: string; first: string; second: string }
  | { kind: "min-font-size"; id: string; min: number }
  | { kind: "min-control-size"; id: string; min: number }
  | { kind: "no-horizontal-overflow"; id: string };

export type TaskSpec = {
  id: string;
  domain: string;
  prompt: string;
  checks: Check[];
};

export type CheckResult = {
  checkId: string;
  layer: Layer;
  status: Status;
  detail: string;
};

function layerOf(check: Check): Layer {
  if (check.kind === "runtime-clean") return "runtime";
  if (check.kind === "min-font-size" || check.kind === "min-control-size" || check.kind === "no-horizontal-overflow") {
    return "usability";
  }
  if (check.kind === "svg-arrow-near" || check.kind === "canvas-differs" || check.kind === "canvas-same") {
    return "geometry";
  }
  return "state";
}

function finitePoint(point: { x: number; y: number } | undefined): point is { x: number; y: number } {
  return !!point && Number.isFinite(point.x) && Number.isFinite(point.y);
}

function finiteShape(shape: SvgShape | undefined): shape is SvgShape {
  return (
    !!shape &&
    Number.isFinite(shape.x) &&
    Number.isFinite(shape.y) &&
    Number.isFinite(shape.width) &&
    Number.isFinite(shape.height) &&
    shape.width >= 0 &&
    shape.height >= 0
  );
}

function distanceToBox(shape: SvgShape, point: { x: number; y: number }): number | null {
  if (!finiteShape(shape) || !finitePoint(point)) return null;
  const dx = Math.max(shape.x - point.x, 0, point.x - (shape.x + shape.width));
  const dy = Math.max(shape.y - point.y, 0, point.y - (shape.y + shape.height));
  const distance = Math.hypot(dx, dy);
  return Number.isFinite(distance) ? distance : null;
}

function readNumber(
  phase: Phase,
  source: "declared" | "observed",
  key: string
): { status: "missing" } | { status: "invalid" } | { status: "ok"; value: number } {
  const map = phase[source];
  if (!(key in map)) return { status: "missing" };
  const value = map[key];
  if (typeof value !== "number" || !Number.isFinite(value)) return { status: "invalid" };
  return { status: "ok", value };
}

function judgeOne(check: Check, observation: Observation): CheckResult {
  const base = { checkId: check.id, layer: layerOf(check) };
  if (check.kind === "runtime-clean") {
    const errors = [...observation.consoleErrors, ...observation.pageErrors];
    return errors.length
      ? { ...base, status: "fail", detail: `运行错误：${errors.slice(0, 3).join(" | ")}` }
      : { ...base, status: "pass", detail: "" };
  }
  if (check.kind === "min-font-size") {
    if (!observation.fontSizes.length) return { ...base, status: "indeterminate", detail: "没有读取到字号" };
    const smallest = Math.min(...observation.fontSizes);
    return smallest >= check.min
      ? { ...base, status: "pass", detail: "" }
      : { ...base, status: "fail", detail: `最小字号 ${smallest}px，低于 ${check.min}px` };
  }
  if (check.kind === "min-control-size") {
    if (!observation.controlSizes.length) return { ...base, status: "indeterminate", detail: "没有读取到控件尺寸" };
    const smallest = Math.min(...observation.controlSizes);
    return smallest >= check.min
      ? { ...base, status: "pass", detail: "" }
      : { ...base, status: "fail", detail: `最小控件 ${smallest}px，低于 ${check.min}px` };
  }
  if (check.kind === "no-horizontal-overflow") {
    return observation.horizontalOverflow
      ? { ...base, status: "fail", detail: "页面出现横向溢出" }
      : { ...base, status: "pass", detail: "" };
  }
  if (check.kind === "canvas-differs" || check.kind === "canvas-same") {
    const first = observation.phases[check.first]?.canvas?.pixels;
    const second = observation.phases[check.second]?.canvas?.pixels;
    if (!first || !second) return { ...base, status: "indeterminate", detail: "缺少画布采样" };
    const identical = JSON.stringify(first) === JSON.stringify(second);
    if (check.kind === "canvas-differs") {
      return identical
        ? { ...base, status: "fail", detail: `${check.first} 与 ${check.second} 的画布完全相同` }
        : { ...base, status: "pass", detail: "" };
    }
    return identical
      ? { ...base, status: "pass", detail: "" }
      : { ...base, status: "fail", detail: `${check.first} 之后画布仍在变化` };
  }

  const phase = observation.phases[check.phase];
  if (!phase) return { ...base, status: "indeterminate", detail: `缺少阶段 ${check.phase}` };

  if (check.kind === "text-includes") {
    const missing = check.values.filter(value => !phase.text.includes(value));
    return missing.length
      ? { ...base, status: "fail", detail: `界面文字缺少：${missing.join("、")}` }
      : { ...base, status: "pass", detail: "" };
  }
  if (check.kind === "numbers-equal") {
    for (const [key, expected] of Object.entries(check.expected)) {
      if (!Number.isFinite(expected)) {
        return { ...base, status: "fail", detail: `规格里的 ${key} 不是有限数` };
      }
      const reading = readNumber(phase, check.source ?? "declared", key);
      if (reading.status === "missing") return { ...base, status: "indeterminate", detail: `没有读取到 ${key}` };
      if (reading.status === "invalid") return { ...base, status: "fail", detail: `${key} 的观测值不是有限数` };
      if (reading.value !== expected) return { ...base, status: "fail", detail: `${key}=${reading.value}，应为 ${expected}` };
    }
    return { ...base, status: "pass", detail: "" };
  }
  if (check.kind === "numbers-approx") {
    for (const [key, expected] of Object.entries(check.expected)) {
      if (!Number.isFinite(expected) || !Number.isFinite(check.tolerance)) {
        return { ...base, status: "fail", detail: `规格里的 ${key} 或容差不是有限数` };
      }
      const reading = readNumber(phase, check.source ?? "declared", key);
      if (reading.status === "missing") return { ...base, status: "indeterminate", detail: `没有读取到 ${key}` };
      if (reading.status === "invalid") return { ...base, status: "fail", detail: `${key} 的观测值不是有限数` };
      if (Math.abs(reading.value - expected) > check.tolerance) {
        return { ...base, status: "fail", detail: `${key}=${reading.value}，应为 ${expected}±${check.tolerance}` };
      }
    }
    return { ...base, status: "pass", detail: "" };
  }
  if (check.kind === "cross-check") {
    const declared = readNumber(phase, "declared", check.declaredKey);
    if (declared.status === "missing") return { ...base, status: "indeterminate", detail: `页面没有给出 ${check.declaredKey}` };
    if (declared.status === "invalid") return { ...base, status: "fail", detail: `${check.declaredKey} 的声明值不是有限数` };
    const observed = readNumber(phase, "observed", check.observedKey);
    if (observed.status === "missing") return { ...base, status: "indeterminate", detail: `没有独立观测到 ${check.observedKey}` };
    if (observed.status === "invalid") return { ...base, status: "fail", detail: `${check.observedKey} 的观测值不是有限数` };
    if (Math.abs(declared.value - observed.value) > check.tolerance) {
      return {
        ...base,
        status: "fail",
        detail: `声明 ${check.declaredKey}=${declared.value} 与观测 ${check.observedKey}=${observed.value} 不一致`,
      };
    }
    return { ...base, status: "pass", detail: "" };
  }

  // svg-arrow-near
  const shapes = phase.svg ?? [];
  const arrow = shapes.find(shape => shape.id === check.arrowId);
  const target = shapes.find(shape => shape.id === check.targetId);
  if (!arrow || !target) return { ...base, status: "indeterminate", detail: "缺少箭头或目标对象" };
  if (!finiteShape(arrow) || !finiteShape(target) || !finitePoint(arrow.to)) {
    return { ...base, status: "fail", detail: "箭头或目标对象的坐标不是有限数" };
  }
  const source = check.sourceId ? shapes.find(shape => shape.id === check.sourceId) : undefined;
  if (check.sourceId && (!source || !arrow.from)) return { ...base, status: "indeterminate", detail: "缺少箭头起点或来源对象" };
  if (source && !finiteShape(source)) return { ...base, status: "fail", detail: "来源对象坐标不是有限数" };
  const targetDistance = distanceToBox(target, arrow.to);
  if (targetDistance === null) return { ...base, status: "fail", detail: "无法计算箭头端点距离" };
  if (targetDistance > check.tolerance) {
    return { ...base, status: "fail", detail: `箭头终点距目标 ${targetDistance.toFixed(1)}px，超过 ${check.tolerance}px` };
  }
  if (source && arrow.from) {
    if (!finitePoint(arrow.from)) return { ...base, status: "fail", detail: "箭头起点不是有限数" };
    const sourceDistance = distanceToBox(source, arrow.from);
    if (sourceDistance === null) return { ...base, status: "fail", detail: "无法计算箭头起点距离" };
    if (sourceDistance > check.tolerance) {
      return { ...base, status: "fail", detail: `箭头起点距来源 ${sourceDistance.toFixed(1)}px，超过 ${check.tolerance}px` };
    }
  }
  return { ...base, status: "pass", detail: "" };
}

export function judge(spec: TaskSpec, observation: Observation): CheckResult[] {
  return spec.checks.map(check => judgeOne(check, observation));
}

export function summarize(results: CheckResult[]): {
  failed: CheckResult[];
  indeterminate: CheckResult[];
  passed: number;
} {
  return {
    failed: results.filter(result => result.status === "fail"),
    indeterminate: results.filter(result => result.status === "indeterminate"),
    passed: results.filter(result => result.status === "pass").length,
  };
}

export const TASK_SPECS: TaskSpec[] = [
  {
    id: "J01",
    domain: "Java 对象模型",
    prompt: "制作两个引用共享对象的逐步实验：修改共享对象、再重新指向，观察对象数量与箭头。",
    checks: [
      { kind: "runtime-clean", id: "runtime" },
      { kind: "numbers-equal", id: "shared-object", phase: "shared", expected: { objectOfA: 1, objectOfB: 1 } },
      { kind: "numbers-equal", id: "reassigned-objects", phase: "reassigned", expected: { objectOfA: 1, objectOfB: 2 } },
      {
        kind: "svg-arrow-near",
        id: "arrow-points-at-its-object",
        phase: "reassigned",
        arrowId: "arrow-b",
        sourceId: "node-b",
        targetId: "node-new-object",
        tolerance: 12,
      },
    ],
  },
  {
    id: "J02",
    domain: "Java 多态",
    prompt: "制作多态与动态方法分派实验：Animal 引用指向 Dog，调用 sound() 应执行 Dog 的实现。",
    checks: [
      { kind: "runtime-clean", id: "runtime" },
      { kind: "numbers-equal", id: "dynamic-dispatch", phase: "call", expected: { dispatchedImplementations: 1 } },
      { kind: "text-includes", id: "dog-implementation", phase: "call", values: ["Dog", "sound"] },
    ],
  },
  {
    id: "A01",
    domain: "算法：二分查找",
    prompt: "制作二分查找交互演示：数组 [1,3,5,7,9] 查找 7，显示每步检查的索引与区间。",
    checks: [
      { kind: "runtime-clean", id: "runtime" },
      { kind: "text-includes", id: "target", phase: "found", values: ["7"] },
      { kind: "numbers-equal", id: "checked-indexes", phase: "found", expected: { firstChecked: 2, secondChecked: 3 } },
    ],
  },
  {
    id: "A02",
    domain: "算法：Dijkstra",
    prompt: "制作 Dijkstra 演示：A-B=2、A-C=5、B-C=1、C-D=3、B-D=7，求 A 到 D 的最短路径。",
    checks: [
      { kind: "runtime-clean", id: "runtime" },
      { kind: "numbers-equal", id: "shortest-distance", phase: "result", expected: { distance: 6 } },
      { kind: "text-includes", id: "shortest-path", phase: "result", values: ["A", "B", "C", "D"] },
      { kind: "no-horizontal-overflow", id: "no-overflow" },
    ],
  },
  {
    id: "D01",
    domain: "数据库事务",
    prompt: "制作转账事务实验：A=100、B=40，转账 30；中途失败回滚，总额始终 140。",
    checks: [
      { kind: "runtime-clean", id: "runtime" },
      { kind: "numbers-equal", id: "committed", phase: "committed", expected: { A: 70, B: 70 } },
      { kind: "numbers-equal", id: "rolled-back", phase: "rolled_back", expected: { A: 100, B: 40 } },
      { kind: "text-includes", id: "rollback-visible", phase: "rolled_back", values: ["回滚"] },
    ],
  },
  {
    id: "D02",
    domain: "数据库并发",
    prompt: "制作丢失更新实验：两个事务都读到库存 10 各减 1，展示无保护交错得 9 与串行化得 8。",
    checks: [
      { kind: "runtime-clean", id: "runtime" },
      { kind: "numbers-equal", id: "lost-update", phase: "interleaved", expected: { stock: 9 } },
      { kind: "numbers-equal", id: "serialized", phase: "serialized", expected: { stock: 8 } },
      { kind: "no-horizontal-overflow", id: "no-overflow" },
    ],
  },
  {
    id: "C01",
    domain: "并发：信号量",
    prompt: "制作两个许可的信号量实验：三个任务竞争，同时最多运行两个，第三个排队。",
    checks: [
      { kind: "runtime-clean", id: "runtime" },
      { kind: "numbers-equal", id: "permits-hold", phase: "running", expected: { running: 2, waiting: 1 } },
      { kind: "text-includes", id: "queued-task-visible", phase: "running", values: ["等待"] },
    ],
  },
  {
    id: "M01",
    domain: "数学：一次函数",
    prompt: "绘制 y=2x+1，拖动 x 观察函数值，曲线、坐标与数值同步。",
    checks: [
      { kind: "runtime-clean", id: "runtime" },
      { kind: "numbers-approx", id: "value-at-3", phase: "x3", expected: { y: 7 }, tolerance: 0.01 },
      { kind: "numbers-approx", id: "value-at-minus-1", phase: "xminus1", expected: { y: -1 }, tolerance: 0.01 },
      { kind: "canvas-differs", id: "chart-follows-x", first: "x3", second: "xminus1" },
    ],
  },
  {
    id: "M02",
    domain: "数学：二次函数",
    prompt: "绘制 y=x²−4，观察零点与顶点；把常数项改为 −1 后零点变为 ±1。",
    checks: [
      { kind: "runtime-clean", id: "runtime" },
      { kind: "numbers-approx", id: "zeros-and-vertex", phase: "base", expected: { zero1: -2, zero2: 2, vertexY: -4 }, tolerance: 0.01 },
      { kind: "numbers-approx", id: "adjusted-zeros", phase: "adjusted", expected: { zero1: -1, zero2: 1 }, tolerance: 0.01 },
      { kind: "min-font-size", id: "readable", min: 14 },
    ],
  },
  {
    id: "P01",
    domain: "物理：简谐运动",
    prompt: "制作简谐运动 Canvas 动画 x=2sin(φ)，相位 0、π/2、π 时位置分别为 0、2、0，暂停后不推进。",
    checks: [
      { kind: "runtime-clean", id: "runtime" },
      { kind: "numbers-approx", id: "position-at-phases", phase: "pi-half", expected: { position: 2 }, tolerance: 0.05 },
      { kind: "canvas-differs", id: "motion-visible", first: "phase-zero", second: "pi-half" },
      { kind: "canvas-same", id: "paused", first: "paused-a", second: "paused-b" },
    ],
  },
  {
    id: "S01",
    domain: "统计：混淆矩阵",
    prompt: "制作混淆矩阵与指标联动图：TP=40、FP=10、FN=20、TN=30，精确率 80%、召回率约 66.67%。",
    checks: [
      { kind: "runtime-clean", id: "runtime" },
      { kind: "numbers-approx", id: "precision", phase: "metrics", expected: { precision: 0.8 }, tolerance: 0.005 },
      { kind: "numbers-approx", id: "recall", phase: "metrics", expected: { recall: 0.6667 }, tolerance: 0.005 },
      { kind: "min-font-size", id: "readable", min: 14 },
    ],
  },
  {
    id: "N01",
    domain: "网络：TCP 握手",
    prompt: "制作 TCP 三次握手时序图：SYN → SYN-ACK → ACK，方向与文字同步。",
    checks: [
      { kind: "runtime-clean", id: "runtime" },
      { kind: "numbers-equal", id: "handshake-order", phase: "complete", expected: { syn: 1, synAck: 2, ack: 3 } },
      { kind: "text-includes", id: "labels", phase: "complete", values: ["SYN", "ACK"] },
      {
        kind: "svg-arrow-near",
        id: "ack-direction",
        phase: "complete",
        arrowId: "arrow-ack",
        targetId: "node-server",
        tolerance: 12,
      },
    ],
  },
];

/**
 * One declared-vs-observed check per task: the page's own claim only passes
 * when the checker measured the same thing independently.
 */
const EVIDENCE_CHECKS: Record<
  string,
  { phase: string; declaredKey: string; observedKey: string; tolerance: number }
> = {
  J01: { phase: "reassigned", declaredKey: "objectOfB", observedKey: "objectOfB", tolerance: 0 },
  J02: {
    phase: "call",
    declaredKey: "dispatchedImplementations",
    observedKey: "dispatchedImplementations",
    tolerance: 0,
  },
  A01: { phase: "found", declaredKey: "secondChecked", observedKey: "secondChecked", tolerance: 0 },
  A02: { phase: "result", declaredKey: "distance", observedKey: "distance", tolerance: 0 },
  D01: { phase: "committed", declaredKey: "A", observedKey: "A", tolerance: 0 },
  D02: { phase: "interleaved", declaredKey: "stock", observedKey: "stock", tolerance: 0 },
  C01: { phase: "running", declaredKey: "running", observedKey: "running", tolerance: 0 },
  M01: { phase: "x3", declaredKey: "y", observedKey: "y", tolerance: 0.01 },
  M02: { phase: "base", declaredKey: "vertexY", observedKey: "vertexY", tolerance: 0.01 },
  P01: { phase: "pi-half", declaredKey: "position", observedKey: "position", tolerance: 0.05 },
  S01: { phase: "metrics", declaredKey: "precision", observedKey: "precision", tolerance: 0.005 },
  N01: { phase: "complete", declaredKey: "synAck", observedKey: "synAck", tolerance: 0 },
};

for (const spec of TASK_SPECS) {
  const evidence = EVIDENCE_CHECKS[spec.id];
  if (!evidence) continue;
  spec.checks.push({
    kind: "cross-check",
    id: "evidence-consistent",
    ...evidence,
  });
}
