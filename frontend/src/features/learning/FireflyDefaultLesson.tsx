import { useMemo } from "react";

import { DoupoDefaultLesson } from "./DoupoDefaultLesson";
import { FireflyDefaultLesson as FireflyMechanicsLesson } from "./FireflyMechanicsLesson";
import {
  createDefaultFireflyLessonState,
  type FireflyLessonController,
} from "./defaultFireflyLesson";
import { createDefaultDoupoLessonState } from "./defaultDoupoLesson";
import "./default-lesson.css";

export function FireflyDefaultLesson({
  controller,
}: {
  controller: FireflyLessonController;
}) {
  const lessonKind = controller.state.lessonKind ?? "firefly";
  const doupoController = useMemo(
    () => ({
      state: controller.state.doupo,
      update: (patch: Partial<typeof controller.state.doupo>) =>
        controller.update({
          doupo: { ...controller.state.doupo, ...patch },
        }),
      reset: () =>
        controller.update({ doupo: createDefaultDoupoLessonState() }),
    }),
    [controller],
  );

  const switchLesson = (kind: "firefly" | "doupo") => {
    controller.update({ lessonKind: kind });
  };

  return (
    <div className="default-lesson-frame">
      <div className="default-lesson-switcher" role="tablist" aria-label="默认课程示例">
        <span>示例</span>
        <button
          aria-selected={lessonKind === "firefly"}
          className={lessonKind === "firefly" ? "is-active" : ""}
          onClick={() => switchLesson("firefly")}
          role="tab"
          type="button"
        >
          流萤机制
        </button>
        <button
          aria-selected={lessonKind === "doupo"}
          className={lessonKind === "doupo" ? "is-active" : ""}
          onClick={() => switchLesson("doupo")}
          role="tab"
          type="button"
        >
          斗破叙事
        </button>
        <button
          className="default-lesson-reset"
          onClick={() => controller.reset()}
          type="button"
        >
          恢复默认
        </button>
      </div>
      {lessonKind === "doupo" ? (
        <DoupoDefaultLesson controller={doupoController} />
      ) : (
        <FireflyMechanicsLesson controller={controller} />
      )}
    </div>
  );
}

export function createFreshDefaultLessonState() {
  return createDefaultFireflyLessonState();
}
