"""Offline multimodal audio/evidence analyzer & versioned expressive envelope (TI-1 promoted stack)."""
from __future__ import annotations

from collections import Counter
from dataclasses import asdict, dataclass, field
import hashlib
import json
import os
from pathlib import Path
import re
import struct
from typing import Any, Dict, List, Optional, Sequence
import wave


DEFAULT_HF_HOME = Path(os.environ.get("HF_HOME") or (Path.home() / ".cache" / "huggingface"))


def _distance(left, right):
    previous = list(range(len(right) + 1))
    for i, a in enumerate(left, 1):
        current = [i]
        for j, b in enumerate(right, 1):
            current.append(min(current[-1] + 1, previous[j] + 1, previous[j - 1] + (a != b)))
        previous = current
    return previous[-1]


def compare_ocr(reference: str, candidate: str) -> dict:
    """Compare OCR text against an independently corrected reference without auto-promoting inventions."""
    words = lambda s: re.findall(r"\b\w+\b", s.casefold())
    rw, cw = words(reference), words(candidate)
    ref_lines = [x.strip() for x in reference.splitlines() if x.strip()]
    out_lines = [x.strip() for x in candidate.splitlines() if x.strip()]
    left, right = Counter(ref_lines), Counter(out_lines)
    shared_order_left = [x for x in ref_lines if x in right]
    shared_order_right = [x for x in out_lines if x in left]
    return {
        "character_errors": _distance(reference, candidate),
        "character_error_rate": _distance(reference, candidate) / len(reference) if reference else None,
        "word_errors": _distance(rw, cw),
        "word_error_rate": _distance(rw, cw) / len(rw) if rw else None,
        "omitted_lines": list((left - right).elements()),
        "candidate_only_lines": list((right - left).elements()),
        "shared_line_order_matches": shared_order_left == shared_order_right,
        "note": "Candidate-only lines are possible inventions or OCR errors and need human inspection.",
    }


def compare_timed(reference: list[dict], candidate: list[dict]) -> dict:
    """Compare aligned timed events by ID without inferring speakers or sound from text."""
    def validate(rows):
        result = {}
        for r in rows:
            if not isinstance(r.get("id"), str) or not r["id"] or r["id"] in result:
                raise ValueError("Each event needs a unique ID.")
            if not 0 <= r["start"] < r["end"]:
                raise ValueError("Event times must be nonnegative and ordered.")
            result[r["id"]] = r
        return result

    a, b = validate(reference), validate(candidate)
    pairs = []
    for key in sorted(a.keys() & b.keys()):
        x, y = a[key], b[key]
        pairs.append({
            "id": key,
            "start_error_seconds": abs(x["start"] - y["start"]),
            "end_error_seconds": abs(x["end"] - y["end"]),
            "speaker_matches": x.get("speaker") == y.get("speaker"),
            "label_matches": x.get("label") == y.get("label"),
            "text_matches": x.get("text") == y.get("text"),
        })
    return {
        "matched": pairs,
        "missing_ids": sorted(a.keys() - b.keys()),
        "extra_ids": sorted(b.keys() - a.keys()),
        "note": "Matches require independently aligned event IDs; overlap is preserved.",
    }


@dataclass(frozen=True)
class Evidence:
    """Opt-in OCR or audio extraction record; must be permitted & reviewed before context export."""

    kind: str
    source_id: str
    locator: str
    extraction_revision: str
    raw: str
    reviewed: str = ""
    reviewer: str = ""
    permission: str = "unknown"

    def __post_init__(self):
        if self.kind not in ("ocr", "audio") or not all((self.source_id, self.locator, self.extraction_revision)):
            raise ValueError("Evidence requires kind, source, locator and extraction revision.")
        if self.permission not in ("unknown", "denied", "permitted"):
            raise ValueError("Invalid permission state.")

    def context(self) -> dict:
        if self.permission != "permitted" or not self.reviewer.strip() or not self.reviewed.strip():
            raise PermissionError("Evidence must be permitted and reviewed before context export.")
        return {
            "source_id": self.source_id,
            "locator": self.locator,
            "extraction_revision": self.extraction_revision,
            "reviewer": self.reviewer,
            "text": self.reviewed,
            "raw_sha256": hashlib.sha256(self.raw.encode("utf-8")).hexdigest(),
        }

    def record(self) -> dict:
        return asdict(self)


def save_evidence(record: Evidence, path: str | Path) -> None:
    """Write one immutable raw/reviewed record, refusing an existing destination."""
    with Path(path).open("x", encoding="utf-8") as stream:
        json.dump(record.record(), stream, ensure_ascii=False, indent=2)
        stream.write("\n")


def load_evidence(path: str | Path) -> Evidence:
    return Evidence(**json.loads(Path(path).read_text(encoding="utf-8")))


