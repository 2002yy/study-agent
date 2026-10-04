import { ChevronDown, ChevronRight, Sparkles } from "lucide-react";
import { useState } from "react";

import type { ChatResponse, MemoryStatusResponse } from "../../types";
import { useFireflyLessonController } from "./FireflyLessonContext";
import { LearningPanel } from "./LearningPanel";
import { LearningStrip as BaseLearningStrip } from "./LearningStripBase";
import type { LearningResumeResponse } from "./learningResumeApi";

type LearningStripProps = {
  resume: LearningResumeResponse | null;
  resumeError: string;
  sessionId?: string;
  onRevalidated?: () => void;
  lastChat: ChatResponse | null;
  visitedPhases: string[];
  memoryStatus: MemoryStatusResponse | null;
};

export function LearningStrip(props: LearningStripProps) {
  const lesson = useFireflyLessonController();
  const [open, setOpen] = useState(() => Boolean(lesson?.state.active));
  const durableActive =
    props.resume?.source === "durable" && props.resume.status === "active";

  if (
    lesson?.state.active &&
    lesson.state.lessonKind === "doupo" &&
    !durableActive
  ) {
    return (
      <div className="learning-strip firefly-learning-strip" aria-label="默认斗破课程">
        <button
          aria-expanded={open}
          className="learning-strip-toggle trustworthy-learning-summary durable-learning-summary"
          onClick={() => setOpen((value) => !value)}
          type="button"
        >
          <span className="learning-strip-chevron">
            {open ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
          </span>
          <span className="learning-strip-status-item learning-strip-objective">
            <Sparkles size={12} />
            <span>《斗破苍穹》认知翻转</span>
          </span>
          <span className="learning-strip-status-item learning-strip-phase">
            默认示例 · 10张叙事卡
          </span>
          <span className="learning-strip-status-item learning-strip-next">
            <span>人物知识 · 估值曲线 · 身份合并</span>
          </span>
          <span className="learning-verification-badge pending_validation">
            重新估值七门
          </span>
        </button>
        {open ? (
          <div className="learning-strip-detail firefly-learning-detail">
            <LearningPanel
              resume={props.resume}
              resumeError={props.resumeError}
              sessionId={props.sessionId}
              onRevalidated={props.onRevalidated}
              lastChat={props.lastChat}
              visitedPhases={props.visitedPhases}
              memoryStatus={props.memoryStatus}
            />
          </div>
        ) : null}
      </div>
    );
  }

  return <BaseLearningStrip {...props} />;
}
