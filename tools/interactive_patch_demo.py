"""Run M4-D's model-free patch/validate/retain-or-rollback demonstration.

python -m tools.interactive_patch_demo --out D:/validation/new-patch-demo
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
from pathlib import Path
from types import SimpleNamespace

from src.interactive_patch import TextEdit, prepare_patch, source_hash
from src.interactive_restore import RestoreRequest

BASE = """<!doctype html><html><head><style>
body{margin:16px;font:16px system-ui}button,input{font:inherit;min-height:44px;min-width:44px}main{max-width:100%}
</style></head><body><main><h1>Linear function</h1><label>x <input id="x" type="number" value="1"></label>
<output id="y"></output><button id="reset">Reset</button><!-- controls -->
<script>const x=document.querySelector('#x'),y=document.querySelector('#y');
function render(){y.textContent=String(2*Number(x.value)+1);window.studyUI.setState({x:Number(x.value)});}
x.addEventListener('input',render);document.querySelector('#reset').addEventListener('click',()=>{x.value='1';render();});
/* handlers */render();</script></main></body></html>"""


def saved_turn(html: str, revision: int):
    payload = dict(
        type="interactive",
        id="linear-demo",
        revision=revision,
        title="Linear function",
        summary="Explore y=2x+1",
        html=html,
    )
    return SimpleNamespace(
        id=f"turn-{revision}",
        status="completed",
        assistant_message="```study-ui\n" + json.dumps(payload) + "\n```",
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=False)
    good = prepare_patch(
        [saved_turn(BASE, 1)],
        RestoreRequest("linear-demo", 1),
        source_hash(BASE),
        [
            TextEdit("<!-- controls -->", '<button id="double">Double x</button>'),
            TextEdit(
                "/* handlers */",
                "document.querySelector('#double').addEventListener('click',()=>{x.value=String(Number(x.value)*2);render();});",
            ),
        ],
    )
    broken = prepare_patch(
        [saved_turn(BASE, 1), saved_turn(good.html, 2)],
        RestoreRequest("linear-demo", 2),
        good.sha256,
        [TextEdit("2*Number(x.value)+1", "3*Number(x.value)+1")],
    )
    cases = [
        ("base", BASE, 1),
        ("added-control", good.html, 2),
        ("broken-calculation", broken.html, 3),
    ]
    manifest = []
    for name, html, revision in cases:
        (out / f"{name}.html").write_bytes(html.encode("utf-8"))
        manifest.append(
            dict(
                name=name,
                file=f"{name}.html",
                revision=revision,
                sha256=source_hash(html),
            )
        )
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    from tools.m4c3_results import browser_environment

    env = browser_environment({"M4D_PATCH_DEMO_DIR": str(out)})
    frontend = Path(__file__).resolve().parents[1] / "frontend"
    executable = "npx.cmd" if os.name == "nt" else "npx"
    command = [
        executable,
        "playwright",
        "test",
        "--config=playwright.m4c-offline.config.ts",
        "e2e/acceptance/incrementalPatch.spec.ts",
        "--project=desktop-chromium",
        "--reporter=line",
    ]
    completed = subprocess.run(command, cwd=frontend, env=env, check=False)
    if completed.returncode:
        return completed.returncode
    reports = json.loads((out / "browser-results.json").read_text(encoding="utf-8"))
    # A candidate is publishable only when every explicit viewport report passes.
    assert len(reports) == 6
    accepted = all(r["passed"] for r in reports if r["name"] == "added-control")
    rejected = all(
        not r["passed"] for r in reports if r["name"] == "broken-calculation"
    )
    assert all(r["passed"] for r in reports if r["name"] == "base")
    assert accepted and rejected
    versions = out / "accepted-versions"
    versions.mkdir()
    (versions / "v1.html").write_bytes(BASE.encode("utf-8"))
    (versions / "v2.html").write_bytes(good.html.encode("utf-8"))
    result = dict(
        component_id="linear-demo",
        active_revision=2,
        active_file="accepted-versions/v2.html",
        active_sha256=good.sha256,
        accepted_revision=2,
        rejected_revision=3,
        rollback_revision=2,
        model_calls=0,
        report="browser-results.json",
    )
    (out / "result.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
