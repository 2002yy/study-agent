import { BookOpen, CheckCircle2, Loader2, MessageSquare, Upload, X } from "lucide-react";

import type { UploadFlowPhase } from "./uploadController";

export function UploadLearningPrompt({
  phase,
  status,
  detail,
  uploadCount,
  onStartLearning,
  onAskDirectly,
  onChooseAgain,
  onDismiss,
}: {
  phase: UploadFlowPhase;
  status: string;
  detail: string;
  uploadCount: number;
  onStartLearning: () => void;
  onAskDirectly: () => void;
  onChooseAgain: () => void;
  onDismiss: () => void;
}) {
  if (phase === "idle") return null;

  return (
    <section className={`upload-learning-prompt ${phase}`} aria-live="polite">
      <div className="upload-learning-prompt-main">
        <div className="upload-learning-prompt-icon" aria-hidden="true">
          {phase === "processing" ? <Loader2 className="spin" size={18} /> : <CheckCircle2 size={18} />}
        </div>
        <div>
          <span className="upload-learning-prompt-kicker">
            {phase === "processing" ? "正在准备学习资料" : phase === "ready" ? "资料已准备好" : "资料处理未完成"}
          </span>
          <strong>{status || (uploadCount ? `${uploadCount} 份资料` : "本次资料")}</strong>
          {detail ? <small>{detail}</small> : null}
        </div>
      </div>

      {phase === "ready" ? (
        <div className="upload-learning-prompt-actions">
          <button className="primary-action compact" onClick={onStartLearning} type="button">
            <BookOpen size={14} />
            开始系统学习
          </button>
          <button className="ghost-action compact" onClick={onAskDirectly} type="button">
            <MessageSquare size={14} />
            直接提问
          </button>
          <button aria-label="关闭资料准备提示" className="icon-button" onClick={onDismiss} type="button">
            <X size={15} />
          </button>
        </div>
      ) : null}

      {phase === "failed" ? (
        <div className="upload-learning-prompt-actions">
          <button className="ghost-action compact" onClick={onChooseAgain} type="button">
            <Upload size={14} />
            重新选择资料
          </button>
          <button aria-label="关闭资料错误提示" className="icon-button" onClick={onDismiss} type="button">
            <X size={15} />
          </button>
        </div>
      ) : null}
    </section>
  );
}
