"""Extract English 1993 last draft of Pulp Fiction from user-uploaded PDF using Windows Media OCR."""

from __future__ import annotations

import asyncio
import io
import sys
import time
from pathlib import Path
import fitz
from PIL import Image
import winocr

import sys as _sys

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in _sys.path:
    _sys.path.insert(0, str(_REPO_ROOT))

from prose_engine import paths as prose_paths

PDF_PATH = Path(
    r"C:\NOIR_LOCAL\.gemini\antigravity\brain\f8842a47-08ce-4d96-a6b6-3a3d89029b1e\.user_uploaded\media_1794069748807_6ef193f3.pdf"
)
OUT_PATH = prose_paths.books("text", "pulp_fiction_quentin_tarantino.txt")


async def extract_all() -> None:
    t0 = time.time()
    doc = fitz.open(PDF_PATH)
    total_pages = len(doc)
    print(f"Starting OCR extraction of {total_pages} pages...", flush=True)

    extracted_pages = []
    for page_idx in range(total_pages):
        page = doc[page_idx]
        pix = page.get_pixmap(dpi=150)
        img = Image.open(io.BytesIO(pix.tobytes("png")))
        res = await winocr.recognize_pil(img, lang="en-US")

        page_lines = [line.text.rstrip() for line in res.lines if line.text.strip()]
        page_text = "\n".join(page_lines)
        extracted_pages.append(page_text)

        if (page_idx + 1) % 20 == 0 or page_idx == total_pages - 1:
            print(
                f"Processed {page_idx + 1}/{total_pages} pages ({time.time() - t0:.1f}s)",
                flush=True,
            )

    full_text = "\n\n".join(extracted_pages)
    OUT_PATH.write_text(full_text, encoding="utf-8")

    words = len(full_text.split())
    chars = len(full_text)
    print(
        f"Extracted {total_pages} pages, {words:,} words, {chars:,} chars -> {OUT_PATH}",
        flush=True,
    )
    print(f"Total time: {time.time() - t0:.1f}s", flush=True)


if __name__ == "__main__":
    asyncio.run(extract_all())
