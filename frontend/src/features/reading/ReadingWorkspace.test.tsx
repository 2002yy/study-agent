// @vitest-environment jsdom
import "@testing-library/jest-dom/vitest";
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ReadingLayout, ReadingWorkspaceProvider } from "./ReadingWorkspace";
import { useReadingWorkspace, citationTarget } from "./ReadingContext";
import { readDocument, type DocumentReading, type ReadingTarget } from "./readingApi";
import { SourcesPanel } from "../rag/SourcesPanel";
import { EvidenceTrail } from "../evidence/EvidenceTrail";
import type { ChatResponse } from "../../types";

vi.mock("./readingApi", () => ({readDocument:vi.fn()}));
const known = {document_id:"doc",revision_id:"rev",source_path:"notes.md",title:"学习笔记",
  file_type:"md",content_hash:"hash",chunks:1,metadata:{}};
const target: ReadingTarget = {scope:"knowledge",documentId:"doc",revision:"rev",sourcePath:"notes.md"};
const response: DocumentReading = {schema_version:"document-reading-v1",representation:"indexed_text",
  scope:"knowledge",document_id:"doc",revision_id:"rev",content_hash:"hash",parser_version:"loader_v1",
  title:"学习笔记",source_path:"notes.md",file_type:"md",evidence_status:"active",
  start_line:1,end_line:100,total_lines:220,text:"# 学习正文\n这是资料的第一段。"};

function Open() {
  const reading = useReadingWorkspace()!;
  return <div className="chat-column"><button onClick={()=>reading.open(target)}>打开正文</button>
    <button onClick={()=>reading.ask("选段内容",2,2)}>请求选段解释</button>
    <input aria-label="保留的草稿" defaultValue="已有草稿"/>
  </div>;
}
function Harness({sessionId="a",isSending=false,onAsk=vi.fn(),children,navigationKey=0}: {
  sessionId?:string;isSending?:boolean;onAsk?:(prompt:string)=>void;children?:React.ReactNode;navigationKey?:number;
}) {
  return <ReadingWorkspaceProvider sessionId={sessionId} documents={[known]} isSending={isSending}
    onAsk={onAsk} onOpen={()=>{}} onBrowse={()=>{}} navigationKey={navigationKey}>
    <ReadingLayout><Open/></ReadingLayout>{children}
  </ReadingWorkspaceProvider>;
}
beforeEach(()=>{
  vi.mocked(readDocument).mockReset().mockResolvedValue(response);
  Object.defineProperty(HTMLElement.prototype,"scrollIntoView",{configurable:true,value:vi.fn()});
});
afterEach(cleanup);

