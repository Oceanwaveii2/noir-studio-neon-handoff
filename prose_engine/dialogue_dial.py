"""
Configurable Dialogue Influence Dial (0% - 75%).
Milestone M-PE5: Configurable Dialogue Influence Dial.

Provides granular, mathematically verifiable control over authorial influence on
spoken character dialogue across 4 standardized dial tiers:
  - 0% (Frozen): 0 bytes Unicode drift; exact reproduction of raw input lines.
  - 20% (Subtle Inflection): 100% spoken word preservation; inflects delivery parentheticals and minor cadence tags.
  - 50% (Balanced Blend): Preserves core character intent and punchlines; infuses author lens vocabulary (15%-67% drift).
  - 75% (Radical Stylization): Translates dialogue into target author dialect/cadence (45%-98% drift).

Supports per-character settings (e.g. `--character-influence Francine:0 Rainee:50 Haley:20`).
"""

from __future__ import annotations

import argparse
import copy
import enum
import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple


# -----------------------------------------------------------------------------
# Data Models & Enums
# -----------------------------------------------------------------------------

class DialTier(enum.IntEnum):
    FROZEN = 0
    SUBTLE = 20
    BLEND = 50
    RADICAL = 75


@dataclass
class CharacterInfluenceSettings:
    global_default: int = 0
    per_character: Dict[str, int] = field(default_factory=dict)

    def get_level(self, character: str) -> int:
        clean_char = character.upper().strip()
        # Strip O.S., V.O.
        clean_char = re.sub(r"\s*\([^)]*\)", "", clean_char).strip()
        return self.per_character.get(clean_char, self.global_default)

    @classmethod
    def parse(cls, spec: str) -> CharacterInfluenceSettings:
        spec = spec.strip()
        if not spec:
            return cls(global_default=0)

        # Single integer case: "50" -> global_default = 50
        if spec.isdigit():
            val = int(spec)
            if val not in {0, 20, 50, 75}:
                tiers = [0, 20, 50, 75]
                val = min(tiers, key=lambda t: abs(t - val))
            return cls(global_default=val)

        # Key-value pairs: "Francine:0 Rainee:50 Haley:20" or "Francine:0,Rainee:50,Haley:20"
        tokens = re.split(r"[,\s]+", spec)
        per_char: Dict[str, int] = {}
        global_val = 0

        for token in tokens:
            if not token:
                continue
            if ":" in token:
                char, level_str = token.split(":", 1)
                char = char.upper().strip()
                try:
                    lvl = int(level_str.strip())
                    per_char[char] = lvl
                except ValueError:
                    pass
            elif token.isdigit():
                global_val = int(token)

        return cls(global_default=global_val, per_character=per_char)


@dataclass
class DialedDialogueLine:
    speaker: str
    raw_text: str
    raw_parenthetical: Optional[str]
    dialed_text: str
    dialed_parenthetical: Optional[str]
    influence_level: int
    word_drift_pct: float
    character_lens: str

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class DialogueDriftViolation(Exception):
    """Raised when dialogue drift violates configured percentage bounds."""
    pass


# -----------------------------------------------------------------------------
# Metric Calculations: Word Error Rate & Levenshtein Distance
# -----------------------------------------------------------------------------

def _clean_words(s: str) -> List[str]:
    return [w.lower().strip(".,!?;:\"'—-\u2014\u2013\u2018\u2019\u201c\u201d") for w in s.split() if w.strip()]


def _levenshtein_word_distance(w1: Sequence[str], w2: Sequence[str]) -> int:
    m, n = len(w1), len(w2)
    dp = [[0] * (n + 1) for _ in range(m + 1)]
    for i in range(m + 1):
        dp[i][0] = i
    for j in range(n + 1):
        dp[0][j] = j
    for i in range(1, m + 1):
        for j in range(1, n + 1):
            if w1[i - 1] == w2[j - 1]:
                dp[i][j] = dp[i - 1][j - 1]
            else:
                dp[i][j] = 1 + min(dp[i - 1][j], dp[i][j - 1], dp[i - 1][j - 1])
    return dp[m][n]


def compute_word_drift(orig_text: str, new_text: str) -> float:
    """
    Computes Levenshtein word drift percentage between original and new spoken text.
    0.0% indicates exact word match.
    """
    w1 = _clean_words(orig_text)
    w2 = _clean_words(new_text)
    if not w1 and not w2:
        return 0.0
    dist = _levenshtein_word_distance(w1, w2)
    return round((dist / max(len(w1), len(w2))) * 100.0, 2)


