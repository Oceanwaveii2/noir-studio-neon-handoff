"""
Measured AI tells and Hard-Banned Lexical Cliché Blacklist.

Contains:
1. Measured AI tells (participial tails, excess lexicon, negative parallelism, filter words).
2. Hard-banned AI cliché families (musical flatulence, straw/beverage tropes, pseudo-mechanical
   jargon, military hyperbole, and stock literary clichés).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Dict, List

EXCESS_LEXICON = [
    "delve", "delves", "delving", "delved", "tapestry", "testament", "camaraderie", "intricate",
    "palpable", "showcase", "showcasing", "underscore", "underscores", "meticulous",
    "multifaceted", "nuanced", "realm", "journey", "navigate", "leverage", "foster",
    "unfazed", "masterclass", "visceral",
]

FILTER_WORDS = [
    "felt", "saw", "heard", "noticed", "realized", "seemed", "wondered", "watched",
    "thought", "knew", "looked", "seemed",
]

# Hard-Banned AI Slop Families
BLACKLIST_CLICHES: Dict[str, List[str]] = {
    # 1. Musical flatulence euphemisms
    "musical_flatulence": [
        r"\bbaritone trombone\b",
        r"\btrombone glissando\b",
        r"\bcontrabass drone\b",
        r"\bcontrabass glissando\b",
        r"\bcontrabass\b",
        r"\bglissando\b",
        r"\btrombone\b",
        r"\bbaritone drone\b",
        r"\borchestral flatulence\b",
        r"\bfull-throated trombone\b",
    ],
    # 2. Beverage / straw cliché
    "beverage_straw_trope": [
        r"\bslurping death-rattle\b",
        r"\bdeath-rattle\b",
        r"\bdeath rattle\b",
        r"\bslurping against the plastic\b",
    ],
    # 3. Pseudo-mechanical engineering jargon
    "pseudo_mechanical_jargon": [
        r"\bpneumatic\b",
        r"\bhydraulic\b",
        r"\bdisplacement of mass\b",
        r"\binternal pressure wave\b",
        r"\bpressure valve\b",
    ],
    # 4. Military / action hyperbole
    "military_hyperbole": [
        r"\bfatal tactical error\b",
        r"\btactical error\b",
        r"\btactical blunder\b",
        r"\bprimary detonation\b",
        r"\bshatters her seal\b",
        r"\bsmall-caliber gunfire\b",
    ],
    # 5. Stock literary / internet idioms
    "stock_literary_idiom": [
        r"\bgives up the ghost\b",
        r"\btestament to the\b",
        r"\btapestry of\b",
        r"\bdressed with ruthless precision\b",
        r"\bdrops like an anvil\b",
        r"\bclean, dry, and mortifyingly resonant\b",
        r"\bvacuum where nobody breathes\b",
    ],
    # 6. Stoic / melodramatic AI reaction tropes
    "ai_reaction_cliche": [
        r"\bunfazed\b",
        r"\bsteely resolve\b",
        r"\bunspoken understanding\b",
        r"\bsilent agreement\b",
        r"\bvisceral\b",
    ],
    # 7. AI praise and editorial meta-commentary
    "ai_praise_and_editorializing": [
        r"\bmasterclass\b",
        r"\ba testament to\b",
        r"\btapestry of\b",
        r"\bcareful dance\b",
        r"\bdelicate balance\b",
    ],
    # 8. AI filler & involuntary hedging
    "ai_filler_hedging": [
        r"\balmost as if\b",
        r"\bas if on cue\b",
        r"\bas if to say\b",
        r"\bcouldn't help but\b",
        r"\bcan't help but\b",
        r"\ba stark reminder\b",
    ],
    # 9. Explicit world-rule lecturing & causal meta-commentary
    "rule_lecturing_and_exposition": [
        r"\bbecause in this world\b",
        r"\bby the rules of\b",
        r"\bunder the laws of\b",
        r"\bas dictated by\b",
        r"\bas governed by\b",
        r"\baccording to (?:clan|lineage) law\b",
        r"\bwhich meant that her\b",
        r"\bmeaning that (?:she|he|they) had to\b",
        r"\bin order to ensure that\b",
        r"\bdesigned specifically to\b",
        r"\bserving to remind (?:her|him|them)\b",
        r"\ba reminder of (?:her|his|their) nature\b",
    ],
    # 11. Punchline echoes & comic over-explanation
    "punchline_echoes": [
        r"\bunderscoring the (?:absurdity|ridiculousness|irony)\b",
        r"\bhighlighting the fact that\b",
        r"\bmaking it abundantly clear that\b",
        r"\bleaving no doubt that\b",
        r"\bas if to emphasize (?:the|her|his)\b",
    ],
    # 12. Subtext spoilers & emotional signposting
    "subtext_spoilers": [
        r"\bsignaling (?:her|his|their) (?:readiness|displeasure|dominance|authority)\b",
        r"\ban unspoken (?:understanding|agreement|rule|bond)\b",
        r"\ba silent (?:acknowledgment|accord|understanding|compact)\b",
        r"\bin that moment,? (?:she|he|they) realized\b",
        r"\bcouldn't help but (?:feel|notice|wonder|smile)\b",
    ],
    # 13. Moralizing scene codas & therapeutic wrap-ups
    "moralizing_codas": [
        r"\band in the end,? (?:she|he|they) learned\b",
        r"\ba poignant reminder that\b",
        r"\ba quiet reminder that\b",
        r"\bthe true meaning of\b",
        r"\breminding them all of what really mattered\b",
    ],
    # 14. Melodramatic said-bookisms in dialogue tags
    "said_bookisms": [
        r'["“][^"”]+["”]\s+(?:she|he|they|[A-Z][a-z]+)\s+(?:intoned|opined|retorted|queried|ejaculated|breathed|hissed|purred|smirked)\b',
        r'\b(?:intoned|opined|retorted|queried|ejaculated|breathed|hissed|purred|smirked)\s+(?:she|he|they|[A-Z][a-z]+)[,\.]',
    ],
}

PARTICIPIAL = re.compile(r",\s+([a-z]+ing)\b")
NEGATIVE_PARALLELISM = re.compile(
    r"\bnot\s+(?:just|only|merely|simply)?\s*[A-Za-z][^.!?]{0,40}\bbut\b", re.IGNORECASE
)
BEAT = re.compile(r"^(?:beat|a beat)\.?$", re.IGNORECASE)
WORD = re.compile(r"[A-Za-z']+")


@dataclass
class Finding:
    rule: str
    start: int
    end: int
    excerpt: str
    severity: str
    advice: str

    def to_dict(self) -> Dict:
        return {
            "rule": self.rule,
            "start": self.start,
            "end": self.end,
            "excerpt": self.excerpt,
            "severity": self.severity,
            "advice": self.advice,
        }


def _excerpt(text: str, start: int, end: int) -> str:
    return text[max(0, start - 20) : min(len(text), end + 20)].replace("\n", " ").strip()


def blacklisted_cliches(text: str) -> List[str]:
    """Returns a list of all blacklisted AI clichés found in text (lowercased)."""
    found: List[str] = []
    for category, patterns in BLACKLIST_CLICHES.items():
        for pat in patterns:
            for match in re.finditer(pat, text, re.IGNORECASE):
                found.append(match.group(0).lower())
    return sorted(set(found))


def scan(text: str) -> List[Finding]:
    findings: List[Finding] = []
    words = max(1, len(WORD.findall(text)))

    # 1. Scan for hard-banned blacklisted clichés (Severity: Error)
    for category, patterns in BLACKLIST_CLICHES.items():
        for pat in patterns:
            for match in re.finditer(pat, text, re.IGNORECASE):
                findings.append(
                    Finding(
                        f"blacklisted_{category}",
                        match.start(),
                        match.end(),
                        match.group(0),
                        "error",
                        f"Hard-banned AI cliché: '{match.group(0)}'. Replace with grounded character action.",
                    )
                )

    participials = list(PARTICIPIAL.finditer(text))
    if len(participials) >= 2 and len(participials) / words * 1000 >= 3:
        for match in participials:
            findings.append(
                Finding(
                    "participial_tail", match.start(), match.end(), _excerpt(text, *match.span()),
                    "warning", "split into a finite clause",
                )
            )

    lowered = text.lower()
    found_lexicon = [word for word in EXCESS_LEXICON if re.search(rf"\b{word}\b", lowered)]
    if len(found_lexicon) >= 2:
        for word in found_lexicon:
            match = re.search(rf"\b{word}\b", lowered)
            findings.append(
                Finding(
                    "excess_lexicon", match.start(), match.end(), word, "warning",
                    "replace with a concrete noun or verb",
                )
            )

    for match in NEGATIVE_PARALLELISM.finditer(text):
        findings.append(
            Finding(
                "negative_parallelism", match.start(), match.end(), _excerpt(text, *match.span()),
                "warning", "state the assertion directly",
            )
        )

    filters = [word for word in FILTER_WORDS if re.search(rf"\b{word}\b", lowered)]
    if len(filters) / words * 1000 > 8:
        findings.append(
            Finding(
                "filter_words", 0, len(text), ", ".join(sorted(set(filters))), "info",
                "replace observer verbs with action or sensation",
            )
        )

    for line in text.splitlines():
        stripped = line.strip()
        if BEAT.match(stripped):
            start = text.find(line)
            findings.append(
                Finding(
                    "beat_direction", start, start + len(line), stripped, "info",
                    "replace with physical action",
                )
            )
    return findings


def counts(text: str) -> Dict[str, int]:
    result: Dict[str, int] = {}
    for finding in scan(text):
        result[finding.rule] = result.get(finding.rule, 0) + 1
    return result


def per_k(count: int, text: str) -> float:
    words = max(1, len(WORD.findall(text)))
    return round(count / words * 1000, 2)
