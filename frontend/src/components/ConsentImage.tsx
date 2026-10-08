import { useState } from "react";
import { safeImageUrl } from "../features/answer-ui/answerUiProtocol";

/** Browser-side resource consent, independent of the Agent's web-search policy.
 * No model-supplied remote URL may become an img request until explicitly approved.
 * Consent is bound to the exact URL; changing the URL cannot reuse an old approval.
 */
export function ConsentImage({ src, alt = "", onFailure }: {
  src?: string;
  alt?: string;
  onFailure?: () => void;
}) {
  const [approvedUrl, setApprovedUrl] = useState<string | null>(null);
  const [failedUrl, setFailedUrl] = useState<string | null>(null);
  if (!safeImageUrl(src)) {
    return <span role="status">图片地址不可用：{alt || "未命名图片"}</span>;
  }
  if (failedUrl === src) {
    return <span role="status">图片暂时无法显示：{alt || "未命名图片"}</span>;
  }
  // Local packaged assets are controlled by this app. All remote HTTPS URLs,
  // including URLs authored by a model in Markdown, require a user click.
  const isLocalAsset = src.startsWith("/assets/");
  if (!isLocalAsset && approvedUrl !== src) {
    const hostname = new URL(src).hostname;
    return (
      <span className="answer-external-image-consent">
        <span>外部图片来自 {hostname}。点击后才会向该网站发送请求。</span>
        <button type="button" onClick={() => setApprovedUrl(src)}>加载外部图片</button>
      </span>
    );
  }
  return <img src={src} alt={alt} loading="lazy" referrerPolicy="no-referrer"
    onError={() => { setFailedUrl(src); onFailure?.(); }} />;
}