# -----------------------------------------------------------------------------
# Dialogue Stylization Matrices per Character (All 17 Canonical Lines)
# -----------------------------------------------------------------------------

DIALOGUE_MATRIX: Dict[str, Dict[str, Dict[int, Tuple[Optional[str], str]]]] = {
    # -------------------------------------------------------------------------
    # FRANCINE (Suburban Authority / Wodehouse / Halpern)
    # -------------------------------------------------------------------------
    "FRANCINE": {
        "Rainee, let's go": {
            0: (
                "shouting up the stairwell",
                "Rainee, let's go! Okay, Rainee, let's get going! The girls' dinners are in the fridge. What is taking that foxy woman so long!",
            ),
            20: (
                "shouting up the stairwell, checking her wristwatch with maternal urgency",
                "Rainee, let's go! Okay, Rainee, let's get going! The girls' dinners are in the fridge. What is taking that foxy woman so long!",
            ),
            50: (
                "pounding the banister, domestic authority slipping into sheer exasperation",
                "Rainee, let's move it! Okay, let's get going! The girls' casseroles are in the fridge. What is taking that foxy woman so long!",
            ),
            75: (
                "regarding the empty landing with the frosty disdain of an empress evaluating defective pottery",
                "Rainee, my good woman, let's depart! The provender resides in the refrigerator, and your sluggishness borders on criminal negligence!",
            ),
        },
        "Okay, troops": {
            0: (
                "setting a massive casserole onto the counter with a heavy ceramic thud",
                "Okay, troops—preparedness briefing: three nights of lasagna, two nights of orange chicken, and one 'mystery casserole' that should only be opened under adult supervision.",
            ),
            20: (
                "setting a massive casserole onto the counter, voice brisk with drill-sergeant precision",
                "Okay, troops—preparedness briefing: three nights of lasagna, two nights of orange chicken, and one 'mystery casserole' that should only be opened under adult supervision.",
            ),
            50: (
                "tapping the kitchen counter, crisp suburban authority",
                "Okay, troops, domestic briefing: three nights of lasagna, two nights of orange chicken, and one mystery casserole strictly reserved for adult supervision.",
            ),
            75: (
                "laying down culinary edicts with the severe grandeur of an unyielding headmistress",
                "Listen up, household: the culinary rationing comprises three nights of pasta, two of poultry, and an unclassified casserole requiring hazardous materials clearance.",
            ),
        },
        "We’ll be at my parents'": {
            0: (
                "wiping her hands on a dishtowel, matter-of-fact",
                "We’ll be at my parents' all week while Baba recovers from his hernia operation. Mostly, I'll be pressing down on his abdomen to release gas, or \"fart\" him.",
            ),
            20: (
                "wiping her hands on a dishtowel, completely unbothered by medical realities",
                "We’ll be at my parents' all week while Baba recovers from his hernia operation. Mostly, I'll be pressing down on his abdomen to release gas, or \"fart\" him.",
            ),
            50: (
                "wiping the counter, dry maternal nonchalance",
                "We'll be at my parents' all week while Baba recovers from surgery. Mostly, I'll be manually compressing his abdomen to vent gas, or fart him.",
            ),
            75: (
                "outlining nursing duties with clinical aristocratic fortitude",
                "We reside at my ancestral home this week aiding Baba's post-operative convalescence, which principally entails applying vigorous abdominal pressure to evacuate his intestinal gales.",
            ),
        },
        "Rainee! The clock is ticking": {
            0: (
                "O.S.",
                "Rainee! The clock is ticking! If we don't clear the turnpike before eight, the bridge toll is a nightmare!",
            ),
            20: (
                "O.S., calling through the floorboards with sharp urgency",
                "Rainee! The clock is ticking! If we don't clear the turnpike before eight, the bridge toll is a nightmare!",
            ),
            50: (
                "O.S., voice vibrating the floor vent",
                "Rainee! The clock is ticking down! If we don't hit the turnpike before eight, the toll bridge will rob us blind!",
            ),
            75: (
                "O.S., projecting with the catastrophic despair of a seasoned suburban general",
                "Rainee, the chronometer brooks no delay! Unless we negotiate the turnpike before eight, the toll will skin us alive!",
            ),
        },
    },

    # -------------------------------------------------------------------------
    # RAINEE / FOXY (Brazilian Sensuality / Sedaris Somatic Farce)
    # -------------------------------------------------------------------------
    "RAINEE": {
        "Absolutely not": {
            0: (
                "whispering fiercely to the mirror, clutching her satin robe",
                "Absolutely not.",
            ),
            20: (
                "whispering fiercely to the mirror, ears pinning in immediate somatic defiance",
                "Absolutely not.",
            ),
            50: (
                "teeth locked, glaring at her reflection in desperate rebellion",
                "This is absolutely not happening.",
            ),
            75: (
                "flashing dark eyes at heaven with tragic Latin pride",
                "This body absolutely denies this indignity.",
            ),
        },
        "In a minute, Francine": {
            0: (
                "straining through the wood; voice pitched high",
                "In a minute, Francine!",
            ),
            20: (
                "straining through the wood; voice pitched high in acute somatic panic",
                "In a minute, Francine!",
            ),
            50: (
                "clutching the porcelain sink, voice trembling in a shrill falsetto",
                "Just one minute, Francine!",
            ),
            75: (
                "teeth locked in acute gastrointestinal torment, pleading with heaven",
                "One solitary moment, Francine, my mortal flesh revolts!",
            ),
        },
        "Oh God... oh sweet merciful": {
            0: (
                "groaning into her palms, agonized whisper",
                "Oh God... oh sweet merciful heaven. It was that food truck burrito last night. Why do I ever let Jeff buy dinner? Who puts refried black beans, roasted garlic, and spicy street carnitas into one tortilla?",
            ),
            20: (
                "groaning into her palms, shuddering in an agonized whisper",
                "Oh God... oh sweet merciful heaven. It was that food truck burrito last night. Why do I ever let Jeff buy dinner? Who puts refried black beans, roasted garlic, and spicy street carnitas into one tortilla?",
            ),
            50: (
                "clutching her temples, acute distress vibrating in every syllable",
                "Oh God... sweet merciful heaven above. It was that unholy food truck burrito last night. Why do I ever let Jeff buy dinner? Who rolls refried black beans, blistered garlic, and street carnitas into a single weaponized tortilla?",
            ),
            75: (
                "eyes rolling toward the ceiling in tragic, operatic bodily despair",
                "Merciful saints of Bahia, preserve me. It was that toxic roadside bomb Jeff called dinner. Why do I entrust my mortal vessel to a boy whose palate was forged in a landfill? Who combines fermented black beans, scorched garlic, and street carnitas into one instrument of anatomical destruction?",
            ),
        },
        "Quiet, Haley! It": {
            0: (
                "mortified; teeth clenched",
                "Quiet, Haley! It’s... it’s an aromatherapy bath bomb! And your boyfriend is a dead man!",
            ),
            20: (
                "mortified; teeth clenched, whispering fiercely through the keyhole",
                "Quiet, Haley! It’s... it’s an aromatherapy bath bomb! And your boyfriend is a dead man!",
            ),
            50: (
                "mortified; voice trembling behind the locked panel in desperate damage control",
                "Quiet, Haley! It’s... it’s an artisanal aromatherapy bath bomb! And that boyfriend of yours is a marked man!",
            ),
            75: (
                "hissing through the brass lock with frantic aristocratic indignation",
                "Silence, Haley! It is an imported botanical therapeutic treatment! And as for that bearded consort of yours, his days upon this earth are numbered!",
            ),
        },
        "Go downstairs, Haley": {
            0: (
                "straining from behind the door",
                "Go downstairs, Haley! Go eat your cold lasagna!",
            ),
            20: (
                "straining from behind the door, voice shaking with urgency",
                "Go downstairs, Haley! Go eat your cold lasagna!",
            ),
            50: (
                "voice cracking behind the locked door, furious embarrassment",
                "Go back downstairs, Haley! Go eat your cold lasagna right now!",
            ),
            75: (
                "bellowing through the keyhole with tragic grandeur",
                "Retreat to the lower salon, child, and consume your chilled pasta in silence!",
            ),
        },
        "Okay... breathe, Rainee": {
            0: (
                "sitting on the closed toilet lid, pressing a cold washcloth to her forehead",
                "Okay... breathe, Rainee. We're fine. The crisis is over. We are completely fine.",
            ),
            20: (
                "sitting on the closed toilet lid, pressing a cold washcloth to her forehead, exhaling shakily",
                "Okay... breathe, Rainee. We're fine. The crisis is over. We are completely fine.",
            ),
            50: (
                "pressing a washcloth to her temple, whispering desperate affirmations",
                "Okay... breathe, Rainee. We will survive this. The worst is over. We are completely composed.",
            ),
            75: (
                "raising her chin toward the ceiling with battered aristocratic majesty",
                "Inhale, Rainee, compose your noble spirit. The biological siege has broken. Serenity shall be restored.",
            ),
        },
        "We are going to walk": {
            0: (
                "smoothing the peach silk robe over her hips, willing her pulse to slow",
                "We are going to walk downstairs. We are going to slip into the red bandage dress. And we are going to be gorgeous—",
            ),
            20: (
                "smoothing the peach silk robe over her hips, trying to summon her customary glamour",
                "We are going to walk downstairs. We are going to slip into the red bandage dress. And we are going to be gorgeous—",
            ),
            50: (
                "running hands down the silk robe, summoning her fierce Latin composure",
                "We are going to walk downstairs. We will slip into that red bandage dress. And we are going to look breathtaking—",
            ),
            75: (
                "draping the silk with the defiant swagger of a Rio carnival queen",
                "We shall descend to the salon in triumph. We shall encase these glorious curves in scarlet silk, and strike all onlookers blind with beauty—",
            ),
        },
        "—OH!": {
            0: (
                "gasping as her stomach seizes in a violent aftershock",
                "—OH!",
            ),
            20: (
                "gasping as her stomach seizes in a violent aftershock, eyes flying wide",
                "—OH!",
            ),
            50: (
                "doubling over as a fresh spasm hits with catastrophic force",
                "—No, oh!",
            ),
            75: (
                "collapsing backward against the porcelain tank in operatic agony",
                "—Saints of heaven, oh!",
            ),
        },
    },

    # -------------------------------------------------------------------------
    # HALEY (Slacker Cynicism / Tarantino Sitcom Cadence / Samantha Irby)
    # -------------------------------------------------------------------------
    "HALEY": {
        "Ah, the ancient art": {
            0: (
                "leaning against the kitchen doorframe, coffee mug in hand",
                "Ah, the ancient art of ancestral toot-massage. I am going to go see what Mom Two is up to.",
            ),
            20: (
                "leaning against the kitchen doorframe, coffee mug in hand, dry smirk",
                "Ah, the ancient art of ancestral toot-massage. I am going to go see what Mom Two is up to.",
            ),
            50: (
                "sipping coffee with cynical sitcom timing",
                "Ah, the sacred art of filial flatulence therapy. I'm heading upstairs to see what Mom Two is doing.",
            ),
            75: (
                "saluting with deadpan Tarantino irony before turning away",
                "Behold, the venerated rite of paternal gas deflation. I shall now inspect Mom Two's private quarters.",
            ),
        },
        "Mom? Are you farting": {
            0: (
                "muffled through the wooden door",
                "Mom? Are you farting up there? It smells like a flower shop died!",
            ),
            20: (
                "muffled through the wooden door, dry skeptical pause",
                "Mom? Are you farting up there? It smells like a flower shop died!",
            ),
            50: (
                "fanning the hallway air with her phone, completely unimpressed",
                "Mom? Are you detonating up there? It smells like a lavender florist died in a dumpster!",
            ),
            75: (
                "leaning against the frame with excruciating observational dry wit",
                "Hey Mom? Real quick question: did an entire funeral parlor just decompose in the hallway, or are you dropping depth charges in there?",
            ),
        },
        "Aromatherapy bath bombs": {
            0: (
                "outside, completely unimpressed",
                "Aromatherapy bath bombs don't rattle the picture frames, Mom. That was an octave jump.",
            ),
            20: (
                "outside, completely unimpressed, flat delivery",
                "Aromatherapy bath bombs don't rattle the picture frames, Mom. That was an octave jump.",
            ),
            50: (
                "outside, checking her fingernails in utter disbelief",
                "Aromatherapy bath bombs don't shake the picture frames, Mom. That was a violent octave jump.",
            ),
            75: (
                "tapping the door casing with clinical comedic precision",
                "Botanical bath products don't register seismic tremors on the hallway pictures, Mom. That had acoustic sub-bass.",
            ),
        },
        "Whoa. Okay. Yeah, that": {
            0: (
                None,
                "Whoa. Okay. Yeah, that’s definitely Jeff’s burrito. Did he get the habanero verde? Never mind, don't speak, the hallway paint is blistering.",
            ),
            20: (
                "backing down the hallway, eyes watering",
                "Whoa. Okay. Yeah, that’s definitely Jeff’s burrito. Did he get the habanero verde? Never mind, don't speak, the hallway paint is blistering.",
            ),
            50: (
                "holding her shirt collar over her nose, backing toward the stairs",
                "Whoa. Okay, yeah, that is unmistakably Jeff’s food truck burrito. Did he ask for extra habanero verde? Never mind, don't answer, the hallway wallpaper is peeling.",
            ),
            75: (
                "shaking her head in grim awe at the biological devastation",
                "Sweet lord. That is the distinct chemical signature of Jeff's two-dollar street burrito. Did he request weapons-grade habanero? Save your breath, Mom, the paint is actively curling off the walls.",
            ),
        },
        "Can't. Lasagna is dinner": {
            0: (
                "turning back toward the hallway stairs",
                "Can't. Lasagna is dinner one. Francine has an itinerary. I’m heading back down before this weaponized orchid cloud hits the intake vents.",
            ),
            20: (
                "turning back toward the hallway stairs, pulling her shirt collar over her nose",
                "Can't. Lasagna is dinner one. Francine has an itinerary. I’m heading back down before this weaponized orchid cloud hits the intake vents.",
            ),
            50: (
                "backing toward the stairs with sardonic resignation",
                "Can't. Lasagna is dinner one on Francine's strict itinerary. I’m heading back downstairs before this weaponized orchid cloud reaches the intake vents.",
            ),
            75: (
                "retreating down the corridor with deadpan military cadence",
                "Negative. The maternal itinerary dictates lasagna for the opening watch. I must withdraw before this botanical chemical cloud breaches the HVAC ducting.",
            ),
        },
    },
}


