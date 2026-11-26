"""Automated Studio v2 UI Contract & Parity Gate.

Checks:
1. Zero `!important` overrides in `ui/*.css`.
2. Minimum readable font floor (>= 11px) across canonical Studio v2 stylesheets.
3. 100% route & file parity between `tools/v2_page.html`, `tools/studio_canon_routes.py`, and `ui/`.
4. ES module syntax check (`node --check`) on every `ui/*.js` file when Node is available.
"""
from __future__ import annotations

import pathlib
import re
import shutil
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
UI_DIR = ROOT / "ui"
CANONICAL_CSS = (
    "tokens.css",
    "shell.css",
    "compose.css",
    "prose.css",
    "char_switchyard.css",
    "story_graph_canvas.css",
    "graph.css",
    "timeline.css",
)
SUB_11PX_FONT_RE = re.compile(r"(?:^|[\s:])([0-9](?:\.\d+)?|10(?:\.\d+)?)px\b")


def check_no_important() -> list[str]:
    errors: list[str] = []
    for css_path in sorted(UI_DIR.glob("*.css")):
        for lineno, line in enumerate(css_path.read_text(encoding="utf-8").splitlines(), 1):
            if "!important" in line:
                errors.append(f"{css_path.relative_to(ROOT).as_posix()}:{lineno}: contains !important")
    return errors


def check_min_font_floor() -> list[str]:
    errors: list[str] = []
    for name in CANONICAL_CSS:
        css_path = UI_DIR / name
        if not css_path.is_file():
            errors.append(f"Missing canonical stylesheet: ui/{name}")
            continue
        for lineno, line in enumerate(css_path.read_text(encoding="utf-8").splitlines(), 1):
            low = line.lower()
            if ("font-size" in low or re.search(r"\bfont\s*:", low)) and SUB_11PX_FONT_RE.search(low):
                errors.append(f"{css_path.relative_to(ROOT).as_posix()}:{lineno}: sub-11px font -> {line.strip()}")
    return errors


def check_v2_route_parity() -> list[str]:
    errors: list[str] = []
    v2_html = (ROOT / "tools" / "v2_page.html").read_text(encoding="utf-8")
    routes_py = (ROOT / "tools" / "studio_canon_routes.py").read_text(encoding="utf-8")
    asset_urls = re.findall(r'["\'](/assets/v2/[^"\'?]+)(?:\?[^"\']*)?["\']', v2_html)
    if not asset_urls:
        return ["No /assets/v2/ assets found in tools/v2_page.html"]
    for url in asset_urls:
        if f'"{url}"' not in routes_py and f"'{url}'" not in routes_py:
            errors.append(f"tools/v2_page.html references {url} missing from STUDIO_ASSET_MAP")
        rel_ui = UI_DIR / url.removeprefix("/assets/v2/")
        if not rel_ui.is_file():
            errors.append(f"tools/v2_page.html references {url} missing on disk at {rel_ui.relative_to(ROOT).as_posix()}")
    return errors


def check_js_syntax() -> list[str]:
    node = shutil.which("node")
    if not node:
        return []
    errors: list[str] = []
    for js_path in sorted(UI_DIR.glob("*.js")):
        proc = subprocess.run([node, "--check", str(js_path)], capture_output=True, text=True)
        if proc.returncode != 0:
            errors.append(f"{js_path.relative_to(ROOT).as_posix()}: {proc.stderr.strip()}")
    return errors


def main() -> int:
    failures: list[str] = []
    gates = [
        ("zero_important_css", check_no_important),
        ("min_11px_font_floor", check_min_font_floor),
        ("v2_route_parity", check_v2_route_parity),
        ("js_module_syntax", check_js_syntax),
    ]
    for label, fn in gates:
        errs = fn()
        if errs:
            print(f"[FAIL] {label} ({len(errs)})")
            for e in errs:
                print(f"  - {e}")
            failures.extend(errs)
        else:
            print(f"[PASS] {label}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
