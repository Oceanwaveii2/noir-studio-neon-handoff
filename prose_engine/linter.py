"""
Anti-AI-ism Linter & Stylistic Quality Auditor.
Milestone M-PE6: Script-Novel Hybrid Realizer & Anti-AI-ism Linter.

Audits prose and script text against mechanical AI tells, essayistic filler,
romance melodrama clichés, and stylistic burstiness metrics:
  1. Binary Contrasts: "less X and more Y", "not so much X as Y".
  2. Essayistic Narrative Explanations: "Because of this...", "Due to this...".
  3. Symmetrical Tripartite Verbs: "jumped, stumbled, and collapsed".
  4. Romance Melodrama Stock Phrases: "white-knuckles", "quivering jaw", "pale blush", "primal panic", "heat-mirage".
  5. Weak Participial Tails: trailing ", leaving/sending/creating/causing ...".
  6. Burstiness Threshold: Standard deviation of sentence lengths (σ >= 4.0).

Exit Criterion:
  0 linter violations, 0 blacklisted clichés, and passing burstiness (σ >= 4.0).
"""

from __future__ import annotations

import argparse
import math
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


@dataclass
class LinterViolation:
    category: str
    matched_text: str
    line_number: int
    context_snippet: str
    rule_description: str

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class LinterReport:
    total_violations: int
    violations: List[LinterViolation]
    burstiness_score: float
    burstiness_passed: bool
    passed: bool
    summary: Dict[str, int]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "total_violations": self.total_violations,
            "passed": self.passed,
            "burstiness_score": self.burstiness_score,
            "burstiness_passed": self.burstiness_passed,
            "summary": self.summary,
            "violations": [v.to_dict() for v in self.violations],
        }


class AntiAILinterError(Exception):
    """Raised when text violates anti-AI stylistic rules."""
    pass


# -----------------------------------------------------------------------------
# Canonical Banned AI Patterns
# -----------------------------------------------------------------------------

