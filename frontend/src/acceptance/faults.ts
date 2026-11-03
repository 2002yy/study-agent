import type { Layer, Observation, Phase } from "./model";

/**
 * Twenty-four known defects, eight per layer, applied to an otherwise correct
 * observation. They measure the detector itself: a known fault must be reported
 * as a failure on the named check, never silently pass.
 *
 * A fault mutates both what the page declares and what the checker observes,
 * because a page can be consistently wrong. Declared-vs-observed disagreement
 * is exercised separately by the evidence tests.
 */
export type Fault = {
  id: string;
  taskId: string;
  layer: Extract<Layer, "runtime" | "state" | "geometry" | "usability">;
  checkId: string;
  description: string;
  apply: (observation: Observation) => Observation;
};

const clone = (observation: Observation): Observation =>
  JSON.parse(JSON.stringify(observation)) as Observation;

function setNumber(phase: Phase, key: string, value: number): void {
  phase.declared[key] = value;
  phase.observed[key] = value;
}

export const FAULTS: Fault[] = [
  // runtime: eight defects
  {
    id: "R01",
    taskId: "J01",
    layer: "runtime",
    checkId: "runtime",
    description: "脚本抛错，界面停在初始画面",
    apply: observation => {
      const next = clone(observation);
      next.pageErrors.push("TypeError: cannot read properties of undefined");
      return next;
    },
  },
  {
    id: "R02",
    taskId: "A01",
    layer: "runtime",
    checkId: "runtime",
    description: "控制台报错，区间高亮不更新",
    apply: observation => {
      const next = clone(observation);
      next.consoleErrors.push("Uncaught ReferenceError: mid is not defined");
      return next;
    },
  },
  {
    id: "R03",
    taskId: "M01",
    layer: "runtime",
    checkId: "runtime",
    description: "拖动回调未绑定",
    apply: observation => {
      const next = clone(observation);
      next.pageErrors.push("Uncaught TypeError: onInput is not a function");
      return next;
    },
  },
  {
    id: "R04",
    taskId: "D01",
    layer: "runtime",
    checkId: "runtime",
    description: "回滚按钮点击后抛错",
    apply: observation => {
      const next = clone(observation);
      next.consoleErrors.push("Uncaught Error: rollback failed");
      return next;
    },
  },
  {
    id: "R05",
    taskId: "S01",
    layer: "runtime",
    checkId: "runtime",
    description: "指标联动脚本中断",
    apply: observation => {
      const next = clone(observation);
      next.pageErrors.push("ReferenceError: matrix is not defined");
      return next;
    },
  },
  {
    id: "R06",
    taskId: "P01",
    layer: "runtime",
    checkId: "runtime",
    description: "动画循环因异常停止",
    apply: observation => {
      const next = clone(observation);
      next.consoleErrors.push("Uncaught RangeError: Maximum call stack size exceeded");
      return next;
    },
  },
  {
    id: "R07",
    taskId: "N01",
    layer: "runtime",
    checkId: "runtime",
    description: "时序推进报错",
    apply: observation => {
      const next = clone(observation);
      next.pageErrors.push("TypeError: steps is undefined");
      return next;
    },
  },
  {
    id: "R08",
    taskId: "C01",
    layer: "runtime",
    checkId: "runtime",
    description: "队列释放回调抛错",
    apply: observation => {
      const next = clone(observation);
      next.consoleErrors.push("Uncaught TypeError: release is not a function");
      return next;
    },
  },

  // state: eight defects (the page consistently shows the wrong value)
  {
    id: "S01",
    taskId: "J01",
    layer: "state",
    checkId: "reassigned-objects",
    description: "重新指向后仍显示同一个对象",
    apply: observation => {
      const next = clone(observation);
      setNumber(next.phases.reassigned, "objectOfB", 1);
      return next;
    },
  },
  {
    id: "S02",
    taskId: "A01",
    layer: "state",
    checkId: "checked-indexes",
    description: "从索引 0 开始线性扫描",
    apply: observation => {
      const next = clone(observation);
      setNumber(next.phases.found, "firstChecked", 0);
      return next;
    },
  },
  {
    id: "S03",
    taskId: "A02",
    layer: "state",
    checkId: "shortest-distance",
    description: "把 A-C-D 当成最短路（8）",
    apply: observation => {
      const next = clone(observation);
      setNumber(next.phases.result, "distance", 8);
      return next;
    },
  },
  {
    id: "S04",
    taskId: "D01",
    layer: "state",
    checkId: "committed",
    description: "转账后总额变成 130",
    apply: observation => {
      const next = clone(observation);
      setNumber(next.phases.committed, "A", 60);
      return next;
    },
  },
  {
    id: "S05",
    taskId: "D02",
    layer: "state",
    checkId: "lost-update",
    description: "把丢失更新显示成 8",
    apply: observation => {
      const next = clone(observation);
      setNumber(next.phases.interleaved, "stock", 8);
      return next;
    },
  },
  {
    id: "S06",
    taskId: "C01",
    layer: "state",
    checkId: "permits-hold",
    description: "三个任务同时运行",
    apply: observation => {
      const next = clone(observation);
      setNumber(next.phases.running, "running", 3);
      setNumber(next.phases.running, "waiting", 0);
      return next;
    },
  },
  {
    id: "S07",
    taskId: "M01",
    layer: "state",
    checkId: "value-at-3",
    description: "x=3 时显示 y=6",
    apply: observation => {
      const next = clone(observation);
      setNumber(next.phases.x3, "y", 6);
      return next;
    },
  },
  {
    id: "S08",
    taskId: "S01",
    layer: "state",
    checkId: "precision",
    description: "精确率算成 40/60",
    apply: observation => {
      const next = clone(observation);
      setNumber(next.phases.metrics, "precision", 0.667);
      return next;
    },
  },

  // visual and usability: eight defects
  {
    id: "V01",
    taskId: "J01",
    layer: "geometry",
    checkId: "arrow-points-at-its-object",
    description: "箭头终点指向空白",
    apply: observation => {
      const next = clone(observation);
      const arrow = next.phases.reassigned.svg?.find(shape => shape.id === "arrow-b");
      if (arrow) arrow.to = { x: 120, y: 240 };
      return next;
    },
  },
  {
    id: "V02",
    taskId: "N01",
    layer: "geometry",
    checkId: "ack-direction",
    description: "ACK 箭头画向客户端相反方向",
    apply: observation => {
      const next = clone(observation);
      const arrow = next.phases.complete.svg?.find(shape => shape.id === "arrow-ack");
      if (arrow) arrow.to = { x: 10, y: 400 };
      return next;
    },
  },
  {
    id: "V03",
    taskId: "M01",
    layer: "geometry",
    checkId: "chart-follows-x",
    description: "数值变了但曲线没动",
    apply: observation => {
      const next = clone(observation);
      next.phases.xminus1.canvas = { pixels: [[255, 0, 0]] };
      return next;
    },
  },
  {
    id: "V04",
    taskId: "P01",
    layer: "geometry",
    checkId: "paused",
    description: "暂停后画布仍在推进",
    apply: observation => {
      const next = clone(observation);
      next.phases["paused-b"].canvas = { pixels: [[1, 1, 1]] };
      return next;
    },
  },
  {
    id: "V05",
    taskId: "M02",
    layer: "usability",
    checkId: "readable",
    description: "坐标轴文字缩到 12px",
    apply: observation => {
      const next = clone(observation);
      next.fontSizes = [12, 16];
      return next;
    },
  },
  {
    id: "V06",
    taskId: "S01",
    layer: "usability",
    checkId: "readable",
    description: "矩阵标签缩到 11px",
    apply: observation => {
      const next = clone(observation);
      next.fontSizes = [11, 16];
      return next;
    },
  },
  {
    id: "V07",
    taskId: "A02",
    layer: "usability",
    checkId: "no-overflow",
    description: "手机宽度出现横向滚动",
    apply: observation => {
      const next = clone(observation);
      next.horizontalOverflow = true;
      return next;
    },
  },
  {
    id: "V08",
    taskId: "D02",
    layer: "usability",
    checkId: "no-overflow",
    description: "时间线在两个事务并排时溢出",
    apply: observation => {
      const next = clone(observation);
      next.horizontalOverflow = true;
      return next;
    },
  },
];
