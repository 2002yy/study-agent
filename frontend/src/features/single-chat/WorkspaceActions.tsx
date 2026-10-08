import { CheckCircle2, Library, Loader2, LogOut, MoreHorizontal, Settings, Upload } from "lucide-react";
import type { DrawerId } from "../../types";
import { ExtensionLauncher } from "../extensions/ExtensionLauncher";
import { RAG_UPLOAD_HELP_TEXT } from "../rag/uploadContract";
export function WorkspaceActions({onUploadClick,onOpenDrawer,onEndSession,isEndingSession,isSending,canClose,closureLabel}: {
  onUploadClick:()=>void;onOpenDrawer:(drawer:DrawerId)=>void;onEndSession:()=>void;
  isEndingSession?:boolean;isSending:boolean;canClose:boolean;closureLabel:string|null;
}) {
  const openFromMenu=(drawer:DrawerId,target:HTMLButtonElement)=>{
    const menu=target.closest("details"); menu?.removeAttribute("open");
    menu?.querySelector<HTMLElement>("summary")?.focus();onOpenDrawer(drawer);
  };
  return (
    <div className="workspace-navigation-actions" aria-label="工作台工具">
          {closureLabel && canClose ? (
            <button
              aria-label={closureLabel}
              className="end-session-button"
              disabled={isEndingSession || isSending || !canClose}
              onClick={onEndSession}
              type="button"
              title="整理本次学习成果（确认后才写入）"
            >
              {isEndingSession ? <Loader2 className="spin" size={16} /> : <LogOut size={16} />}
              {closureLabel}
            </button>
          ) : null}
          <button
            aria-label="上传学习资料"
            className="sidebar-upload-button"
            onClick={onUploadClick}
            type="button"
            title={`上传学习资料。${RAG_UPLOAD_HELP_TEXT}`}
          >
            <Upload size={16} />
            <span>上传资料</span>
          </button>
          <details className="workspace-menu">
            <summary aria-label="打开更多学习工具" className="workspace-menu-trigger" title="更多">
              <MoreHorizontal size={16} />
              <span>设置与工具</span>
            </summary>
            <div className="workspace-menu-popover" role="menu">
              <button onClick={(event) => openFromMenu("sources", event.currentTarget)} role="menuitem" type="button">
                <Library size={16} />
                <span><strong>资料与来源</strong><small>查看回答引用和已上传资料</small></span>
              </button>
              <button onClick={(event) => openFromMenu("memory", event.currentTarget)} role="menuitem" type="button">
                <CheckCircle2 size={16} />
                <span><strong>学习成果</strong><small>整理并确认本次学习沉淀</small></span>
              </button>
              <button onClick={(event) => openFromMenu("settings", event.currentTarget)} role="menuitem" type="button">
                <Settings size={16} />
                <span><strong>设置</strong><small>调整学习体验、资料使用与隐私</small></span>
              </button>

              <ExtensionLauncher onOpen={openFromMenu} />
            </div>
          </details>
          </div>
  );
}
