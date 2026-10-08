import { afterEach, describe, expect, it, vi } from "vitest";
import { readDocument, readOriginalPdf } from "./readingApi";

const data={schema_version:"document-reading-v1",representation:"indexed_text",scope:"knowledge",
  document_id:"doc",revision_id:"rev",source_path:"notes.md",start_line:1,end_line:2,total_lines:2,text:"a\nb"};
afterEach(()=>{vi.unstubAllGlobals();vi.unstubAllEnvs()});
describe("reading API",()=>{
  it("pins PDF originals and passes API credentials in headers",async()=>{
    const fetcher=vi.fn().mockResolvedValue(new Response(new Uint8Array([37,80,68,70]),{headers:{"Content-Type":"application/pdf"}}));
    vi.stubGlobal("fetch",fetcher);vi.stubEnv("VITE_STUDY_AGENT_API_TOKEN","reader-fixture");
    const signal=new AbortController().signal;
    expect(await readOriginalPdf({scope:"session",threadId:"thread",attachmentId:"att"},"rev",signal)).toEqual(new Uint8Array([37,80,68,70]));
    expect(fetcher).toHaveBeenCalledWith("/sessions/thread/attachments/att/original?expected_revision=rev",{signal,headers:{"X-Study-Agent-Token":"reader-fixture"}});
  });
  it("checks retained web source identity and representation",async()=>{
    vi.stubGlobal("fetch",vi.fn().mockResolvedValue(new Response(JSON.stringify({...data,scope:"web",representation:"saved_web_text",source_path:"https://example.org/saved"}))));
    const target={scope:"web" as const,threadId:"thread",runId:"run",url:"https://example.org/other"};
    await expect(readDocument(target,1,new AbortController().signal)).rejects.toThrow("不一致");
  });
  it("uses an ID-only GET with a bound revision and abort signal",async()=>{
    const fetcher=vi.fn().mockResolvedValue(new Response(JSON.stringify(data)));
    vi.stubGlobal("fetch",fetcher);const signal=new AbortController().signal;
    await readDocument({scope:"knowledge",documentId:"doc",revision:"rev"},1,signal);
    expect(fetcher).toHaveBeenCalledWith("/knowledge-base/documents/doc/reading?start_line=1&limit=100&expected_revision=rev",{signal,headers:{}});
  });
  it("uses the existing deployment token header for reading",async()=>{
    const fetcher=vi.fn().mockResolvedValue(new Response(JSON.stringify(data)));
    vi.stubGlobal("fetch",fetcher);vi.stubEnv("VITE_STUDY_AGENT_API_TOKEN","reader-fixture");
    await readDocument({scope:"knowledge",documentId:"doc",windowLines:20},1,new AbortController().signal);
    expect(fetcher).toHaveBeenCalledWith("/knowledge-base/documents/doc/reading?start_line=1&limit=20",expect.objectContaining({headers:{"X-Study-Agent-Token":"reader-fixture"}}));
  });
  it("rejects source or revision mismatch and out-of-range citation endpoints",async()=>{
    vi.stubGlobal("fetch",vi.fn().mockImplementation(()=>Promise.resolve(new Response(JSON.stringify(data)))));
    await expect(readDocument({scope:"knowledge",documentId:"doc",revision:"old"},1,new AbortController().signal)).rejects.toThrow("不一致");
    await expect(readDocument({scope:"knowledge",documentId:"doc",sourcePath:"other.md"},1,new AbortController().signal)).rejects.toThrow("不一致");
    await expect(readDocument({scope:"knowledge",documentId:"doc",endLine:3},1,new AbortController().signal)).rejects.toThrow("不一致");
  });
  it("preserves server errors rather than falling back to snippets",async()=>{
    vi.stubGlobal("fetch",vi.fn().mockResolvedValue(new Response(JSON.stringify({detail:"资料已删除"}),{status:404})));
    await expect(readDocument({scope:"session",attachmentId:"att",threadId:"thread"},1,new AbortController().signal)).rejects.toThrow("资料已删除");
  });
});
