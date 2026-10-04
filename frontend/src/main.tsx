import React from "react";
import ReactDOM from "react-dom/client";
import { humanizeUiError } from "./utils/uiLabels";
import App from "./App";
import { WorkspaceProvider } from "./app/WorkspaceProvider";
import { seedMessages } from "./features/single-chat/chatHistory";
import "./styles.css";
import "./practical-experience.css";
import "./product-boundary.css";
import "./task-intent-selector.css";
import "./learning-closure.css";
import "./session-navigation.css";
import "./trustworthy-learning-status.css";
import "./restore-card.css";
import "./progressive-disclosure.css";
import "./features/rag/sourcesPanel.css";
import "./accessibility-responsive.css";
import "./recovery-visibility.css";

type AppErrorBoundaryState = {
  error: Error | null;
};

class AppErrorBoundary extends React.Component<React.PropsWithChildren, AppErrorBoundaryState> {
  state: AppErrorBoundaryState = { error: null };

  static getDerivedStateFromError(error: Error): AppErrorBoundaryState {
    return { error };
  }

  render() {
    if (this.state.error) {
      return (
        <div className="app-error-boundary">
          <strong>前端渲染异常</strong>
          <p>{humanizeUiError(this.state.error, "学习界面暂时无法显示，请刷新页面重试。")}</p>
          <button type="button" onClick={() => window.location.reload()}>
            刷新页面
          </button>
        </div>
      );
    }
    return this.props.children;
  }
}

ReactDOM.createRoot(document.getElementById("root") as HTMLElement).render(
  <React.StrictMode>
    <AppErrorBoundary>
      <WorkspaceProvider initialState={{ chatMessages: seedMessages }}>
        <App />
      </WorkspaceProvider>
    </AppErrorBoundary>
  </React.StrictMode>,
);
