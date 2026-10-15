"""G14-c image description via DeepSeek's hosted vision model.

Contract (PROJECT_STATUS section 12, decisions 6 + acceptance gate 6):
image bytes leave the machine only through this module, only when the
independent attachment_vision_enabled setting is on, and every call is
audited as purpose="image_description". The model id defaults to
deepseek-v4-flash-vision-exp and can be overridden with
DEEPSEEK_MODEL_VISION_NAME.
"""

from __future__ import annotations

import base64
import mimetypes
import os
from pathlib import Path
from typing import Any

from src.llm_spend_guard import SpendLimitExceeded

DEFAULT_VISION_MODEL = "deepseek-v4-flash-vision-exp"
# Output cap for one image description; also the spend-reservation bound.
_VISION_MAX_TOKENS = 1200

_DESCRIPTION_PROMPT = (
    "请为学习资料索引生成这张图片的中文文字描述：提取图中全部可读文字、"
    "图表结构与关键信息，输出纯文本段落（不要寒暄、不要 markdown 标题）。"
    "描述将用于关键词与向量检索，请保留具体术语。"
)


class VisionDescriptionError(RuntimeError):
    """Raised when the vision API call fails."""


def vision_model_name() -> str:
    return (
        os.getenv("DEEPSEEK_MODEL_VISION_NAME", "").strip()
        or DEFAULT_VISION_MODEL
    )


def _data_url(image_path: Path) -> str:
    mime_type = mimetypes.guess_type(str(image_path))[0] or "application/octet-stream"
    payload = base64.b64encode(image_path.read_bytes()).decode("ascii")
    return f"data:{mime_type};base64,{payload}"


def describe_image_with_deepseek(image_path: Path) -> str:
    """Send one image to the vision model and return its text description."""
    from src.llm_client import _classify_error, get_provider_settings

    try:
        client = get_provider_settings("deepseek")
    except RuntimeError as exc:
        raise VisionDescriptionError(f"provider unavailable: {exc}") from exc

    try:
        from openai import OpenAI

        # Vision is a paid call too: reserve it under the same hard cap before
        # any request is sent (image payload charged as a conservative proxy).
        from src.llm_spend_guard import reserve_call

        reserve_call(
            # base64 expands by ~4/3; x2 is a deliberately conservative proxy.
            prompt_chars=len(_DESCRIPTION_PROMPT) + image_path.stat().st_size * 2,
            max_tokens=_VISION_MAX_TOKENS,
            attempts=max(1, client.max_retries + 1),
            purpose="vision:image_description",
            model=vision_model_name(),
            call_id=f"vision:{image_path.name}",
        )

        api = OpenAI(
            api_key=client.api_key,
            base_url=client.base_url,
            timeout=max(client.timeout_seconds, 60.0),
            max_retries=client.max_retries,
        )
        # The multimodal content-block shape is valid on the wire but the
        # openai SDK's TypedDict union cannot infer it cleanly.
        messages: list[dict[str, Any]] = [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": _DESCRIPTION_PROMPT},
                    {
                        "type": "image_url",
                        "image_url": {"url": _data_url(image_path)},
                        "detail": "high",
                    },
                ],
            }
        ]
        response = api.chat.completions.create(
            model=vision_model_name(),
            messages=messages,  # type: ignore[arg-type]
            max_tokens=_VISION_MAX_TOKENS,
            extra_body={"thinking": {"type": "disabled"}},
        )
        description = (response.choices[0].message.content or "").strip()
    except SpendLimitExceeded:
        # A spend stop is not a provider failure: keep it distinguishable.
        raise
    except Exception as exc:  # noqa: BLE001 - normalized into audit trail
        raise VisionDescriptionError(_classify_error(exc)) from exc

    if not description:
        raise VisionDescriptionError("vision model returned an empty description")
    return description
