"""Offline prototype acceptance; no model or backend calls."""

import json
import os
from pathlib import Path
from playwright.sync_api import sync_playwright

root = Path(__file__).resolve().parent
results = []
with sync_playwright() as p:
    browser = p.chromium.launch()
    for width, height, name in [(1440, 900, "desktop"), (375, 812, "mobile")]:
        page = browser.new_page(
            viewport={"width": width, "height": height}, reduced_motion="reduce"
        )
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.goto(os.environ["DESIGN_PREVIEW_URL"] + "dir-3.html")
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
        assert page.locator("#send").is_disabled()
        page.locator("#prompt").fill("   ")
        assert page.locator("#send").is_disabled()
        page.locator("#prompt").fill("中文输入")
        page.locator("#prompt").dispatch_event("compositionstart")
        page.locator("#prompt").press("Enter")
        assert page.locator("#extra .user").count() == 0
        page.locator("#prompt").dispatch_event("compositionend")
        page.locator("#prompt").fill("<script>literal text</script>")
        page.locator("#send").click()
        assert (
            page.locator("#extra .user").inner_text() == "<script>literal text</script>"
        )
        assert page.locator("#extra script").count() == 0
        assert "本地预置演示回复" in page.locator("#extra").inner_text()
        page.locator("#file").set_input_files(
            {"name": "demo.txt", "mimeType": "text/plain", "buffer": b"local demo"}
        )
        assert "仅本地展示，不会上传" in page.locator("#file-note").inner_text()
        page.locator(".top-actions [data-action=new]").click()
        assert page.locator("#empty").is_visible()
        assert page.locator("#extra .user").count() == 0
        assert page.locator("#file-note").inner_text() == ""
        page.locator(".top-actions [data-action=reset]").click()
        assert page.locator("#sample").is_visible()
        page.locator("[data-passage=checkpoint]").click()
        assert "selected" in page.locator("#checkpoint").get_attribute("class")
        if width < 700:
            assert page.locator("#source-pane").is_visible()
            assert not page.locator("#answer-pane").is_visible()
            page.screenshot(path=root / "dir-3-mobile-source.png", full_page=True)
            page.locator("#answer-tab").click()
            assert page.locator("#answer-pane").is_visible()
        else:
            page.locator(".top-actions [data-action=source]").click()
            assert not page.locator("#source-pane").is_visible()
            page.locator(".top-actions [data-action=source]").click()
            assert page.locator("#source-pane").is_visible()
            page.locator("[data-action=about]").click()
            assert page.locator("#about").is_visible()
            page.keyboard.press("Escape")
            assert not page.locator("#about").is_visible()
        page.locator(".top-actions [data-action=reset]").click()
        page.locator("#concurrency").evaluate(
            "el=>{document.querySelectorAll('.passage').forEach(p=>p.classList.remove('selected'));el.classList.add('selected');document.querySelector('.source-body').scrollTop=0}"
        )
        page.screenshot(path=root / f"dir-3-{name}.png", full_page=True)
        small = page.locator("button:visible").evaluate_all(
            "els=>els.filter(e=>{let r=e.getBoundingClientRect();return r.width<43.9 || r.height<43.9}).map(e=>({label:e.getAttribute('aria-label')||e.textContent,width:e.getBoundingClientRect().width,height:e.getBoundingClientRect().height}))"
        )
        assert not small, small
        assert not errors, errors
        results.append(
            {
                "viewport": name,
                "size": [width, height],
                "assertions": "PASS",
                "console_errors": errors,
                "undersized_buttons": small,
            }
        )
        page.close()
    browser.close()
(root / "dir-3-verification.json").write_text(
    json.dumps(
        {"checks": results, "model_calls": 0, "backend_calls": 0},
        ensure_ascii=False,
        indent=2,
    ),
    encoding="utf-8",
)
print(json.dumps(results, ensure_ascii=False))
