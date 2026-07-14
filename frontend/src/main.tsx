import React from "react";
import ReactDOM from "react-dom/client";
import App from "./App";
import { WorkspaceProvider } from "./app/WorkspaceProvider";
import { seedMessages } from "./features/single-chat/chatHistory";
import "./styles.css";
import "./practical-experience.css";
import "./task-intent-selector.css";

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
          <p>{this.state.error.message}</p>
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
  </React.StrictMode>
);