describe("reading workspace",()=>{
  it("opens only owner-bound saved web reads and labels a truncated snapshot",async()=>{
    vi.mocked(readDocument).mockResolvedValue({...response,scope:"web",representation:"saved_web_text",file_type:"web",source_path:"https://example.org/read",content_truncated:true});
    const rag={results:[],web_tools:{run_id:"saved-run",calls:[]},evidence_snapshot:{schema_version:"evidence-snapshot-v1",refs:[{id:"web",type:"web_read",url:"https://example.org/read",source:"https://example.org/read",title:"已读网页",lifecycle_status:"selected"}]}} as unknown as ChatResponse["rag"];
    render(<Harness><EvidenceTrail evidence={{rag}}/></Harness>);
    fireEvent.click(screen.getByRole("button",{name:/证据轨迹/}));
    fireEvent.click(screen.getByRole("button",{name:"阅读网页"}));
    await screen.findByText(/阅读时保存的部分正文/);
    expect(readDocument).toHaveBeenCalledWith({scope:"web",threadId:"a",runId:"saved-run",url:"https://example.org/read",sourcePath:"https://example.org/read"},1,expect.any(AbortSignal));
  });
  it("opens full text from the library and closes without discarding chat draft",async()=>{
    render(<Harness><SourcesPanel lastChat={null} ragSearch={null} isSearching={false} initialTab="library"
      knowledgeBase={{index_path:"index.json",index_exists:true,index_version:1,documents:[known],chunks:1}}/></Harness>);
    fireEvent.click(screen.getByRole("button",{name:"阅读正文"}));
    expect(await screen.findByText("这是资料的第一段。")).toBeInTheDocument();
    expect(readDocument).toHaveBeenCalledWith(target,1,expect.any(AbortSignal));
    fireEvent.click(screen.getByRole("button",{name:"关闭资料阅读"}));
    expect(screen.queryByRole("region",{name:"资料正文"})).not.toBeInTheDocument();
    expect(screen.getByLabelText("保留的草稿")).toHaveValue("已有草稿");
  });
  it("pins the returned revision for pagination and clears old text on failure",async()=>{
    vi.mocked(readDocument).mockResolvedValueOnce(response).mockRejectedValueOnce(new Error("资料版本已变化"));
    render(<Harness/>);fireEvent.click(screen.getByText("打开正文"));
    await screen.findByText("这是资料的第一段。");
    fireEvent.click(screen.getByRole("button",{name:"下一段正文"}));
    expect(await screen.findByRole("alert")).toHaveTextContent("资料版本已变化");
    expect(readDocument).toHaveBeenLastCalledWith(expect.objectContaining({revision:"rev"}),101,expect.any(AbortSignal));
    expect(screen.queryByText("这是资料的第一段。")).not.toBeInTheDocument();
  });
  it("preserves the reader DOM and scroll position while switching tabs",async()=>{
    render(<Harness/>);
    // Finish the initial document positioning before simulating user scrolling.
    await act(async()=>{fireEvent.click(screen.getByText("打开正文"))});
    expect(screen.getByText("这是资料的第一段。")).toBeInTheDocument();
    const body=screen.getByLabelText("可滚动资料正文");body.scrollTop=123;
    fireEvent.click(screen.getByRole("button",{name:"对话"}));
    fireEvent.click(screen.getByRole("button",{name:"资料"}));
    expect(screen.getByLabelText("可滚动资料正文")).toBe(body);expect(body.scrollTop).toBe(123);
  });
  it("passes only an explicit quote to the draft action and blocks it while sending",async()=>{
    const ask=vi.fn();const view=render(<Harness onAsk={ask}/>);
    fireEvent.click(screen.getByText("打开正文"));await screen.findByText("这是资料的第一段。");
    fireEvent.click(screen.getByText("请求选段解释"));
    expect(ask).toHaveBeenCalledWith(expect.stringContaining("版本 rev，L2–L2"));
    expect(ask).toHaveBeenCalledWith(expect.stringContaining("引用：\n选段内容"));
    ask.mockClear();view.rerender(<Harness onAsk={ask} isSending/>);
    fireEvent.click(screen.getByText("请求选段解释"));expect(ask).not.toHaveBeenCalled();
  });
  it("discards a late document response after switching session",async()=>{
    let resolve!: (data:DocumentReading)=>void;
    vi.mocked(readDocument).mockImplementationOnce(()=>new Promise(done=>{resolve=done}));
    const view=render(<Harness/>);fireEvent.click(screen.getByText("打开正文"));
    await waitFor(()=>expect(readDocument).toHaveBeenCalled());
    const signal=vi.mocked(readDocument).mock.calls[0][2];
    view.rerender(<Harness sessionId="b"/>);
    expect(signal.aborted).toBe(true);
    await act(async()=>resolve(response));
    expect(screen.queryByRole("region",{name:"资料正文"})).not.toBeInTheDocument();
    expect(screen.queryByText("这是资料的第一段。")).not.toBeInTheDocument();
  });
  it("offers a smaller bounded window for oversized text without truncating it",async()=>{
    vi.mocked(readDocument).mockRejectedValueOnce(new Error("此段正文过长，请缩小阅读窗口")).mockResolvedValueOnce(response);
    render(<Harness/>);fireEvent.click(screen.getByText("打开正文"));
    fireEvent.click(await screen.findByRole("button",{name:"缩小阅读窗口"}));
    await screen.findByText("这是资料的第一段。");
    expect(readDocument).toHaveBeenLastCalledWith(expect.objectContaining({windowLines:20,revision:"rev"}),1,expect.any(AbortSignal));
  });
  it("keeps a global document when the first chat ID is allocated, but clears it on explicit navigation",async()=>{
    const view=render(<Harness sessionId=""/>);
    await act(async()=>{fireEvent.click(screen.getByText("打开正文"))});
    expect(screen.getByText("这是资料的第一段。")).toBeInTheDocument();
    const body=screen.getByLabelText("可滚动资料正文");body.scrollTop=77;
    view.rerender(<Harness sessionId="first-chat"/>);
    expect(screen.getByLabelText("可滚动资料正文")).toBe(body);
    expect(body.scrollTop).toBe(77);expect(readDocument).toHaveBeenCalledTimes(1);
    view.rerender(<Harness sessionId="other-chat" navigationKey={1}/>);
    expect(screen.queryByRole("region",{name:"资料正文"})).not.toBeInTheDocument();
  });
  it("opens an adopted answer citation using the exact turn chunk location",async()=>{
    const rag={status:"found",query:"笔记",retrieval_mode:"hybrid",reason:"",context:"",sources:"",result_count:1,
      debug:{},attempts:[],rewritten_query:"",results:[{chunk:{chunk_id:"c",document_id:"doc",revision_id:"rev",
      source_path:"notes.md",start_line:2,end_line:2},score:1}],evidence_snapshot:{
        schema_version:"evidence-snapshot-v1",refs:[{id:"c",type:"local",source:"notes.md",title:"笔记引用",lifecycle_status:"selected"}],
    }} as ChatResponse["rag"];
    render(<Harness><EvidenceTrail evidence={{rag}}/></Harness>);
    fireEvent.click(screen.getByRole("button",{name:/证据轨迹/}));
    fireEvent.click(screen.getByRole("button",{name:"定位正文"}));
    await screen.findByText("这是资料的第一段。");
    expect(readDocument).toHaveBeenCalledWith({...target,startLine:2,endLine:2},1,expect.any(AbortSignal));
    expect(document.querySelector('[data-line="2"]')).toHaveClass("citation-located");
  });
});

