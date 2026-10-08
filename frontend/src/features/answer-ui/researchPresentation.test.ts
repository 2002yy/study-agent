import { describe, expect, it } from "vitest";
import { mergeResearchPresentation, parseResearchPresentation } from "./researchPresentation";

import { researchFixture } from "./researchPresentation.fixture";
describe("read-only research presentation", () => {
  it.each([1, 0, null])("uses authoritative equal-version turn counts, including %s", readCount => {
    const event = researchFixture(); event.snapshot_kind = "run"; event.turn_updated_at = null;
    event.blocks[0].read_count = 4;
    const turn = researchFixture(); turn.blocks[0].read_count = readCount;
    turn.blocks[0].research_status = "completed"; turn.watch = false;
    const merged = mergeResearchPresentation(event, turn);
    expect(merged.blocks[0].read_count).toBe(readCount);
    expect(merged.watch).toBe(false);
    // An equal-revision partial SSE cannot undo the full turn's correction.
    expect(mergeResearchPresentation(merged, event)).toEqual(merged);
  });
  it("replaces SSE zero with a same-version durable read, without accepting older turn corrections", () => {
    const event = researchFixture(); event.snapshot_kind = "run"; event.turn_updated_at = null;
    event.blocks[0].read_count = 0;
    const turn = researchFixture(); turn.blocks[0].read_count = 1;
    const merged = mergeResearchPresentation(event, turn);
    expect(merged.blocks[0].read_count).toBe(1);
    const stale = researchFixture(); stale.turn_updated_at = "2026-10-08T09:00:00Z";
    stale.blocks[0].read_count = 9;
    expect(mergeResearchPresentation(merged, stale)).toEqual(merged);
    stale.snapshot_kind = "run"; stale.turn_updated_at = null; stale.blocks[0].revision = 1;
    expect(mergeResearchPresentation(merged, stale)).toEqual(merged);
  });
  it("does not inherit counts across sessions, turns or run identities", () => {
    const previous = researchFixture(); previous.blocks[0].read_count = 8;
    const session = researchFixture(); session.session_id = "s2";
    expect(mergeResearchPresentation(previous, session).blocks[0].read_count).toBeNull();
    const turn = researchFixture(); turn.turn_id = "t2";
    expect(mergeResearchPresentation(previous, turn).blocks[0].read_count).toBeNull();
    const nextRun = researchFixture(); nextRun.blocks[0].run_id = "r2";
    nextRun.blocks[0].block_id = "r2:research"; nextRun.blocks[0].sources = [];
    const merged = mergeResearchPresentation(previous, nextRun);
    expect(merged.blocks.find(b => b.run_id === "r2")?.read_count).toBeNull();
    expect(merged.blocks.find(b => b.run_id === "r1")?.read_count).toBe(8);
  });
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
