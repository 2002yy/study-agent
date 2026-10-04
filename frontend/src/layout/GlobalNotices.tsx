import { AlertTriangle, RefreshCw, Settings, X } from "lucide-react";
import { humanizeUiError } from "../utils/uiLabels";

function NoticeDetails({ message }: { message: string }) {
  return (
    <details className="global-notice-details">
      <summary>开发者诊断</summary>
      <div>{message}</div>
    </details>
  );
}

export function GlobalNotices({
  apiError,
  operationError,
  partialErrors,
  onRetryApi,
  onOpenSettings,
  onDismissOperationError,
}: {
  apiError: string;
  operationError: string;
  partialErrors: Array<[string, string]>;
  onRetryApi: () => void;
  onOpenSettings: () => void;
  onDismissOperationError: () => void;
}) {
  if (apiError) {
    return (
      <section aria-live="assertive" className="api-warning" role="alert">
        <AlertTriangle aria-hidden="true" size={16} />
        <div className="global-notice-content">
          <strong>无法连接学习服务</strong>
          <NoticeDetails message={apiError} />
        </div>
        <div className="global-notice-actions">
          <button className="ghost-action compact" onClick={onRetryApi} type="button">
            <RefreshCw aria-hidden="true" size={13} /> 重试
          </button>
          <button className="ghost-action compact" onClick={onOpenSettings} type="button">
            <Settings aria-hidden="true" size={13} /> 设置
          </button>
        </div>
      </section>
    );
  }
  if (operationError) {
    return (
      <section aria-live="assertive" className="api-warning operation-warning" role="alert">
        <AlertTriangle aria-hidden="true" size={16} />
        <div className="global-notice-content">
          <strong>操作没有完成</strong>
          <div>{humanizeUiError(operationError, "本次操作未能完成，请稍后重试。")}</div>
          <NoticeDetails message={operationError} />
        </div>
        <div className="global-notice-actions">
          <button className="ghost-action compact" onClick={onOpenSettings} type="button">
            <Settings aria-hidden="true" size={13} /> 设置
          </button>
          <button
            aria-label="关闭错误提示"
            className="ghost-action compact"
            onClick={onDismissOperationError}
            type="button"
          >
            <X aria-hidden="true" size={13} /> 关闭
          </button>
        </div>
      </section>
    );
  }
  if (!partialErrors.length) return null;
  return (
    <section aria-live="polite" className="api-warning" role="status">
      <AlertTriangle aria-hidden="true" size={16} />
      <div className="global-notice-content">
        <strong>部分功能暂不可用</strong>
        <details className="global-notice-details">
          <summary>开发者诊断</summary>
          {partialErrors.map(([key, message]) => (
            <div key={key}><strong>{key}</strong>: {message}</div>
          ))}
        </details>
      </div>
      <div className="global-notice-actions">
        <button className="ghost-action compact" onClick={onRetryApi} type="button">
          <RefreshCw aria-hidden="true" size={13} /> 重试
        </button>
        <button className="ghost-action compact" onClick={onOpenSettings} type="button">
          <Settings aria-hidden="true" size={13} /> 设置
        </button>
      </div>
    </section>
  );
}
