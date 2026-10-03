import { createContext, useContext, type ReactNode } from "react";

import type { FireflyLessonController } from "./defaultFireflyLesson";

const FireflyLessonContext = createContext<FireflyLessonController | null>(null);

export function FireflyLessonProvider({
  controller,
  children,
}: {
  controller: FireflyLessonController;
  children: ReactNode;
}) {
  return (
    <FireflyLessonContext.Provider value={controller}>
      {children}
    </FireflyLessonContext.Provider>
  );
}

export function useFireflyLessonController(): FireflyLessonController | null {
  return useContext(FireflyLessonContext);
}