@dataclass(frozen=True)
class PauseWindow:
    start_sec: float
    end_sec: float
    duration_sec: float
    rms_db: float


@dataclass
class ClipExpressiveEnvelope:
    """Versioned multimodal clip metadata usable for comedic hold/pause timing without leaking external lore."""

    source_path: str
    source_sha256: str
    duration_sec: float
    sample_rate: int
    pause_windows: List[PauseWindow] = field(default_factory=list)
    peak_rms_db: float = -60.0
    acoustic_tags: List[Dict[str, Any]] = field(default_factory=list)
    transcript_segments: List[Dict[str, Any]] = field(default_factory=list)
    speaker_embedding_dim: Optional[int] = None
    provenance: Dict[str, Any] = field(default_factory=dict)
    schema_version: int = 1

    def to_rhythm_guidance(self) -> Dict[str, Any]:
        longest = max((p.duration_sec for p in self.pause_windows), default=0.0)
        return {
            "schema_version": self.schema_version,
            "duration_sec": self.duration_sec,
            "pause_count": len(self.pause_windows),
            "longest_hold_sec": round(longest, 3),
            "top_acoustic_tags": self.acoustic_tags[:3],
            "cues": [
                {
                    "kind": "hold_beat",
                    "start_sec": p.start_sec,
                    "duration_sec": p.duration_sec,
                    "instruction": f"Hold acoustic pause {p.duration_sec:.2f}s at {p.start_sec:.2f}s before delivery.",
                }
                for p in self.pause_windows[:4]
            ],
        }


def resolve_hf_snapshot(repo_folder: str, hf_home: Path = DEFAULT_HF_HOME) -> Optional[Path]:
    """Resolve an offline cached HuggingFace snapshot via refs/main first, checking config presence."""
    base = Path(hf_home) / "hub" / repo_folder
    ref = base / "refs" / "main"
    if ref.is_file():
        candidate = base / "snapshots" / ref.read_text(encoding="utf-8").strip()
        if candidate.is_dir():
            return candidate
    snaps_dir = base / "snapshots"
    if not snaps_dir.is_dir():
        return None
    valid = [p for p in sorted(snaps_dir.iterdir()) if (p / "config.json").is_file() or (p / "hyperparams.yaml").is_file()]
    return valid[-1] if valid else None


def detect_wav_pauses(
    wav_path: Path | str,
    *,
    frame_ms: float = 100.0,
    silence_threshold_rms: float = 0.015,
    min_pause_sec: float = 0.35,
) -> tuple[float, int, float, List[PauseWindow]]:
    """Compute exact RMS energy contour and silent pause windows from a local PCM WAV file."""
    path = Path(wav_path)
    with wave.open(str(path), "rb") as wf:
        channels = wf.getnchannels()
        sampwidth = wf.getsampwidth()
        sr = wf.getframerate()
        nframes = wf.getnframes()
        raw = wf.readframes(nframes)

    if sampwidth != 2:
        raise ValueError("detect_wav_pauses currently supports 16-bit PCM WAV streams.")
    total_samples = len(raw) // 2
    samples = struct.unpack(f"<{total_samples}h", raw)
    if channels > 1:
        mono = [sum(samples[i : i + channels]) / (channels * 32768.0) for i in range(0, total_samples, channels)]
    else:
        mono = [s / 32768.0 for s in samples]

    duration_sec = round(len(mono) / max(1, sr), 3)
    win = max(1, int(sr * (frame_ms / 1000.0)))
    peak_rms = 1e-6
    pauses: List[PauseWindow] = []
    cur_start: Optional[float] = None
    cur_rms: List[float] = []

    import math

    for idx in range(0, len(mono), win):
        chunk = mono[idx : idx + win]
        if not chunk:
            continue
        rms = math.sqrt(sum(v * v for v in chunk) / len(chunk))
        peak_rms = max(peak_rms, rms)
        t_start = idx / sr
        t_end = (idx + len(chunk)) / sr
        if rms <= silence_threshold_rms:
            if cur_start is None:
                cur_start = t_start
            cur_rms.append(rms)
        else:
            if cur_start is not None and (t_start - cur_start) >= min_pause_sec:
                mean_r = max(1e-6, sum(cur_rms) / len(cur_rms))
                pauses.append(PauseWindow(round(cur_start, 3), round(t_start, 3), round(t_start - cur_start, 3), round(20 * math.log10(mean_r), 2)))
            cur_start = None
            cur_rms = []

    if cur_start is not None and (duration_sec - cur_start) >= min_pause_sec:
        mean_r = max(1e-6, sum(cur_rms) / max(1, len(cur_rms)))
        pauses.append(PauseWindow(round(cur_start, 3), duration_sec, round(duration_sec - cur_start, 3), round(20 * math.log10(mean_r), 2)))

    peak_db = round(20 * math.log10(max(1e-6, peak_rms)), 2)
    return duration_sec, sr, peak_db, pauses