describe("notebook reading navigation",()=>{
  it("locates only headings in the loaded window without another read",async()=>{
    vi.mocked(readDocument).mockResolvedValue({...response,text:"# 学习正文\n第一段\n```md\n# 示例代码\n```\n## 第二节\n正文"});
    render(<Harness/>);fireEvent.click(screen.getByText("打开正文"));
    await screen.findByText("第一段");
    const body=screen.getByLabelText("可滚动资料正文");body.scrollTop=77;
    fireEvent.click(screen.getByRole("button",{name:"本段目录"}));
    const outline=screen.getByRole("navigation",{name:"当前正文窗口目录"});
    expect(outline).toHaveTextContent("当前已载入正文的标题 · L1–L100");
    expect(outline.querySelectorAll("button")).toHaveLength(2);
    expect(outline).not.toHaveTextContent("示例代码");
    fireEvent.click(screen.getByRole("button",{name:"第二节 L6"}));
    expect(document.activeElement).toBe(document.querySelector('[data-line="6"]'));
    expect(readDocument).toHaveBeenCalledTimes(1);
    fireEvent.click(screen.getByRole("button",{name:"本段目录"}));
    expect(body.scrollTop).toBe(77);
  });
  it("jumps locally and binds an outside-window read to the returned revision",async()=>{
    render(<Harness/>);fireEvent.click(screen.getByText("打开正文"));
    await screen.findByText("这是资料的第一段。");
    const input=screen.getByRole("spinbutton",{name:"跳转到正文行号"});
    fireEvent.change(input,{target:{value:"2"}});fireEvent.submit(input.closest("form")!);
    expect(document.activeElement).toBe(document.querySelector('[data-line="2"]'));
    expect(readDocument).toHaveBeenCalledTimes(1);
    fireEvent.change(input,{target:{value:"221"}});fireEvent.submit(input.closest("form")!);
    expect(readDocument).toHaveBeenCalledTimes(1);
    fireEvent.change(input,{target:{value:"101"}});fireEvent.submit(input.closest("form")!);
    await waitFor(()=>expect(readDocument).toHaveBeenCalledTimes(2));
    expect(readDocument).toHaveBeenLastCalledWith(expect.objectContaining({revision:"rev"}),101,expect.any(AbortSignal));
  });
  it("makes selection explicit, clears it, and adds a bound quote only on request",async()=>{
    const ask=vi.fn();render(<Harness onAsk={ask}/>);fireEvent.click(screen.getByText("打开正文"));
    const text=await screen.findByText("这是资料的第一段。");
    const range=document.createRange();range.selectNodeContents(text);
    const selected=window.getSelection()!;selected.removeAllRanges();selected.addRange(range);
    fireEvent.mouseUp(screen.getByLabelText("可滚动资料正文"));
    expect(screen.getByText("已选 L2–L2")).toBeInTheDocument();expect(ask).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button",{name:"取消正文选段"}));
    expect(screen.getByRole("button",{name:"解释选中文字"})).toBeDisabled();
    selected.addRange(range);fireEvent.mouseUp(screen.getByLabelText("可滚动资料正文"));
    fireEvent.click(screen.getByRole("button",{name:"解释选中文字"}));
    expect(ask).toHaveBeenCalledWith(expect.stringContaining("版本 rev，L2–L2"));
    expect(ask).toHaveBeenCalledWith(expect.stringContaining("引用：\n这是资料的第一段。"));
    expect(screen.getByLabelText("保留的草稿")).toHaveValue("已有草稿");
    expect(document.querySelector(".reading-layout")).toHaveClass("reading-chat-active");
  });
});

describe("citation location authorization",()=>{
  const chunk={chunk_id:"c",document_id:"doc",revision_id:"rev",source_path:"notes.md",start_line:2,end_line:5};
  it("resolves a unique exact turn chunk bound to a known document revision",()=>{
    expect(citationTarget("c","notes.md",[{chunk}],[known])).toEqual({...target,startLine:2,endLine:5});
  });
  it("rejects guessed titles, missing revisions, duplicate IDs and stale library revisions",()=>{
    expect(citationTarget("c","notes.md",[{chunk:{...chunk,revision_id:undefined}}],[known])).toBeNull();
    expect(citationTarget("c","other/notes.md",[{chunk}],[known])).toBeNull();
    expect(citationTarget("c","notes.md",[{chunk},{chunk}],[known])).toBeNull();
    expect(citationTarget("c","notes.md",[{chunk}],[{...known,revision_id:"new"}])).toBeNull();
    expect(citationTarget("c","notes.md",[{chunk:{...chunk,start_line:0}}],[known])).toBeNull();
  });
  it("requires explicit current-thread metadata for a temporary citation",()=>{
    const result=[{chunk:{...chunk,metadata:{attachment_id:"att",thread_id:"a"}}}];
    expect(citationTarget("c","notes.md",result,[],"b")).toBeNull();
    expect(citationTarget("c","notes.md",result,[],"a")).toMatchObject({scope:"session",attachmentId:"att",threadId:"a"});
  });
});