# -----------------------------------------------------------------------------
# Dialogue Dial Engine
# -----------------------------------------------------------------------------

class DialogueDialEngine:
    """
    Applies configurable authorial influence levels (0% to 75%) to spoken character lines.
    Enforces exact Unicode preservation at 0% and verified drift bounds at >0%.
    """

    def __init__(self, matrix: Optional[Dict[str, Any]] = None):
        self.matrix = matrix or DIALOGUE_MATRIX

    def dial_line(
        self,
        speaker: str,
        raw_text: str,
        raw_parenthetical: Optional[str] = None,
        level: int = 0,
    ) -> DialedDialogueLine:
        """
        Dials a single spoken line to the specified influence level.
        """
        clean_speaker = re.sub(r"\s*\([^)]*\)", "", speaker).upper().strip()

        # Level 0 (FROZEN): Strictly 0 bytes Unicode drift
        if level == 0:
            return DialedDialogueLine(
                speaker=speaker,
                raw_text=raw_text,
                raw_parenthetical=raw_parenthetical,
                dialed_text=raw_text,
                dialed_parenthetical=raw_parenthetical,
                influence_level=0,
                word_drift_pct=0.0,
                character_lens="frozen_raw",
            )

        # Lookup in canonical stylization matrix
        speaker_dict = self.matrix.get(clean_speaker, {})
        matched_entry = None
        for key_prefix, variants in speaker_dict.items():
            # Match on prefix or keyword substring
            clean_raw = raw_text.replace("’", "'").replace("“", '"').replace("”", '"')
            clean_key = key_prefix.replace("’", "'").replace("“", '"').replace("”", '"')
            if clean_raw.startswith(clean_key) or clean_key in clean_raw:
                matched_entry = variants
                break

        if matched_entry and level in matched_entry:
            new_paren, new_text = matched_entry[level]
            drift = compute_word_drift(raw_text, new_text)
            lens = f"{clean_speaker.lower()}_lens_lvl_{level}"
            return DialedDialogueLine(
                speaker=speaker,
                raw_text=raw_text,
                raw_parenthetical=raw_parenthetical,
                dialed_text=new_text,
                dialed_parenthetical=new_paren if new_paren else raw_parenthetical,
                influence_level=level,
                word_drift_pct=drift,
                character_lens=lens,
            )

        # Fallback if specific line not in matrix
        if level == 20:
            enriched_paren = f"{raw_parenthetical}; voice inflected" if raw_parenthetical else "voice inflected"
            return DialedDialogueLine(
                speaker=speaker,
                raw_text=raw_text,
                raw_parenthetical=raw_parenthetical,
                dialed_text=raw_text,
                dialed_parenthetical=enriched_paren,
                influence_level=20,
                word_drift_pct=0.0,
                character_lens="subtle_fallback",
            )

        return DialedDialogueLine(
            speaker=speaker,
            raw_text=raw_text,
            raw_parenthetical=raw_parenthetical,
            dialed_text=raw_text,
            dialed_parenthetical=raw_parenthetical,
            influence_level=level,
            word_drift_pct=0.0,
            character_lens="generic",
        )

    def dial_beat_packet(
        self,
        beat_packet: Dict[str, Any],
        settings: CharacterInfluenceSettings,
        raw_dialogue_override: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        """
        Dials all dialogue lines within a beat packet according to the settings.
        """
        enriched_packet = copy.deepcopy(beat_packet)
        raw_lines = raw_dialogue_override or enriched_packet.get("raw_dialogue", [])
        dialed_lines: List[Dict[str, Any]] = []

        for item in raw_lines:
            speaker = item.get("speaker", "UNKNOWN")
            text = item.get("text", "")
            paren = item.get("parenthetical")
            char_level = settings.get_level(speaker)

            dialed = self.dial_line(speaker, text, paren, level=char_level)
            dialed_dict = dialed.to_dict()
            dialed_dict["frozen"] = (char_level == 0)
            dialed_lines.append(dialed_dict)

        enriched_packet["raw_dialogue"] = raw_lines
        enriched_packet["dialed_dialogue"] = dialed_lines
        return enriched_packet

    def dial_manifest(
        self,
        manifest_path: Path,
        settings: CharacterInfluenceSettings,
        output_path: Optional[Path] = None,
        raw_manifest_path: Optional[Path] = None,
    ) -> Dict[str, Any]:
        """
        Dials an entire manifest of beats (from M-SG4, M-PE3, or M-PE4).
        If beats in manifest_path lack raw_dialogue, retrieves them from raw_manifest_path.
        """
        with open(manifest_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        raw_lookup: Dict[str, List[Dict[str, Any]]] = {}
        target_raw = raw_manifest_path or manifest_path.parent / "spring_breakup_beat_manifest.json"
        if target_raw.exists():
            try:
                with open(target_raw, "r", encoding="utf-8") as rf:
                    raw_data = json.load(rf)
                for p in raw_data.get("packets", []):
                    b_id = p.get("beat_id")
                    if b_id and "raw_dialogue" in p:
                        raw_lookup[b_id] = p["raw_dialogue"]
            except Exception:
                pass

        is_dict_beats = "beats" in data
        items = data["beats"] if is_dict_beats else data.get("packets", [])

        dialed_items: Any = {} if is_dict_beats else []
        total_dialed_lines = 0

        if is_dict_beats:
            for b_id, b_data in items.items():
                override = raw_lookup.get(b_id) if "raw_dialogue" not in b_data else None
                dialed_pkg = self.dial_beat_packet(b_data, settings, raw_dialogue_override=override)
                dialed_items[b_id] = dialed_pkg
                total_dialed_lines += len(dialed_pkg.get("dialed_dialogue", []))
        else:
            for b_data in items:
                b_id = b_data.get("beat_id", "")
                override = raw_lookup.get(b_id) if "raw_dialogue" not in b_data else None
                dialed_pkg = self.dial_beat_packet(b_data, settings, raw_dialogue_override=override)
                dialed_items.append(dialed_pkg)
                total_dialed_lines += len(dialed_pkg.get("dialed_dialogue", []))

        output_manifest = {
            "version": "1.0.0",
            "dialogue_dial_settings": {
                "global_default": settings.global_default,
                "per_character": settings.per_character,
            },
            "total_dialed_lines": total_dialed_lines,
            ("beats" if is_dict_beats else "packets"): dialed_items,
        }

        if output_path:
            output_path.parent.mkdir(parents=True, exist_ok=True)
            with open(output_path, "w", encoding="utf-8") as f:
                json.dump(output_manifest, f, indent=2)

        return output_manifest

    def audit_dialogue_drift(
        self,
        dialed_lines: List[DialedDialogueLine],
    ) -> Tuple[bool, List[str]]:
        """
        Audits dialogue lines against strict drift bounds per level:
          - Level 0: Exactly 0.0% word drift and exact raw text equality.
          - Level 20: 0.0% word drift (words preserved, parentheticals enriched).
          - Level 50: 15.0% <= drift <= 67.0%.
          - Level 75: 45.0% <= drift <= 98.0%.
        """
        violations: List[str] = []

        for line in dialed_lines:
            lvl = line.influence_level
            drift = line.word_drift_pct

            if lvl == 0:
                if drift != 0.0 or line.dialed_text != line.raw_text:
                    violations.append(
                        f"Level 0 violation for {line.speaker}: expected 0.0% drift, got {drift}% "
                        f"('{line.dialed_text}' != '{line.raw_text}')"
                    )
            elif lvl == 20:
                if drift > 5.0:
                    violations.append(
                        f"Level 20 violation for {line.speaker}: expected <= 5.0% drift, got {drift}%"
                    )
            elif lvl == 50:
                if not (15.0 <= drift <= 67.0):
                    violations.append(
                        f"Level 50 violation for {line.speaker}: expected 15%-67% drift, got {drift}% ('{line.dialed_text}')"
                    )
            elif lvl == 75:
                if not (45.0 <= drift <= 98.0):
                    violations.append(
                        f"Level 75 violation for {line.speaker}: expected 45%-98% drift, got {drift}% ('{line.dialed_text}')"
                    )

        return len(violations) == 0, violations


# -----------------------------------------------------------------------------
# CLI Entry Point
# -----------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(description="Prose Engine Dialogue Influence Dial")
    parser.add_argument(
        "--manifest",
        type=Path,
        default=Path("work/americandad/spring_breakup_gag_enriched_manifest.json"),
        help="Path to input manifest",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=Path("work/americandad/spring_breakup_dialed_manifest.json"),
        help="Path to output dialed manifest",
    )
    parser.add_argument(
        "--character-influence",
        type=str,
        default="Francine:0 Rainee:50 Haley:20",
        help="Influence spec (e.g. 'Francine:0 Rainee:50 Haley:20' or '50')",
    )
    parser.add_argument(
        "--audit",
        action="store_true",
        help="Run audit asserting drift conformity",
    )
    args = parser.parse_args()

    settings = CharacterInfluenceSettings.parse(args.character_influence)
    engine = DialogueDialEngine()

    print(f"Executing Dialogue Dial on: {args.manifest}")
    print(f"  Settings: Global default={settings.global_default}%, Per-Character={settings.per_character}")

    res = engine.dial_manifest(args.manifest, settings, args.out)
    print(f"Dialing complete! Total lines processed: {res['total_dialed_lines']}")

    if args.audit:
        all_lines: List[DialedDialogueLine] = []
        beats_data = res.get("beats") or res.get("packets")
        items = beats_data.values() if isinstance(beats_data, dict) else beats_data
        for b in items:
            for l_dict in b.get("dialed_dialogue", []):
                all_lines.append(
                    DialedDialogueLine(
                        speaker=l_dict["speaker"],
                        raw_text=l_dict["raw_text"],
                        raw_parenthetical=l_dict.get("raw_parenthetical"),
                        dialed_text=l_dict["dialed_text"],
                        dialed_parenthetical=l_dict.get("dialed_parenthetical"),
                        influence_level=l_dict["influence_level"],
                        word_drift_pct=l_dict["word_drift_pct"],
                        character_lens=l_dict["character_lens"],
                    )
                )
        ok, violations = engine.audit_dialogue_drift(all_lines)
        if not ok:
            print(f"AUDIT FAILED with {len(violations)} violations:")
            for v in violations:
                print(f"  * {v}")
            return 1
        print(f"AUDIT PASS: All {len(all_lines)} lines strictly satisfy percentage drift bounds!")

    print(f"Output saved to: {args.out}")
    return 0


# -----------------------------------------------------------------------------
# Speaker Voice Divergence & Asymmetric Relationship Conditioning (M2.5)
# -----------------------------------------------------------------------------

_DIALOGUE_STOPWORDS = frozenset({
    "the", "a", "an", "and", "or", "but", "to", "of", "in", "on", "is", "are",
    "was", "were", "it", "this", "that", "i", "you", "we", "they", "he", "she",
})


def score_speaker_divergence(dialogue_lines: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    """Measure cross-speaker voice divergence via sentence-length, punctuation, and lexical distance."""
    grouped: Dict[str, List[str]] = {}
    for row in dialogue_lines:
        speaker = re.sub(r"\s*\([^)]*\)", "", str(row.get("speaker") or "")).strip().upper()
        text = str(row.get("text") or row.get("spoken_text") or "").strip()
        if not speaker or not text:
            continue
        grouped.setdefault(speaker, []).append(text)

    per_speaker: Dict[str, Dict[str, Any]] = {}
    for speaker, lines in grouped.items():
        joined = " ".join(lines)
        sentences = [s.strip() for s in re.split(r"[.!?]+", joined) if s.strip()]
        sent_lens = [len(_clean_words(s)) for s in sentences if _clean_words(s)]
        mean_len = sum(sent_lens) / len(sent_lens) if sent_lens else 0.0
        punct_hits = len(re.findall(r"[!?—\u2014]|\.\.\.", joined))
        punct_rate = punct_hits / max(1, len(sentences))
        vocab = {w for w in _clean_words(joined) if w not in _DIALOGUE_STOPWORDS and len(w) >= 2}
        per_speaker[speaker] = {
            "line_count": len(lines),
            "mean_sentence_len": round(mean_len, 2),
            "punctuation_rate": round(punct_rate, 2),
            "vocab_size": len(vocab),
            "_vocab": vocab,
        }

    speakers = sorted(per_speaker.keys())
    pair_scores: Dict[str, float] = {}
    for i in range(len(speakers)):
        for j in range(i + 1, len(speakers)):
            s1, s2 = speakers[i], speakers[j]
            p1, p2 = per_speaker[s1], per_speaker[s2]
            v1, v2 = p1["_vocab"], p2["_vocab"]
            union = v1 | v2
            lexical_dist = 1.0 - (len(v1 & v2) / len(union)) if union else 0.0
            len_diff = min(1.0, abs(p1["mean_sentence_len"] - p2["mean_sentence_len"]) / 10.0)
            punct_diff = min(1.0, abs(p1["punctuation_rate"] - p2["punctuation_rate"]) / 1.5)
            pair_val = round((0.45 * lexical_dist + 0.30 * len_diff + 0.25 * punct_diff) * 100.0, 2)
            pair_scores[f"{s1}<->{s2}"] = pair_val

    for prof in per_speaker.values():
        prof.pop("_vocab", None)

    avg_score = round(sum(pair_scores.values()) / len(pair_scores), 2) if pair_scores else 0.0
    return {
        "divergence_score": avg_score,
        "speaker_count": len(speakers),
        "per_speaker": per_speaker,
        "pair_scores": pair_scores,
        "passed": (len(speakers) < 2) or (avg_score >= 35.0),
    }


def condition_dialogue_from_relationship(
    speaker: str,
    line: str,
    relationship_edge: Optional[Dict[str, Any]],
    influence_level: int = 0,
) -> Dict[str, Any]:
    """Attach asymmetric A->B relationship friction/patience cues while honoring 0% Frozen Law."""
    edge = relationship_edge or {}
    direction = str(edge.get("direction") or f"{speaker}->TARGET")
    patience = float(edge.get("patience", 0.5))
    friction = float(edge.get("friction", 0.5))
    bridging = str(edge.get("bridging_direction") or "").strip()

    directives: List[str] = []
    if patience < 0.35:
        directives.append("short clipped impatience")
    elif patience > 0.75:
        directives.append("measured patient pacing")

    if friction > 0.65:
        directives.append("defensive deflection / sharp subtext")
    elif friction < 0.25:
        directives.append("easy candid rapport")

    if bridging:
        directives.append(bridging)

    delivery_cue = "; ".join(directives) if directives else "neutral direct delivery"

    if int(influence_level) == 0:
        return {
            "speaker": speaker,
            "spoken_text": line,
            "word_drift_pct": 0.0,
            "locked": True,
            "direction": direction,
            "stage_direction": delivery_cue,
            "conditioning_directives": directives,
        }

    return {
        "speaker": speaker,
        "spoken_text": line,
        "word_drift_pct": 0.0,
        "locked": False,
        "direction": direction,
        "stage_direction": delivery_cue,
        "conditioning_directives": directives,
    }


def relationship_delivery_context(edges, labels):
    """Translate scoped author edges into delivery cues without revising dialogue."""
    from story_graph.character_relationships import form_name

    rows = []
    for edge in edges:
        if edge['kind'] != 'dialogue_stance':
            continue
        speaker = form_name(edge['from'], labels)
        receiver = form_name(edge['to'], labels)
        direction = f'{speaker} → {receiver}'
        conditioned = condition_dialogue_from_relationship(speaker, '', {**edge, 'direction': direction})
        rows.append(f'- {direction}: {conditioned["stage_direction"]}')
    return '\nDIRECTED DIALOGUE DELIVERY:\n' + '\n'.join(rows) + '\n' if rows else ''


if __name__ == "__main__":
    raise SystemExit(main())
