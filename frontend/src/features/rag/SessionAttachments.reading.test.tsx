// @vitest-environment jsdom
import "@testing-library/jest-dom/vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { listSessionAttachments } from "../../api";
import { SessionAttachments } from "./SessionAttachments";
import { ReadingLayout, ReadingWorkspaceProvider } from "../reading/ReadingWorkspace";
import { readDocument } from "../reading/readingApi";

vi.mock("../../api",()=>({listSessionAttachments:vi.fn(),deleteSessionAttachment:vi.fn(),
  promoteSessionAttachment:vi.fn(),retrySessionAttachment:vi.fn(),uploadSessionAttachment:vi.fn()}));
vi.mock("../reading/readingApi",()=>({readDocument:vi.fn()}));
afterEach(()=>{cleanup();vi.clearAllMocks()});
it("reads only a ready text attachment in its current thread",async()=>{
  const attachment={id:"att",thread_id:"thread",filename:"notes.md",content_hash:"hash",
    mime_type:"text/markdown",size_bytes:12,status:"ready" as const,stage_error:"",stage_history:[],
    retry_count:0,promoted_rag_run_id:"",external_calls:[],created_at:"",updated_at:""};
  vi.mocked(listSessionAttachments).mockResolvedValue({attachments:[attachment,
    {...attachment,id:"image",filename:"photo.png"},{...attachment,id:"pending",status:"parsing"}],max_files_per_thread:10,total_bytes:36});
  vi.mocked(readDocument).mockResolvedValue({schema_version:"document-reading-v1",representation:"indexed_text",
    scope:"session",document_id:"doc",revision_id:"rev",content_hash:"hash",parser_version:"loader_v1",
    title:"附件讲义",source_path:"notes.md",file_type:"md",evidence_status:"active",start_line:1,end_line:1,total_lines:1,text:"只属于本会话的正文"});
  render(<ReadingWorkspaceProvider sessionId="thread" documents={[]} isSending={false} onAsk={()=>{}} onOpen={()=>{}} onBrowse={()=>{}}>
    <ReadingLayout><div className="chat-column"><SessionAttachments sessionId="thread"/></div></ReadingLayout>
  </ReadingWorkspaceProvider>);
  expect(await screen.findAllByRole("button",{name:"阅读正文"})).toHaveLength(1);
  fireEvent.click(screen.getByRole("button",{name:"阅读正文"}));
  expect(await screen.findByText("只属于本会话的正文")).toBeInTheDocument();
  expect(readDocument).toHaveBeenCalledWith({scope:"session",threadId:"thread",attachmentId:"att"},1,expect.any(AbortSignal));
});
