import { BookOpen, FileText, FolderOpen } from "lucide-react";
import { useReadingWorkspace } from "./ReadingContext";

export function ReadingLibraryNavigation() {
  const reader=useReadingWorkspace();
  if(!reader)return null;
  return <section className="reading-library-navigation" aria-label="资料导航">
    <div className="reading-library-heading"><span><FolderOpen size={15}/>阅读资料</span><button type="button" onClick={reader.browse} aria-label="管理阅读资料">管理</button></div>
    {reader.target && reader.target.scope !== "knowledge" ? <button type="button" className="reading-library-document is-current" onClick={reader.showReader}><BookOpen size={16}/><span><strong>{reader.document?.title || "当前资料"}</strong><small>{reader.target.scope === "session" ? "本会话附件" : "网页阅读记录"}</small></span></button>:null}
    <div className="reading-library-documents">
      {reader.documents.map(doc=><button key={doc.document_id} type="button" className={`reading-library-document${reader.target?.scope === "knowledge" && reader.target.documentId === doc.document_id ? " is-current":""}`} aria-current={reader.target?.documentId === doc.document_id ? "page":undefined} onClick={()=>reader.open({scope:"knowledge",documentId:doc.document_id,revision:doc.revision_id,sourcePath:doc.source_path})}><FileText size={16}/><span><strong>{doc.title}</strong><small>{doc.file_type.toUpperCase()} · 长期资料</small></span></button>)}
    </div>
    {!reader.documents.length?<button type="button" className="reading-library-empty" onClick={reader.browse}><BookOpen size={16}/>选择一份资料开始阅读</button>:null}
  </section>;
}
