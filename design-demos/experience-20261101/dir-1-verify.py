"""Offline prototype interaction checks. No app backend or model calls."""

import json
import os
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent
BASE = os.environ["DESIGN_PREVIEW_URL"]
results = []
with sync_playwright() as p:
    browser = p.chromium.launch()
    for width, height in ((1440, 900), (375, 812)):
        page = browser.new_page(viewport={"width": width, "height": height})
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.goto(BASE + "dir-1.html")
        page.wait_for_load_state("networkidle")
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
        page.screenshot(
            path=str(ROOT / f"dir-1-{'desktop' if width == 1440 else 'mobile'}.png"),
            full_page=True,
        )
        page.get_by_role("button", name="查看来源", exact=True).click()
        assert page.locator("#sources").is_visible()
        assert (
            page.locator("#sources a").get_attribute("href")
            == "https://www.sqlite.org/wal.html"
        )
        page.get_by_role("button", name="关闭来源").click()
        assert page.locator("#send").is_disabled()
        page.locator("#message").fill("   ")
        assert page.locator("#send").is_disabled()
        page.locator("#message").fill("中文输入")
        page.locator("#message").dispatch_event("compositionstart")
        page.locator("#message").press("Enter")
        assert page.locator("#messages").inner_text() == ""
        page.locator("#message").dispatch_event("compositionend")
        page.locator("#message").press("Enter")
        assert "中文输入" in page.locator("#messages").inner_text()
        assert "本地演示回复" in page.locator("#messages").inner_text()
        page.locator("#file").set_input_files(
            {"name": "notes.txt", "mimeType": "text/plain", "buffer": b"offline only"}
        )
        assert "notes.txt" in page.locator("#file-name").inner_text()
        assert "不上传" in page.locator("#file-name").inner_text()
        if width == 375:
            page.get_by_role("button", name="打开会话导航").click()
        page.get_by_role("button", name="阅读设置", exact=True).click()
        page.locator("#text-size").select_option("21")
        assert (
            page.locator(".answer").evaluate("el => getComputedStyle(el).fontSize")
            == "21px"
        )
        page.get_by_role("button", name="关闭设置").click()
        if width == 375:
            page.get_by_role("button", name="打开会话导航").click()
        page.get_by_role("button", name="新对话", exact=True).click()
        assert page.locator("#empty").is_visible()
        assert page.locator("#messages").inner_text() == ""
        assert page.locator("#file-name").is_hidden()
        page.get_by_role("button", name="回到 WAL 示例").click()
        assert page.locator("#sample").is_visible()
        page.get_by_role("button", name="给我一个具体例子", exact=True).click()
        assert page.locator("#message").input_value() == "给我一个具体例子"
        assert not errors, errors
        results.append(
            {
                "viewport": [width, height],
                "checks": 17,
                "page_errors": errors,
                "result": "pass",
            }
        )
        page.close()
    browser.close()
(ROOT / "dir-1-verification.json").write_text(
    json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8"
)
print(json.dumps(results, ensure_ascii=False))
