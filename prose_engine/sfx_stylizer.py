"""Diversified Stylized Sound-to-Text (Onomatopoeia) Engine.

Generates scene-aware, tone-matched stylized sound effects with a configurable
repetition-decay window so consecutive narrative beats never recycle identical
canned SFX. Pure stdlib, zero imports from story_graph/ or tools/.
"""

from __future__ import annotations

from collections import deque
from typing import Any, Deque, Dict, List, Sequence


SFX_LEXICONS: Dict[str, Dict[str, List[str]]] = {
    "impact": {
        "dry_comedy": ["THWOK", "KLONK", "THUNK", "WHUMP", "BONK-THUD", "KER-PLONK"],
        "slapstick": ["KA-POW!", "WHACK-THUD!", "BOING-CRACK!", "SPLAT-THUMP!", "BIF-KLONK!"],
        "noir": ["CRACK.", "THUD.", "SNAP-THUMP.", "WHUMP.", "KRAK."],
        "dramatic": ["CRACK!", "BOOM-THUD!", "SHATTER-CRUNCH!", "SLAM!"],
    },
    "comedic_snap": {
        "dry_comedy": ["tink.", "snick.", "plip.", "bloop.", "fwip.", "dink."],
        "slapstick": ["TWANG!", "ZOINK!", "BOINK!", "POP-SNAP!", "SPANG!"],
        "noir": ["snick.", "clack.", "tink.", "click-snap."],
        "dramatic": ["SNAP!", "CRACK-WHIP!", "TWANG!"],
    },
    "perfume_hiss": {
        "dry_comedy": ["psssht", "fsssshh", "tsssss", "spritz-hiss", "kshhhht", "pffft-shh"],
        "slapstick": ["PSSSSSHHHH!", "SPRITZ-BLAST!", "FWOOSH-SHHH!", "KSHHHHT!"],
        "noir": ["sssshh.", "psssht.", "fsssss.", "shhhk."],
        "dramatic": ["HSSSSHH!", "FSSSSHT!", "KSSSSHH!"],
    },
    "door_slam": {
        "dry_comedy": ["WHAM.", "KLAK-BOOM.", "THWAM.", "BANG-RATTLE.", "KA-THUNK."],
        "slapstick": ["KA-BLAM!", "SLAM-BOING!", "WHAM-O!", "CRASH-KLONK!"],
        "noir": ["THUD-CLICK.", "BAM.", "KLAK.", "WHAM."],
        "dramatic": ["BLAM!", "THUNDER-SLAM!", "CRACK-BOOM!", "SHUDDER-BANG!"],
    },
    "gasp_beat": {
        "dry_comedy": ["hk—", "gkk—", "hup!", "ack—", "uhp.", "snk—"],
        "slapstick": ["GAAASP!", "HURK!", "ACK-GULP!", "WHEEEZE!"],
        "noir": ["hhk.", "chkk.", "hss—", "khh."],
        "dramatic": ["GASP—!", "HKK—!", "SHARP-INHALATION!"],
    },
    "cutaway_whoosh": {
        "dry_comedy": ["fwip.", "shwook.", "vwoop.", "zip-cut.", "whiff.", "zwoosh."],
        "slapstick": ["ZOOOM-ZIP!", "WHOOOOSH!", "SWOOSH-POP!", "BWIP!"],
        "noir": ["shhhk.", "vwoom.", "fwhip.", "swish."],
        "dramatic": ["WHOOSH—!", "VROOOOM!", "SWEEP-CUT!"],
    },
    "mechanical_click": {
        "dry_comedy": ["chk-chk.", "tik.", "clack-whir.", "krrk.", "bzz-tik.", "snik-clack."],
        "slapstick": ["KA-CHUNK!", "CLANK-SPRONG!", "BZZT-CLACK!", "RATCHET-SNAP!"],
        "noir": ["click.", "chk.", "tik-clack.", "snick."],
        "dramatic": ["CLACK!", "LOCK-SNAP!", "RATCHET-BOOM!"],
    },
}


def _orthographic_variation(base: str, attempt: int, intensity: float) -> str:
    """Create a deterministic tone-preserving orthographic variant when a pool cycles."""
    stem = base.rstrip(".!-—")
    ending = base[len(stem):] or "."
    if intensity >= 0.75:
        return f"{stem.upper()}-{attempt + 1}!"
    if attempt % 2 == 1:
        return f"{stem}{stem[-1].lower() if stem else ''}{ending}"
    return f"{stem}*{ending}"


class SfxStylizer:
    """Scene-aware stylized SFX generator with a repetition-decay window."""

    def __init__(self, decay_window: int = 6) -> None:
        self.decay_window = max(1, int(decay_window))
        self._recent: Deque[str] = deque(maxlen=self.decay_window)
        self.history: List[Dict[str, Any]] = []

    def stylize(
        self,
        category: str,
        tone: str = "dry_comedy",
        intensity: float = 0.5,
        context_hint: str = "",
    ) -> Dict[str, Any]:
        cat_key = category if category in SFX_LEXICONS else "impact"
        tone_map = SFX_LEXICONS[cat_key]
        tone_key = tone if tone in tone_map else "dry_comedy"
        pool = list(tone_map[tone_key])

        # Order pool by intensity preference (higher intensity prefers later/louder entries)
        if intensity >= 0.7:
            pool = list(reversed(pool))

        recent_lower = {item.lower() for item in self._recent}
        ever_used = {item["sfx"].lower() for item in self.history}
        chosen = None
        for candidate in pool:
            if candidate.lower() not in recent_lower and candidate.lower() not in ever_used:
                chosen = candidate
                break

        if chosen is None:
            attempt = len(self.history) + 1
            base = pool[attempt % len(pool)]
            chosen = _orthographic_variation(base, attempt, intensity)
            while chosen.lower() in recent_lower or chosen.lower() in ever_used:
                attempt += 1
                chosen = _orthographic_variation(base, attempt, intensity)

        repeated_in_window = chosen.lower() in recent_lower
        self._recent.append(chosen)
        record = {
            "sfx": chosen,
            "category": cat_key,
            "tone": tone_key,
            "intensity": round(float(intensity), 2),
            "context_hint": context_hint,
            "repeated_in_window": repeated_in_window,
        }
        self.history.append(record)
        return record

    def variety_metrics(self) -> Dict[str, Any]:
        total = len(self.history)
        if total == 0:
            return {
                "total_emitted": 0,
                "unique_count": 0,
                "unique_ratio": 1.0,
                "back_to_back_duplicates": 0,
            }
        sfx_list = [item["sfx"].lower() for item in self.history]
        unique_count = len(set(sfx_list))
        back_to_back = sum(
            1 for idx in range(1, len(sfx_list)) if sfx_list[idx] == sfx_list[idx - 1]
        )
        return {
            "total_emitted": total,
            "unique_count": unique_count,
            "unique_ratio": round(unique_count / total, 3),
            "back_to_back_duplicates": back_to_back,
        }


def generate_scene_sfx(
    events: Sequence[Dict[str, Any]],
    decay_window: int = 6,
) -> Dict[str, Any]:
    """Generate stylized SFX for a sequence of beat events and return variety metrics."""
    stylizer = SfxStylizer(decay_window=decay_window)
    results = [
        stylizer.stylize(
            category=str(ev.get("category", "impact")),
            tone=str(ev.get("tone", "dry_comedy")),
            intensity=float(ev.get("intensity", 0.5)),
            context_hint=str(ev.get("context_hint", "")),
        )
        for ev in events
    ]
    return {
        "events": results,
        "metrics": stylizer.variety_metrics(),
    }
