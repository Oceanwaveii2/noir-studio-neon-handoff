"""
Deterministic prose diagnostics for the Noir Module 1 Prose Engine.
Performs rule-based, non-neural evaluation of:
- Observer filter words ("she noticed", "he saw", "she felt")
- Dialogue tag labels & emotion labels ("she said angrily", "in pure frustration")
- Adjective/adverb piling (3+ stacked descriptors)
- Sentence cadence and burstiness (standard deviation of sentence lengths)
- Sensory detail budgeting (olfactory, auditory, tactile, visual)
- Psychic distance estimation (John Gardner 1-5 scale)
"""

import math
import re
from typing import Dict, List, Set, Tuple
from .models import ProseDiagnosticReport


class ProseDiagnosticsAnalyzer:
    """Deterministic, rule-based prose quality analyzer."""

    # Filter word patterns (creates artificial distance between reader and action)
    FILTER_PATTERNS = [
        r"\b(?:\w+)\s+(?:noticed|could\s+see|saw|felt|realized|observed|watched|heard|smelled|tasted|sensed|noted)\b",
        r"\b(?:\w+)\s+(?:became\s+aware\s+of|caught\s+sight\s+of|could\s+hear|could\s+feel)\b",
        r"\b(?:\w+)\s+(?:seemed\s+to|appeared\s+to)\b",
        r"\b(?:\w+)\s+(?:notices|feels|hears|sees|realizes|seems|watches|thinks|knows|wonders|observes|senses|notes|smells|tastes)\b",
    ]

    # Label syntax patterns (telling emotions via adverbs or direct nouns instead of physical action)
    LABEL_PATTERNS = [
        # Emotion adverbs attached to speech
        r"\b(?:said|whispered|screamed|replied|shouted|rasped|muttered|yelled)\s+(?:angrily|furiously|defensively|nervously|excitedly|sarcastically|bitterly|sadly|happily|scornfully|proudly)\b",
        r"\b(?:angrily|furiously|defensively|nervously|excitedly|sarcastically|bitterly|sadly|happily|scornfully|proudly)\s+(?:said|whispered|screamed|replied|shouted|rasped|muttered|yelled)\b",
        # Explicit emotion naming phrases
        r"\b(?:in|with)\s+(?:pure\s+|sheer\s+)?(?:anger|frustration|jealousy|outrage|confusion|sadness|embarrassment|glee|terror|fear)\b",
        r"\b(?:her|his|their)\s+voice\s+was\s+(?:full\s+of|laced\s+with|dripping\s+with)\s+\w+\b",
        r"\b(?:looked|felt|was)\s+(?:visibly\s+|obviously\s+)?(?:furious|upset|embarrassed|jealous|envious|depressed)\b",
    ]

    # Stacked adjective regex: 3 or more comma-separated or adjacent descriptive words
    ADJECTIVE_PILE_PATTERN = r"\b[A-Za-z]+(?:ed|ing|y|ful|ic|ous|ive|al|ble|ish)\s*,\s*[A-Za-z]+(?:ed|ing|y|ful|ic|ous|ive|al|ble|ish)\s*(?:,\s*|\s+and\s+)[A-Za-z]+(?:ed|ing|y|ful|ic|ous|ive|al|ble|ish)\b"

    # Sensory lexicons for budgeting
    SENSORY_LEXICON: Dict[str, Set[str]] = {
        "olfactory": {
            "ozone", "lavender", "coconut", "oil", "pennzoil", "grease", "perfume", "sweat",
            "damp", "musk", "acrid", "smoke", "scent", "odor", "smell", "stink", "aroma",
            "fragrance", "chia", "flax", "petroleum", "coffee", "whiskey", "wine", "beer",
            "cigarette", "ash", "dust", "steam", "chlorine", "vinegar", "bread",
        },
        "tactile": {
            "itch", "itching", "scratch", "scratches", "scratching", "velvet", "cold", "warm",
            "hot", "sharp", "smooth", "rough", "sticky", "clammy", "damp", "dry", "shiver",
            "tingle", "tingling", "bristle", "snag", "slick", "stinging", "grit", "numb",
            "raw", "sparks", "friction", "sweaty", "silk", "linen", "satin", "leather",
            "wool", "cotton", "denim", "lace", "carpet", "marble", "tile", "chrome",
            "steel", "wood", "glass", "heat", "chill", "ache", "sting", "bruise", "breath",
        },
        "auditory": {
            "shriek", "screech", "crackle", "snap", "snaps", "hiss", "hum", "buzz", "thud",
            "clatter", "crash", "crashes", "shatter", "shatters", "wobble", "pop", "snort",
            "snorts", "rasp", "rasps", "whisper", "clang", "creak", "squeak", "gasp",
            "rattle", "drone", "crunch", "swish", "rustle", "scrape", "thump", "slam",
            "click", "tick", "whir", "sigh", "groan", "sob", "wail", "slap", "stomp",
        },
        "visual_specific": {
            "neon", "tie-dye", "amber", "strobe", "strobes", "strobing", "glint", "flicker",
            "flickers", "glow", "glows", "glossy", "matte", "shadow", "spark", "sparkle",
            "sparkles", "bleached", "pink", "gold", "velvet", "pewter", "light", "sunlight",
            "moonlight", "lamplight", "lamp", "glare", "gloss", "reflection", "mirror",
            "gleam", "blue", "red", "green", "black", "white", "silver", "purple",
            "yellow", "gray", "grey", "brown", "orange", "crimson", "ivory",
        },
    }

    @classmethod
    def split_into_sentences(cls, text: str) -> List[str]:
        """Splits prose text into clean sentences, respecting dialogue quotes."""
        if not text or not text.strip():
            return []
        # Replace abbreviations that might confuse sentence splitting
        cleaned = text.strip()
        # Regex split on sentence terminators (. ! ?) followed by whitespace or quote + whitespace
        parts = re.split(r"(?<=[.!?])[\s\"']+(?=[A-Z0-9\"'])", cleaned)
        sentences = [p.strip() for p in parts if p.strip()]
        if not sentences and cleaned:
            sentences = [cleaned]
        return sentences

    @classmethod
    def count_words(cls, sentence: str) -> int:
        """Counts words in a sentence, excluding standalone punctuation."""
        words = [w for w in re.findall(r"\b[\w'-]+\b", sentence) if any(c.isalnum() for c in w)]
        return len(words)

    @classmethod
    def compute_cadence(cls, sentences: List[str]) -> Tuple[float, float]:
        """
        Computes (average_sentence_length, burstiness_score).
        burstiness_score = standard deviation of word counts across sentences.
        """
        if not sentences:
            return 0.0, 0.0

        lengths = [cls.count_words(s) for s in sentences]
        if not lengths:
            return 0.0, 0.0

        n = len(lengths)
        mean_len = sum(lengths) / n

        if n < 2:
            return float(mean_len), 0.0

        variance = sum((x - mean_len) ** 2 for x in lengths) / (n - 1)
        std_dev = math.sqrt(variance)
        return round(mean_len, 2), round(std_dev, 2)

    @classmethod
    def detect_filter_words(cls, text: str) -> List[str]:
        """Finds all occurrences of observer filter words."""
        found = []
        for pat in cls.FILTER_PATTERNS:
            matches = re.findall(pat, text, flags=re.IGNORECASE)
            for m in matches:
                found.append(m.lower().strip())
        return found

    @classmethod
    def detect_label_syntax(cls, text: str) -> List[str]:
        """Finds dialogue tags with emotional adverbs and explicit emotion naming."""
        found = []
        for pat in cls.LABEL_PATTERNS:
            matches = re.finditer(pat, text, flags=re.IGNORECASE)
            for m in matches:
                found.append(m.group(0).strip())

        # Also detect adjective/adverb piles
        piles = re.finditer(cls.ADJECTIVE_PILE_PATTERN, text, flags=re.IGNORECASE)
        for p in piles:
            found.append(f"Adjective pile: '{p.group(0).strip()}'")

        return found

    @classmethod
    def count_sensory_details(cls, text: str) -> Tuple[int, Dict[str, List[str]]]:
        """Scans text for concrete sensory details across sensory domains."""
        lowered = text.lower()
        # Tokenize into clean lowercase words
        words = set(re.findall(r"\b[\w'-]+\b", lowered))

        details_by_category: Dict[str, List[str]] = {
            "olfactory": [],
            "tactile": [],
            "auditory": [],
            "visual_specific": [],
        }
        total_count = 0

        for category, lexicon in cls.SENSORY_LEXICON.items():
            # Stem-matched so 'glow' catches 'glows'/'glowing' without 'hot' matching 'hotel'.
            matches = []
            for term in lexicon:
                if re.search(rf"\b{re.escape(term)}(?:s|es|ed|ing)?\b", lowered):
                    matches.append(term)
            if matches:
                details_by_category[category].extend(sorted(matches))
                total_count += len(matches)

        return total_count, details_by_category

    @classmethod
    def estimate_psychic_distance(
        cls,
        text: str,
        filter_count: int,
        sensory_count: int,
        has_labels: bool,
    ) -> int:
        """
        Estimates psychic distance on a 1-5 scale:
        1 = Intimate internal / raw visceral immersion
        2 = Close third-person performance (immediate physical blocking, vivid senses)
        3 = Standard dramatic third-person
        4 = Distant observational report (filter words, summary)
        5 = Panoramic / abstract objective camera
        """
        base_level = 2

        # Filter words increase psychic distance (pushes reader back to Level 4 or 5)
        if filter_count >= 2:
            base_level += 2
        elif filter_count == 1:
            base_level += 1

        # Emotion labels pull the prose out of direct immersion into summary
        if has_labels:
            base_level = min(5, base_level + 1)

        # High sensory grounding brings distance closer
        if sensory_count >= 3 and filter_count == 0:
            base_level = max(1, base_level - 1)

        return max(1, min(5, base_level))

    @classmethod
    def analyze(
        cls,
        text: str,
        span_id: str = "span-unknown",
        target_psychic_distance: int = 2
    ) -> ProseDiagnosticReport:
        """
        Runs comprehensive, deterministic diagnostic analysis on a prose span.
        """
        sentences = cls.split_into_sentences(text)
        mean_len, burstiness = cls.compute_cadence(sentences)

        filter_words = cls.detect_filter_words(text)
        labels = cls.detect_label_syntax(text)
        sensory_count, sensory_cats = cls.count_sensory_details(text)

        stripped = text.strip()
        is_dialogue = stripped.startswith(("- ", "—", "–", "\u201c", '"'))
        similes = len(
            re.findall(
                r"\b(?:as if|as though)\b|\blike\s+(?!it\b|this\b|that\b|him\b|her\b|them\b|me\b|us\b|you\b|i\b)",
                text,
                re.IGNORECASE,
            )
        )

        has_labels = len(labels) > 0
        psychic_dist = cls.estimate_psychic_distance(
            text,
            filter_count=len(filter_words),
            sensory_count=sensory_count,
            has_labels=has_labels,
        )

        warnings: List[str] = []

        # 1. Filter word warning
        if filter_words and not is_dialogue:
            warnings.append(
                f"Filter words detected ({len(filter_words)}): {', '.join(filter_words)}. "
                f"Replace observer phrases with direct sensory action."
            )

        # 2. Label syntax warning
        if labels and not is_dialogue:
            warnings.append(
                f"Emotion label syntax detected ({len(labels)}): {', '.join(labels)}. "
                f"Show emotion through physiological reaction and physical blocking."
            )

        # 3. Cadence / Monotony warning
        if len(sentences) >= 3 and burstiness < 2.0 and mean_len >= 6:
            warnings.append(
                f"Monotonous cadence detected: sentence length standard deviation is {burstiness:.1f}. "
                f"Vary sentence lengths to create rhythmic burstiness."
            )

        # 4. Sensory budget warning
        word_total = sum(cls.count_words(sentence) for sentence in sentences)
        if sensory_count == 0 and not is_dialogue and len(sentences) >= 2 and word_total >= 20:
            warnings.append(
                "Sensory deficit: 0 concrete sensory anchors found. "
                "Include at least one specific olfactory, auditory, tactile, or visual detail."
            )

        # 4b. Simile pileup: the AI habit of stacking comparisons
        if not is_dialogue and similes >= 3 and word_total <= 300:
            warnings.append(
                f"Simile pileup ({similes} comparisons in {word_total} words). "
                f"Keep one, make the others literal physical detail."
            )

        # 5. Psychic distance deviation
        if abs(psychic_dist - target_psychic_distance) >= 2:
            warnings.append(
                f"Psychic distance divergence: estimated {psychic_dist}, but target is {target_psychic_distance}."
            )

        from .linter import compute_composite_slop_score
        slop = compute_composite_slop_score(text)

        return ProseDiagnosticReport(
            span_id=span_id,
            filter_word_count=len(filter_words),
            filter_words_found=filter_words,
            label_syntax_detected=has_labels,
            label_examples=labels,
            average_sentence_length=mean_len,
            burstiness_score=burstiness,
            sensory_details_count=sensory_count,
            psychic_distance_estimate=psychic_dist,
            composite_slop_score=slop["score"],
            repeated_ngrams=slop["repeated_ngrams"],
            warnings=warnings,
        )
