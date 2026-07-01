import { AlertTriangle } from "lucide-react";

export function GlobalNotices({
  apiError,
  operationError,
  partialErrors,
  onDismissOperationError,
}: {
  apiError: string;
  operationError: string;
  partialErrors: Array<[string, string]>;
  onDismissOperationError: () => void;
}) {
  if (apiError) {
    return <div className="api-warning"><AlertTriangle size={16} />API 未连接：{apiError}</div>;
  }
  if (operationError) {
    return (
      <div className="api-warning operation-warning">
        <AlertTriangle size={16} />{operationError}
        <button className="ghost-action compact" onClick={onDismissOperationError} type="button">
          关闭
        </button>
      </div>
    );
  }
  if (!partialErrors.length) return null;
  return (
    <div className="api-warning">
      <AlertTriangle size={16} />部分功能暂不可用：
      <details>
        <summary>{partialErrors.map(([key]) => key).join(", ")}</summary>
        {partialErrors.map(([key, message]) => (
          <div key={key}><strong>{key}</strong>: {message}</div>
        ))}
      </details>
    </div>
  );
}
