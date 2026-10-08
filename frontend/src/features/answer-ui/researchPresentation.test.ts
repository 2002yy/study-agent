import { describe, expect, it } from "vitest";
import { mergeResearchPresentation, parseResearchPresentation } from "./researchPresentation";

import { researchFixture } from "./researchPresentation.fixture";
describe("read-only research presentation", () => {
  it("accepts structured server status while refusing self-granted publication", () => {
    const s = researchFixture();
    expect(parseResearchPresentation(s)).toEqual(s);
    expect(parseResearchPresentation({ ...s, publication_authority: true })).toBeNull();
    expect(parseResearchPresentation({ ...s, publication_status: "approved" })).toBeNull();
    expect(parseResearchPresentation({ ...s, protocol_version: 2 })).toBeNull();
  });
  it("rejects duplicate identities and unsafe sources", () => {
    const s = researchFixture();
    expect(parseResearchPresentation({ ...s, blocks: [...s.blocks, ...s.blocks] })).toBeNull();
    s.blocks[0].sources[0].url = "javascript:alert(1)";
    expect(parseResearchPresentation(s)).toBeNull();
  });
  it("deduplicates events and never rolls a run backward", () => {
    const s = researchFixture();
    const stale = researchFixture(); stale.blocks[0].revision = 1;
    stale.blocks[0].sources[0].title = "旧标题";
    expect(mergeResearchPresentation(s, stale).blocks[0].sources[0].title).toBe("官方资料");
    expect(mergeResearchPresentation(s, s).blocks).toHaveLength(1);
    stale.blocks[0].revision = 3;
    expect(mergeResearchPresentation(s, stale).blocks[0].revision).toBe(3);
  });
  it("keeps audited turn metadata when a late run event or old durable response arrives", () => {
    const current = researchFixture();
    current.audit_status = "audited"; current.audit_integrity = "valid"; current.watch = false;
    current.blocks[0].research_status = "completed";
    const event = researchFixture(); event.snapshot_kind = "run"; event.turn_updated_at = null;
    event.blocks[0].revision = 1;
    expect(mergeResearchPresentation(current, event)).toEqual(current);
    const old = researchFixture(); old.turn_updated_at = "2026-10-08T09:00:00Z";
    expect(mergeResearchPresentation(current, old)).toEqual(current);
    const invalidated = researchFixture(); invalidated.turn_updated_at = "2026-10-08T11:00:00Z";
    invalidated.audit_integrity = "invalid"; invalidated.watch = false;
    invalidated.blocks[0].research_status = "completed";
    expect(mergeResearchPresentation(current, invalidated).audit_integrity).toBe("invalid");
  });
  it("rejects aliased run and source block identities", () => {
    const run = researchFixture(); run.blocks[0].block_id = "alias";
    expect(parseResearchPresentation(run)).toBeNull();
    const source = researchFixture(); source.blocks[0].sources[0].block_id = "alias";
    expect(parseResearchPresentation(source)).toBeNull();
  });
});
