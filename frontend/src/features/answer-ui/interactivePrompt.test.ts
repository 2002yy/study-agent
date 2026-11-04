import { expect, it } from "vitest";
import { parseAnswerCard, splitAnswerContent } from "./answerUiProtocol";
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
