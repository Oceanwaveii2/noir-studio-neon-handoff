"""Rebuild the typed draft from the marked PDF, with the author's corrections in red."""

from __future__ import annotations

import html
import sys
from pathlib import Path

import pymupdf

PDF = Path(r"C:\NOIR_LOCAL\Downloads\Corrections II.pdf")
OUT = Path(__file__).resolve().parents[1] / "work" / "americandad" / "TYPED_DRAFT_with_red.html"


def colour(span) -> str:
    value = span["color"]
    r, g, b = (value >> 16) & 255, (value >> 8) & 255, value & 255
    if r > 120 and r > g * 1.4 and r > b * 1.4:
        return "red"
    if g > 100 and g > r * 1.4 and g > b * 1.2:
        return "green"
    return "black"


def main() -> int:
    doc = pymupdf.open(PDF)
    pages = []
    for number, page in enumerate(doc, 1):
        lines = []
        data = page.get_text("dict")
        blocks = sorted(data["blocks"], key=lambda block: (round(block["bbox"][1] / 6), block["bbox"][0]))
        for block in blocks:
            for line in block.get("lines", []):
                pieces = []
                for span in line["spans"]:
                    text = span["text"]
                    if not text.strip():
                        pieces.append(html.escape(text))
                        continue
                    kind = colour(span)
                    if kind == "black":
                        pieces.append(html.escape(text))
                    else:
                        pieces.append(f'<span class="{kind}">{html.escape(text)}</span>')
                joined = "".join(pieces).strip()
                if joined:
                    lines.append(joined)
            lines.append("")
        pages.append((number, lines))

    body = []
    for number, lines in pages:
        body.append(f'<section><h2>Page {number}</h2>')
        body.append("<p>" + "<br>\n".join(lines) + "</p></section>")

    document = f"""<!doctype html>
<html><head><meta charset="utf-8"><title>Typed draft with red corrections</title>
<style>
 body {{ background:#f8fafc; color:#0f172a; font: 15px/1.55 Georgia, serif; max-width: 900px; margin: 40px auto; padding: 0 20px; }}
 h1 {{ font: 600 24px/1.2 system-ui, sans-serif; }}
 h2 {{ font: 600 14px/1.2 system-ui, sans-serif; color:#475569; margin-top: 32px; text-transform: uppercase; letter-spacing:.08em; }}
 .red {{ color:#dc2626; font-weight:600; }}
 .green {{ color:#15803d; font-weight:600; }}
 section {{ border-top:1px solid #e2e8f0; }}
 .legend {{ font: 13px system-ui, sans-serif; color:#475569; }}
</style></head><body>
<h1>Your typed draft — red marks are your corrections</h1>
<p class="legend">Black = what you typed. <span class="red">Red</span> = your corrections and notes. <span class="green">Green</span> = directions.</p>
{''.join(body)}
</body></html>
"""
    OUT.write_text(document, encoding="utf-8")
    print(f"written: {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