_CLAP_DEFAULT_LABELS: Sequence[str] = (
    "spoken comedic dialogue",
    "audience laughter or chuckle",
    "gasp or sharp intake of breath",
    "silence or quiet room tone",
    "comedic impact or sudden sound effect",
    "background musical score",
)


def analyze_clip(
    wav_path: Path | str,
    *,
    hf_home: Path = DEFAULT_HF_HOME,
    use_cuda: bool = True,
    run_clap: bool = False,
    run_whisper: bool = False,
    run_speaker: bool = False,
    clap_labels: Sequence[str] = _CLAP_DEFAULT_LABELS,
) -> ClipExpressiveEnvelope:
    """Analyze a local WAV clip offline, preserving provenance and optional CUDA acceleration."""
    path = Path(wav_path)
    sha = hashlib.sha256(path.read_bytes()).hexdigest()
    duration_sec, sr, peak_db, pauses = detect_wav_pauses(path)

    acoustic_tags: List[Dict[str, Any]] = []
    segments: List[Dict[str, Any]] = []
    speaker_dim: Optional[int] = None
    provenance: Dict[str, Any] = {"offline_only": True, "rms_detector": "pcm16_100ms"}

    os.environ.setdefault("HF_HUB_OFFLINE", "1")
    os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")

    if run_clap:
        clap_dir = resolve_hf_snapshot("models--laion--clap-htsat-unfused", hf_home)
        if clap_dir is not None:
            import librosa
            import torch
            from transformers import ClapModel, ClapProcessor

            device = "cuda" if (use_cuda and torch.cuda.is_available()) else "cpu"
            y48, _ = librosa.load(str(path), sr=48000, mono=True, duration=15.0)
            proc = ClapProcessor.from_pretrained(str(clap_dir), local_files_only=True)
            model = ClapModel.from_pretrained(str(clap_dir), local_files_only=True).to(device)
            # transformers 5.22+ deprecates `audios=`, requiring `audio=`
            inputs = proc(text=list(clap_labels), audio=y48, sampling_rate=48000, return_tensors="pt", padding=True).to(device)
            with torch.no_grad():
                probs = torch.softmax(model(**inputs).logits_per_audio[0], dim=-1).detach().cpu().tolist()
            acoustic_tags = sorted(
                [{"label": lbl, "score": round(float(score), 4)} for lbl, score in zip(clap_labels, probs)],
                key=lambda row: -row["score"],
            )
            provenance["clap"] = {"snapshot": clap_dir.name, "device": device}

    if run_whisper:
        fw_dir = resolve_hf_snapshot("models--Systran--faster-whisper-small.en", hf_home)
        if fw_dir is not None:
            import librosa
            import numpy as np
            import torch
            from faster_whisper import WhisperModel

            device = "cuda" if (use_cuda and torch.cuda.is_available()) else "cpu"
            ctype = "float16" if device == "cuda" else "int8"
            y16, _ = librosa.load(str(path), sr=16000, mono=True, duration=30.0)
            fw = WhisperModel(str(fw_dir), device=device, compute_type=ctype, local_files_only=True)
            seg_iter, _ = fw.transcribe(y16.astype(np.float32), word_timestamps=True, vad_filter=False)
            segments = [
                {"start": round(s.start, 3), "end": round(s.end, 3), "text": s.text.strip()}
                for s in seg_iter
            ]
            provenance["whisper"] = {"snapshot": fw_dir.name, "device": device}

    if run_speaker:
        sb_dir = resolve_hf_snapshot("models--speechbrain--spkrec-ecapa-voxceleb", hf_home)
        if sb_dir is not None:
            import librosa
            import torch
            try:
                from speechbrain.inference.speaker import EncoderClassifier
            except ImportError:
                from speechbrain.pretrained import EncoderClassifier

            device = "cuda" if (use_cuda and torch.cuda.is_available()) else "cpu"
            y16, _ = librosa.load(str(path), sr=16000, mono=True, duration=10.0)
            ecapa = EncoderClassifier.from_hparams(source=str(sb_dir), run_opts={"device": device})
            emb = ecapa.encode_batch(torch.tensor(y16[: 16000 * 3]).unsqueeze(0))
            speaker_dim = int(emb.shape[-1])
            provenance["speaker_ecapa"] = {"snapshot": sb_dir.name, "device": device}

    return ClipExpressiveEnvelope(
        source_path=str(path),
        source_sha256=sha,
        duration_sec=duration_sec,
        sample_rate=sr,
        pause_windows=pauses,
        peak_rms_db=peak_db,
        acoustic_tags=acoustic_tags,
        transcript_segments=segments,
        speaker_embedding_dim=speaker_dim,
        provenance=provenance,
    )
