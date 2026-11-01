"""Offline Playwright interaction checks for the Night Flight design direction."""

import json
import os
from pathlib import Path
from playwright.sync_api import sync_playwright

root = Path(__file__).resolve().parent
checks = []
with sync_playwright() as p:
    browser = p.chromium.launch()
    for width, height, name in [(1440, 900, "desktop"), (375, 812, "mobile")]:
        page = browser.new_page(viewport={"width": width, "height": height})
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.goto(
            os.environ["DESIGN_PREVIEW_URL"] + "dir-2.html", wait_until="networkidle"
        )
        page.screenshot(
            path=str(root / f"dir-2-{name}.png"), full_page=False, animations="disabled"
        )
        page.screenshot(
            path=str(root / f"dir-2-{name}-full.png"),
            full_page=True,
            animations="disabled",
        )
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth"), name
        checks.append(f"{name}: no horizontal overflow")
        assert page.locator("#send").is_disabled()
        page.locator("#prompt").fill("   ")
        assert page.locator("#send").is_disabled()
        checks.append(f"{name}: empty and whitespace submit disabled")
        page.locator("#prompt").fill("中文输入")
        page.locator("#prompt").dispatch_event("compositionstart")
        page.locator("#prompt").press("Enter")
        assert page.locator("#turns .turn").count() == 0
        page.locator("#prompt").dispatch_event("compositionend")
        page.locator("#prompt").press("Enter")
        assert page.locator("#turns .turn").count() == 2
        assert "本地预置演示" in page.locator("#turns").inner_text()
        checks.append(f"{name}: IME safe and explicit demo reply")
        page.get_by_role("button", name="重置示例", exact=True).click()
        if width == 1440:
            page.locator("#source-toggle").click()
            assert page.locator("#sources").is_hidden()
        page.locator("#source-toggle").click()
        assert page.locator("#sources").is_visible()
        if width == 375:
            assert page.locator("#source-close").evaluate(
                "el => el === document.activeElement"
            )
            page.screenshot(
                path=str(root / "dir-2-mobile-source.png"), animations="disabled"
            )
            page.keyboard.press("Escape")
            assert page.locator("#sources").is_hidden()
            assert page.locator("#source-toggle").evaluate(
                "el => el === document.activeElement"
            )
        checks.append(f"{name}: source pane and close/focus return")
        page.locator("#file").set_input_files(
            {"name": "notes.txt", "mimeType": "text/plain", "buffer": b"demo"}
        )
        assert "notes.txt" in page.locator("#attachment-name").inner_text()
        assert "未上传" in page.locator("#attachment-name").inner_text()
        page.locator("#remove-file").click()
        assert page.locator("#attachment").is_hidden()
        checks.append(f"{name}: local file selection and removal")
        page.locator("#new-chat").click()
        assert page.locator("#sample").is_hidden()
        assert page.locator("#empty").is_visible()
        page.get_by_role("button", name="回到 WAL 示例", exact=True).click()
        assert page.locator("#sample").is_visible()
        checks.append(f"{name}: new conversation and reset")
        page.locator("#text-size").click()
        assert page.locator("#text-size").get_attribute("aria-pressed") == "true"
        checks.append(f"{name}: font size toggle")
        assert not errors, errors
        checks.append(f"{name}: zero page errors")
        page.close()
    browser.close()
(root / "dir-2-check.json").write_text(
    json.dumps({"result": "PASS", "checks": checks}, ensure_ascii=False, indent=2),
    encoding="utf-8",
)
print(f"PASS {len(checks)} checks, desktop + mobile")
