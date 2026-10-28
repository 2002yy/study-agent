import { describe, expect, it } from "vitest";

import { ACCEPTED_EXTENSIONS, isImageAttachment } from "./attachmentRules";

describe("session attachment accept list", () => {
  it("advertises CSV alongside the other text documents", () => {
    expect(ACCEPTED_EXTENSIONS).toEqual([
      ".md",
      ".markdown",
      ".txt",
      ".csv",
      ".pdf",
      ".docx",
      ".jpg",
      ".jpeg",
      ".png",
      ".gif",
      ".webp",
    ]);
  });

  it("keeps CSV a document rather than an image", () => {
    expect(isImageAttachment("counts.csv")).toBe(false);
    expect(isImageAttachment("scan.png")).toBe(true);
  });
});
