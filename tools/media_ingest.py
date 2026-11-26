"""CN-1: Media Ingest -> Immutable Baseline Graph (G0).

Extracts timestamped scenes, speakers, and causal edges from media/transcript
inputs (.srt, .txt, .md, or video/document paths paired with .srt) into a
BaselineGraphPacket (branch_id="G0", immutable=True).
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

_SRT_TIME_RE = re.compile(
    r"(\d{2}):(\d{2}):(\d{2})[,.](\d{3})\s*-->\s*(\d{2}):(\d{2}):(\d{2})[,.](\d{3})"
)
_SPEAKER_PREFIX_RE = re.compile(r"^\s*(?:\[([A-Z0-9_ ]+)\]|([A-Z][A-Z0-9_ ]{1,24}):)\s*(.+)$")


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _hms_ms_to_ms(h: str, m: str, s: str, ms: str) -> int:
    return ((int(h) * 3600) + (int(m) * 60) + int(s)) * 1000 + int(ms)


def _extract_speakers_and_text(lines: list[str]) -> tuple[list[str], str]:
    speakers: list[str] = []
    cleaned: list[str] = []
    for raw in lines:
        line = raw.strip()
        if not line:
            continue
        m = _SPEAKER_PREFIX_RE.match(line)
        if m:
            spk = (m.group(1) or m.group(2)).strip().upper()
            if spk and spk not in speakers:
                speakers.append(spk)
            cleaned.append(m.group(3).strip())
        else:
            cleaned.append(line)
    return speakers, " ".join(cleaned).strip()


def _parse_srt(text: str) -> list[dict]:
    blocks = re.split(r"\r?\n\s*\r?\n", text.strip())
    scenes: list[dict] = []
    for block in blocks:
        lines = [ln.rstrip() for ln in block.splitlines() if ln.strip()]
        if not lines:
            continue
        time_idx = None
        start_ms = 0
        for idx, ln in enumerate(lines[:2]):
            m = _SRT_TIME_RE.search(ln)
            if m:
                time_idx = idx
                start_ms = _hms_ms_to_ms(m.group(1), m.group(2), m.group(3), m.group(4))
                break
        if time_idx is None:
            continue
        body_lines = lines[time_idx + 1 :]
        speakers, body = _extract_speakers_and_text(body_lines)
        if not body:
            continue
        scenes.append(
            {
                "id": f"E{len(scenes) + 1:02d}",
                "start_ms": start_ms,
                "speakers": speakers,
                "text": body,
            }
        )
    return scenes


def _parse_plain_text(text: str) -> list[dict]:
    paragraphs = [p.strip() for p in re.split(r"\r?\n\s*\r?\n", text.strip()) if p.strip()]
    scenes: list[dict] = []
    for idx, para in enumerate(paragraphs):
        speakers, body = _extract_speakers_and_text(para.splitlines())
        if not body:
            continue
        scenes.append(
            {
                "id": f"E{len(scenes) + 1:02d}",
                "start_ms": idx * 5000,
                "speakers": speakers,
                "text": body,
            }
        )
    return scenes


def ingest_media_to_baseline_graph(media_path: Path, srt_path: Path | None = None) -> dict:
    """Ingest a media or transcript file into an immutable G0 BaselineGraphPacket."""
    media = Path(media_path)
    if not media.exists():
        raise FileNotFoundError(f"Media file not found: {media}")

    source_sha256 = _sha256_file(media)
    transcript_path = Path(srt_path) if srt_path is not None else media
    if not transcript_path.exists():
        raise FileNotFoundError(f"Subtitle/transcript file not found: {transcript_path}")

    suffix = transcript_path.suffix.lower()
    if suffix == ".srt":
        scenes = _parse_srt(transcript_path.read_text(encoding="utf-8", errors="replace"))
    elif suffix in {".txt", ".md", ".vtt"}:
        scenes = _parse_plain_text(transcript_path.read_text(encoding="utf-8", errors="replace"))
    else:
        scenes = [
            {
                "id": "E01",
                "start_ms": 0,
                "speakers": [],
                "text": f"Media asset ingested: {media.name}",
            }
        ]

    if not scenes:
        scenes = [
            {
                "id": "E01",
                "start_ms": 0,
                "speakers": [],
                "text": f"Empty transcript for {media.name}",
            }
        ]

    causal_edges = [
        {"from": scenes[i]["id"], "to": scenes[i + 1]["id"], "kind": "ENABLES"}
        for i in range(len(scenes) - 1)
    ]

    return {
        "schema_version": "7.0",
        "branch_id": "G0",
        "parent_branch_id": None,
        "immutable": True,
        "source_sha256": source_sha256,
        "scenes": scenes,
        "causal_edges": causal_edges,
    }
