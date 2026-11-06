// @vitest-environment jsdom
import "@testing-library/jest-dom/vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { parseAnswerCard } from "./answerUiProtocol";
import { makeInteractiveDocument, type InteractiveCard } from "./interactiveRuntime";
import { InteractiveDocument } from "./InteractiveDocument";
import { loadThreeSource } from "./threeSource";

vi.mock("./threeSource", () => ({ loadThreeSource: vi.fn() }));
vi.mock("../../api", () => ({ loadInteractiveState: vi.fn(), saveInteractiveState: vi.fn() }));
const card: InteractiveCard = { type: "interactive", id: "three-demo", revision: 1, title: "3D", summary: "旋转观察", html: "<main>page</main><script>void THREE.Scene</script>" };
afterEach(cleanup);
beforeEach(() => vi.mocked(loadThreeSource).mockReset());

describe("controlled Three capability", () => {
  it("preserves old cards and accepts only the explicit supported capability", () => {
    expect(parseAnswerCard(JSON.stringify(card))).toEqual(card);
    expect(parseAnswerCard(JSON.stringify({ ...card, capabilities: ["three"] }))).toMatchObject({ capabilities: ["three"] });
    expect(parseAnswerCard(JSON.stringify({ ...card, capabilities: [] }))).toEqual(card);
    for (const capabilities of [["cdn"], ["three", "three"], "three", null]) {
      expect(parseAnswerCard(JSON.stringify({ ...card, capabilities }))).toBeNull();
    }
  });
  it("requires a loaded host source and never injects it for ordinary cards", () => {
    expect(() => makeInteractiveDocument(card.html, "test", ["three"])).toThrow();
    expect(makeInteractiveDocument(card.html, "test", undefined, "trusted-marker")).not.toContain("trusted-marker");
    const output = makeInteractiveDocument(card.html, "test", ["three"], 'window.THREE={};/* trusted-marker </script> */');
    expect(output).toContain("trusted-marker");
    expect(output).toContain("connect-src 'none'");
    expect(output).toContain("worker-src 'none'");
    expect(output).not.toContain("allow-same-origin");
    // The source remains inside the outer frame's escaped JSON srcdoc data.
    expect(output).not.toContain("<script>window.THREE");
  });
  it("loads only opted-in cards and mounts only after the source resolves", async () => {
    let resolve!: (source: string) => void;
    vi.mocked(loadThreeSource).mockReturnValue(new Promise(done => { resolve = done; }));
    const { container, rerender } = render(<InteractiveDocument card={card} />);
    expect(container.querySelector("iframe")).not.toBeNull();
    expect(loadThreeSource).not.toHaveBeenCalled();
    rerender(<InteractiveDocument card={{ ...card, capabilities: ["three"] }} />);
    expect(container.querySelector("iframe")).toBeNull();
    expect(screen.getByText("正在加载本地 3D 能力…")).toBeVisible();
    resolve("window.THREE={Scene:class{}}");
    await waitFor(() => expect(container.querySelector("iframe")).not.toBeNull());
    expect(container.querySelector("iframe")?.getAttribute("srcdoc")).toContain("window.THREE");
  });
  it("reports load failure without executing the page and allows retry", async () => {
    vi.mocked(loadThreeSource).mockRejectedValueOnce(new Error("offline"))
      .mockResolvedValueOnce("window.THREE={}");
    const { container } = render(<InteractiveDocument card={{ ...card, capabilities: ["three"] }} />);
    expect(await screen.findByRole("alert")).toHaveTextContent("本地 Three.js 能力加载失败");
    expect(container.querySelector("iframe")).toBeNull();
    fireEvent.click(screen.getByTitle("恢复初始状态"));
    await waitFor(() => expect(container.querySelector("iframe")).not.toBeNull());
    expect(loadThreeSource).toHaveBeenCalledTimes(2);
  });
});
