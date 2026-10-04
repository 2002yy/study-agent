import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

const read = (path: string) =>
  readFileSync(fileURLToPath(new URL(path, import.meta.url)), "utf8");

const learningSource = read("./useLearningSessionRuntime.ts");
const runtimeSource = read("./WorkspaceRuntime.tsx");
const viewSource = read("./WorkspaceView.tsx");

describe("Firefly default lesson runtime boundary", () => {
  it("keeps user-authored conversation instructions separate from transient lesson context", () => {
    expect(learningSource).toContain("const defaultLessonContext = useMemo");
    expect(learningSource).toContain("const effectiveConversationInstruction = useMemo");
    expect(learningSource).toContain("conversationInstruction: effectiveConversationInstruction");
    expect(learningSource).toContain("conversationInstruction,");
    expect(learningSource).toContain("fireflyLessonState,");
  });

  it("shares lesson state through the runtime composition boundary without moving ownership into WorkspaceView", () => {
    expect(runtimeSource).toContain("<FireflyLessonProvider controller={learning.fireflyLesson}>");
    expect(viewSource).not.toContain("createDefaultFireflyLessonState");
    expect(viewSource).not.toContain("setFireflyLessonState");
  });

  it("retires the default example when an active durable Goal becomes authoritative", () => {
    expect(learningSource).toContain('learningResume?.source === "durable"');
    expect(learningSource).toContain('learningResume.status === "active"');
    expect(learningSource).toContain("active: false");
  });
});
