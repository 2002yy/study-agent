import { expect, it } from "vitest";
import { packAnswerUiContext, parseAnswerCard, splitAnswerContent } from "./answerUiProtocol";
import { INTERACTIVE_CONTEXT } from "./interactiveRuntime";

it("gives the model a protocol example the actual renderer can accept", () => {
  const example = INTERACTIVE_CONTEXT.match(/\{"type":"interactive"[^\n]*?\}/)?.[0];
  expect(example).toBeDefined();
  expect(parseAnswerCard(example!)).toMatchObject({ type: "interactive", revision: 1 });
  const fenced = "```study-ui\n" + example + "\n```";
  expect(splitAnswerContent(fenced)[0].kind).toBe("card");
  // Prompt repair keeps ordinary HTML examples inert rather than widening execution.
  expect(splitAnswerContent("```html\n<main>example</main>\n```").every(part => part.kind === "markdown")).toBe(true);
});


it("delivers medium and verification guidance through transient context while preserving user choice", () => {
  const instruction = "只用文字解释，金额保留两位小数";
  const packed = packAnswerUiContext(instruction, "原场景参数 a=0");
  const payload = JSON.parse(packed.replace("__STUDY_AGENT_TURN_CONTEXT_V1__", ""));
  expect(payload.conversation_instruction).toBe(instruction);
  expect(payload.turn_context).toContain(INTERACTIVE_CONTEXT);
  expect(payload.turn_context).toContain("尊重其明确的纯文字、静态、交互、动画或3D要求");
  expect(payload.turn_context).toContain("初始输入/预期输出和至少一个边界案例");
  expect(payload.turn_context).toContain("真实执行通过后才能称为已验证");
  expect(payload.turn_context).toContain("原场景参数 a=0");
  expect(payload.turn_context.length).toBeLessThan(12000);
});


it("keeps a text-only request and reply free of a required document", () => {
  const instruction = "只用文字解释已有图形，不要生成界面";
  const payload = JSON.parse(packAnswerUiContext(instruction, "已有场景 scene 版本2")
    .replace("__STUDY_AGENT_TURN_CONTEXT_V1__", ""));
  expect(payload.conversation_instruction).toBe(instruction);
  expect(payload.turn_context).toContain("选择文字时直接用Markdown回答，省略study-ui代码块");
  expect(payload.turn_context).toContain("下列参数、图形和文档生成规则仅在所选媒介需要生成可视化文档时适用");
  expect(payload.turn_context).toContain("仅在生成上述可视化文档时，先给一两句有用文字");
  const reply = "面积等于长乘宽。长为2、宽为3时，面积为6。";
  expect(splitAnswerContent(reply)).toEqual([{ kind: "markdown", content: reply, key: 0 }]);
});