LINTER_RULES: Dict[str, Dict[str, Any]] = {
    "binary_contrast": {
        "description": "Binary contrast formula ('less X and more Y', 'not so much X as Y', 'not X, but Y', 'wasn't X—it was Y')",
        "patterns": [
            r"\bless\s+(?:(?:of\s+)?(?:a|an)\s+)?([a-z]+)\s+and\s+more\s+(?:(?:of\s+)?(?:a|an)\s+)?([a-z]+)\b",
            r"\bnot\s+so\s+much\s+([a-z]+)\s+as\s+([a-z]+)\b",
            r"\bnot\s+([a-z]+),\s*but\s+rather\s+([a-z]+)\b",
            r"\bnot\s+(?:a\s+|an\s+|just\s+)?[a-z]+(?:\s+[a-z]+){0,2},\s+but\s+(?:a\s+|an\s+)?[a-z]+\b",
            r"\b(?:it\s+)?(?:wasn'?t|isn'?t|were\s+not)\s+[^.!?\n]{2,40}(?:—|--|,)\s*(?:it\s+)?(?:was|is)\b",
        ],
    },
    "essayistic_transition": {
        "description": "Essayistic/academic narrative explanation ('Because of this', 'Due to this')",
        "patterns": [
            r"\bBecause\s+of\s+this,?\b",
            r"\bDue\s+to\s+this,?\b",
            r"\bAs\s+a\s+result\s+of\s+this,?\b",
            r"\bIt\s+is\s+worth\s+noting\s+that\b",
            r"\bIn\s+order\s+to\s+understand\b",
        ],
    },
    "tripartite_verbs": {
        "description": "Symmetrical 3-verb serial list ('verb-ed, verb-ed, and verb-ed')",
        "patterns": [
            r"\b([a-z]{3,}ed),\s+([a-z]{3,}ed),\s+and\s+([a-z]{3,}ed)\b",
            r"\b([a-z]{3,}ing),\s+([a-z]{3,}ing),\s+and\s+([a-z]{3,}ing)\b",
            r"\b([a-z]{3,}s),\s+([a-z]{3,}s),\s+and\s+([a-z]{3,}s)\b",
        ],
    },
    "romance_cliche": {
        "description": "Stock romance melodrama cliché ('white-knuckles', 'quivering jaw', 'primal panic')",
        "patterns": [
            r"\bwhite[- ]knuckle[a-z]*\b",
            r"\bknuckles?\s+(?:turned\s+white|went\s+white|glowed\s+white)\b",
            r"\bquivering\s+jaw\b",
            r"\bpale\s+blush\b",
            r"\bprimal\s+panic\b",
            r"\bheat[- ]mirage\b",
            r"\bshivering\s+breath\b",
            r"\blet\s+out\s+a\s+breath\s+she\s+didn'?t\s+know\s+she\s+was\s+holding\b",
        ],
    },
    "weak_participial_tail": {
        "description": "Weak dangling participle tail (', leaving/creating/sending/causing ...')",
        "patterns": [
            r",\s*(?:leaving|creating|sending|causing|resulting\s+in)\s+[a-z\s]{4,35}[\.?!]",
        ],
    },
    "banned_ai_isms": {
        "description": "Hard-banned LLM tropes and editorial clichés ('unfazed', 'masterclass', 'visceral', 'testament')",
        "patterns": [
            r"\bunfazed\b",
            r"\bmasterclass\b",
            r"\bvisceral\b",
            r"\bsteely resolve\b",
            r"\ba testament to\b",
            r"\btapestry of\b",
            r"\bcareful dance\b",
            r"\bdelicate balance\b",
            r"\balmost as if\b",
            r"\bas if on cue\b",
            r"\bcouldn't help but\b",
            r"\bcan't help but\b",
        ],
    },
    "rule_lecturing_and_exposition": {
        "description": "Explicit world-rule lecturing & causal meta-commentary",
        "patterns": [
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
    },
    "punchline_echoes": {
        "description": "Punchline echoes & comic over-explanation",
        "patterns": [
            r"\bunderscoring the (?:absurdity|ridiculousness|irony)\b",
            r"\bhighlighting the fact that\b",
            r"\bmaking it abundantly clear that\b",
            r"\bleaving no doubt that\b",
            r"\bas if to emphasize (?:the|her|his)\b",
        ],
    },
    "subtext_spoilers": {
        "description": "Subtext spoilers & emotional signposting",
        "patterns": [
            r"\bsignaling (?:her|his|their) (?:readiness|displeasure|dominance|authority)\b",
            r"\ban unspoken (?:understanding|agreement|rule|bond)\b",
            r"\ba silent (?:acknowledgment|accord|understanding|compact)\b",
            r"\bin that moment,? (?:she|he|they) realized\b",
            r"\bcouldn't help but (?:feel|notice|wonder|smile)\b",
        ],
    },
    "moralizing_codas": {
        "description": "Moralizing scene codas & therapeutic wrap-ups",
        "patterns": [
            r"\band in the end,? (?:she|he|they) learned\b",
            r"\ba poignant reminder that\b",
            r"\ba quiet reminder that\b",
            r"\bthe true meaning of\b",
            r"\breminding them all of what really mattered\b",
        ],
    },
    "punchline_front_running": {
        "description": "Punchline front-running & pre-explaining subtext before the reaction lands",
        "patterns": [
            r"\bflat-white-boy\s+(?:rear|butt|ass)\s+is\s+no\s+reason\b",
            r"\bexplaining\s+that\s+she\s+meant\b",
            r"\bin\s+other\s+words,?\s+(?:she|he|they)\s+had\b",
            r"\bmeaning\s+that\s+her\s+(?:ass|butt|rear)\b",
            r"\bgiving\s+away\s+the\s+fact\s+that\b",
        ],
    },
    "dramatic_fragmentation": {
        "description": "Melodramatic staccato 1-3 word sentence chains",
        "patterns": [
            r"(?:^|[.!?]\s+)(?:[A-Z][a-z]+(?:\s+[a-z]+){0,2}[.!?]\s*){3,}",
        ],
    },
    "vocab_maxxing": {
        "description": "Overstuffed AI prestige diction ('delve', 'tapestry', 'labyrinthine', 'palpable tension')",
        "patterns": [
            r"\b(?:delve[ds]?|tapestry|symphony\s+of|kaleidoscope\s+of|labyrinthine|myriad\s+of|plethora\s+of|resonate[ds]?\s+deeply|unwavering|palpable\s+tension|deafening\s+silence|quiet\s+devastation)\b",
        ],
    },
    "false_agency": {
        "description": "Inanimate objects or abstract nouns performing intentional human cognition/emotion",
        "patterns": [
            r"\b(?:the\s+)?(?:silence|room|air|shadow|shadows|darkness|wall|walls|clock|hallway|mirror)\s+(?:demanded|whispered|judged|waited|watched|insisted|mocked|knew|remembered)\b",
        ],
    },
}

_NGRAM_STOPWORDS = frozenset({
    "the", "a", "an", "and", "or", "but", "of", "to", "in", "on", "at", "for",
    "with", "by", "from", "as", "is", "was", "were", "are", "be", "been", "it",
    "its", "this", "that", "she", "he", "they", "her", "his", "their", "i", "you",
})


def detect_ngram_repetition(text: str, n: int = 3, min_count: int = 3) -> List[Dict[str, Any]]:
    """Detect repeated content-word n-grams (ignoring pure-stopword n-grams)."""
    words = re.findall(r"[a-z']+", (text or "").lower())
    if len(words) < n:
        return []
    counts: Dict[str, int] = {}
    for i in range(len(words) - n + 1):
        gram = words[i : i + n]
        if all(w in _NGRAM_STOPWORDS for w in gram):
            continue
        key = " ".join(gram)
        counts[key] = counts.get(key, 0) + 1
    repeated = [
        {"ngram": gram, "count": cnt}
        for gram, cnt in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
        if cnt >= min_count
    ]
    return repeated


# -----------------------------------------------------------------------------
# Anti-AI Linter Engine
# -----------------------------------------------------------------------------

class AntiAILinter:
    """
    Scans text for AI tells, banned clichés, and computes sentence length variance.
    """

    def __init__(self, rules: Optional[Dict[str, Dict[str, Any]]] = None):
        self.rules = rules or LINTER_RULES

    def compute_burstiness(self, text: str) -> float:
        """
        Calculates standard deviation of sentence lengths (word count).
        Higher burstiness (>= 4.0) indicates natural human literary cadence.
        """
        # Split on sentence terminals: ., !, ?
        sentences = re.split(r"[.!?]+", text)
        lengths: List[int] = []

        for s in sentences:
            words = [w for w in s.split() if w.strip() and not w.startswith("*")]
            if len(words) >= 2:
                lengths.append(len(words))

        if len(lengths) < 3:
            return 0.0

        mean = sum(lengths) / len(lengths)
        variance = sum((l - mean) ** 2 for l in lengths) / len(lengths)
        return round(math.sqrt(variance), 2)

    def lint(self, text: str, burstiness_threshold: float = 4.0) -> LinterReport:
        """
        Executes full stylistic audit of text against all rules and burstiness.
        """
        violations: List[LinterViolation] = []
        summary: Dict[str, int] = {cat: 0 for cat in self.rules.keys()}

        lines = text.split("\n")

        for line_idx, line in enumerate(lines, start=1):
            # Skip character headers like FRANCINE (O.S.)
            clean_line = line.strip()
            if not clean_line or clean_line.startswith("#") or clean_line.isupper():
                continue

            for cat, rule_info in self.rules.items():
                for pat in rule_info["patterns"]:
                    for match in re.finditer(pat, line, re.IGNORECASE):
                        snippet_start = max(0, match.start() - 30)
                        snippet_end = min(len(line), match.end() + 30)
                        snippet = line[snippet_start:snippet_end].strip()

                        violations.append(
                            LinterViolation(
                                category=cat,
                                matched_text=match.group(),
                                line_number=line_idx,
                                context_snippet=snippet,
                                rule_description=rule_info["description"],
                            )
                        )
                        summary[cat] += 1

        burstiness = self.compute_burstiness(text)
        burstiness_passed = burstiness >= burstiness_threshold
        passed = (len(violations) == 0) and burstiness_passed

        return LinterReport(
            total_violations=len(violations),
            violations=violations,
            burstiness_score=burstiness,
            burstiness_passed=burstiness_passed,
            passed=passed,
            summary=summary,
        )

    def assert_clean(self, text: str, burstiness_threshold: float = 4.0) -> None:
        """
        Asserts text passes all linter checks; raises AntiAILinterError on failure.
        """
        report = self.lint(text, burstiness_threshold=burstiness_threshold)
        if not report.passed:
            msgs = [f"Found {report.total_violations} anti-AI violations:"]
            for v in report.violations:
                msgs.append(f"  Line {v.line_number} [{v.category}]: '{v.matched_text}' -> {v.context_snippet}")
            if not report.burstiness_passed:
                msgs.append(
                    f"  Burstiness failed: sigma={report.burstiness_score} (required >= {burstiness_threshold})"
                )
            raise AntiAILinterError("\n".join(msgs))

    def composite_slop_score(self, text: str, burstiness_threshold: float = 4.0) -> Dict[str, Any]:
        """Compute a 0-100 Composite Slop Score combining AI tells, burstiness deficit, and n-gram repetition."""
        report = self.lint(text, burstiness_threshold=burstiness_threshold)
        word_count = max(1, len(re.findall(r"\b[\w'-]+\b", text or "")))
        density_per_100 = (report.total_violations / word_count) * 100.0
        violation_pts = min(65.0, density_per_100 * 9.5 + report.total_violations * 3.5)

        burstiness_deficit = max(0.0, burstiness_threshold - report.burstiness_score)
        # Only penalize burstiness when there are enough sentences (>=3) to measure it meaningfully
        sentence_count = len([s for s in re.split(r"[.!?]+", text or "") if len(s.split()) >= 2])
        burstiness_pts = min(20.0, burstiness_deficit * 5.0) if sentence_count >= 3 else 0.0

        repeated_ngrams = detect_ngram_repetition(text)
        ngram_pts = min(15.0, sum(max(1, item["count"] - 2) * 5.0 for item in repeated_ngrams))

        score = round(min(100.0, violation_pts + burstiness_pts + ngram_pts), 2)
        if score <= 12.0:
            grade = "A"
        elif score <= 28.0:
            grade = "B"
        elif score <= 50.0:
            grade = "C"
        else:
            grade = "D"

        return {
            "score": score,
            "grade": grade,
            "burstiness": report.burstiness_score,
            "burstiness_passed": report.burstiness_passed,
            "total_violations": report.total_violations,
            "by_category": report.summary,
            "repeated_ngrams": repeated_ngrams,
            "flagged_spans": [
                {
                    "category": v.category,
                    "matched_text": v.matched_text,
                    "line_number": v.line_number,
                    "context_snippet": v.context_snippet,
                }
                for v in report.violations
            ],
        }


def compute_composite_slop_score(
    text: str,
    linter: Optional[AntiAILinter] = None,
    burstiness_threshold: float = 4.0,
) -> Dict[str, Any]:
    """Convenience wrapper returning the 0-100 Composite Slop Score breakdown."""
    engine = linter or AntiAILinter()
    return engine.composite_slop_score(text, burstiness_threshold=burstiness_threshold)


# -----------------------------------------------------------------------------
# CLI Entry Point
# -----------------------------------------------------------------------------

def main() -> int:
    import sys
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except Exception:
            pass

    parser = argparse.ArgumentParser(description="Anti-AI-ism Linter & Stylistic Quality Auditor")
    parser.add_argument("file", type=Path, help="Path to markdown/text file to lint")
    parser.add_argument(
        "--threshold",
        type=float,
        default=4.0,
        help="Minimum burstiness threshold (default: 4.0)",
    )
    args = parser.parse_args()

    if not args.file.exists():
        print(f"Error: File not found: {args.file}")
        return 1

    text = args.file.read_text(encoding="utf-8")
    linter = AntiAILinter()
    report = linter.lint(text, burstiness_threshold=args.threshold)

    print(f"Linter Audit Report for: {args.file}")
    print(f"  Status: {'PASS' if report.passed else 'FAIL'}")
    print(f"  Total Violations: {report.total_violations}")
    print(f"  Burstiness (sigma): {report.burstiness_score} (Threshold: {args.threshold} -> {'PASS' if report.burstiness_passed else 'FAIL'})")

    if report.violations:
        print("\nViolations:")
        for v in report.violations:
            print(f"  Line {v.line_number} [{v.category}]: '{v.matched_text}'")
            print(f"    Snippet: \"{v.context_snippet}\"")

    return 0 if report.passed else 1



if __name__ == "__main__":
    raise SystemExit(main())
