import type { Observation, SvgShape } from "./model";

function base(): Observation {
  return {
    phases: {},
    consoleErrors: [],
    pageErrors: [],
    fontSizes: [16, 16, 18],
    controlSizes: [44, 48],
    horizontalOverflow: false,
  };
}

/** A page that shows and does the same thing: declared and observed agree. */
function values(values: Record<string, number>) {
  return { declared: { ...values }, observed: { ...values } };
}

const node = (id: string, x: number, y: number): SvgShape => ({
  id,
  kind: "node",
  x,
  y,
  width: 40,
  height: 30,
});

/** One observation per task that satisfies every check, used to prove the
 *  judge does not fail a correct answer. */
export function correctObservation(taskId: string): Observation {
  const observation = base();
  switch (taskId) {
    case "J01":
      observation.phases.shared = { text: "a 与 b 指向同一对象", ...values({ objectOfA: 1, objectOfB: 1 }) };
      observation.phases.reassigned = {
        text: "b = new Object()，现在有两个对象",
        ...values({ objectOfA: 1, objectOfB: 2 }),
        svg: [
          node("node-b", 0, 20),
          node("node-new-object", 200, 0),
          {
            id: "arrow-b",
            kind: "arrow",
            x: 0,
            y: 0,
            width: 0,
            height: 0,
            from: { x: 30, y: 40 },
            to: { x: 210, y: 15 },
          },
        ],
      };
      break;
    case "J02":
      observation.phases.call = {
        text: "Animal a = new Dog(); a.sound() 执行 Dog 的实现",
        ...values({ dispatchedImplementations: 1 }),
      };
      break;
    case "A01":
      observation.phases.found = {
        text: "先检查索引 2（值 5），再检查索引 3（值 7），找到 7",
        ...values({ firstChecked: 2, secondChecked: 3 }),
      };
      break;
    case "A02":
      observation.phases.result = { text: "最短路径 A-B-C-D，距离 6", ...values({ distance: 6 }) };
      break;
    case "D01":
      observation.phases.committed = { text: "转账完成", ...values({ A: 70, B: 70 }) };
      observation.phases.rolled_back = { text: "事务回滚，A=100，B=40", ...values({ A: 100, B: 40 }) };
      break;
    case "D02":
      observation.phases.interleaved = { text: "交错执行", ...values({ stock: 9 }) };
      observation.phases.serialized = { text: "串行执行", ...values({ stock: 8 }) };
      break;
    case "C01":
      observation.phases.running = { text: "两个任务运行，一个任务等待", ...values({ running: 2, waiting: 1 }) };
      break;
    case "M01":
      observation.phases.x3 = { text: "x=3，y=7", ...values({ y: 7 }), canvas: { pixels: [[255, 0, 0]] } };
      observation.phases.xminus1 = { text: "x=-1，y=-1", ...values({ y: -1 }), canvas: { pixels: [[0, 0, 255]] } };
      break;
    case "M02":
      observation.phases.base = {
        text: "零点 -2 与 2，顶点 (0,-4)",
        ...values({ zero1: -2, zero2: 2, vertexY: -4 }),
      };
      observation.phases.adjusted = { text: "零点 -1 与 1", ...values({ zero1: -1, zero2: 1 }) };
      break;
    case "P01":
      observation.phases["phase-zero"] = { text: "相位 0", ...values({ position: 0 }), canvas: { pixels: [[0, 0, 0]] } };
      observation.phases["pi-half"] = { text: "相位 π/2", ...values({ position: 2 }), canvas: { pixels: [[1, 2, 3]] } };
      observation.phases["paused-a"] = { text: "已暂停", ...values({}), canvas: { pixels: [[9, 9, 9]] } };
      observation.phases["paused-b"] = { text: "仍暂停", ...values({}), canvas: { pixels: [[9, 9, 9]] } };
      break;
    case "S01":
      observation.phases.metrics = {
        text: "TP=40 FP=10 FN=20 TN=30，精确率 80%，召回率 66.67%",
        ...values({ precision: 0.8, recall: 0.6667 }),
      };
      break;
    case "N01":
      observation.phases.complete = {
        text: "SYN → SYN-ACK → ACK",
        ...values({ syn: 1, synAck: 2, ack: 3 }),
        svg: [
          node("node-server", 300, 0),
          {
            id: "arrow-ack",
            kind: "arrow",
            x: 0,
            y: 0,
            width: 0,
            height: 0,
            from: { x: 20, y: 20 },
            to: { x: 310, y: 15 },
          },
        ],
      };
      break;
    default:
      throw new Error(`unknown task ${taskId}`);
  }
  return observation;
}
