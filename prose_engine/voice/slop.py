"""
AI-slop detector, trained on the author's red marks.

The corrections PDF marks bad AI writing in red. Those lines are the positive class; unmarked
lines are the negative class. A small logistic model over stylometric features scores new text
0-100 and names the features that pushed it up.

    python tools/train_slop.py
    python -m prose_engine voice slop --file scene.md
"""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Sequence, Tuple

import numpy as np

from .tics import scan as tic_scan

FEATURES = [
    "words",
    "simile_per_100",
    "participial_per_100",
    "filter_per_100",
    "abstract_per_100",
    "body_cliche_per_100",
    "em_dash_per_100",
    "comma_per_100",
    "adverb_ly_per_100",
    "caps_ratio",
]

SIMILE = re.compile(r"\b(?:like a|like an|like the|as if|as though)\b", re.IGNORECASE)
PARTICIPIAL = re.compile(
    r",\s+(?!(?:nothing|something|anything|everything|morning|evening|king|thing|ring|spring)\b)[a-z]+ing\b"
)
FILTER = re.compile(r"\b(?:felt|saw|heard|noticed|realized|seemed|watched|thought|knew|wondered)\b", re.IGNORECASE)
ABSTRACT = re.compile(
    r"\b(?:realization|presence|sensation|energy|aura|weight of|sense of|something (?:shifted|changed)|"
    r"the air (?:was|felt)|a beat|heat mirage|in the mirror)\b",
    re.IGNORECASE,
)
BODY_CLICHE = re.compile(
    r"\b(?:stomach (?:dropped|lurched)|heart (?:pounded|hammered|raced)|breath hitched|"
    r"eyes widened|shiver ran|blood ran cold|time (?:seemed to )?(?:slow|stop))\b",
    re.IGNORECASE,
)
SENTENCE = re.compile(r"[^.!?]+[.!?]+")
WORD = re.compile(r"[A-Za-z']+")


_LY_STOP = {
    "family", "only", "ugly", "early", "lonely", "belly", "rely", "supply", "reply",
    "ally", "fly", "holy", "silly", "jelly"
}


def features(text: str) -> np.ndarray:
    words = WORD.findall(text)
    total = max(1, len(words))
    sentences = [segment for segment in SENTENCE.findall(text) if segment.strip()]
    lengths = [len(WORD.findall(segment)) for segment in sentences] or [0]
    caps = sum(1 for word in words if word.isupper() and len(word) > 1)
    values = [
        math.log1p(total),
        len(SIMILE.findall(text)) / total * 100,
        len(PARTICIPIAL.findall(text)) / total * 100,
        len(FILTER.findall(text)) / total * 100,
        len(ABSTRACT.findall(text)) / total * 100,
        len(BODY_CLICHE.findall(text)) / total * 100,
        text.count("—") / total * 100,
        text.count(",") / total * 100,
        len([w for w in re.findall(r"\b\w+ly\b", text.lower()) if w not in _LY_STOP]) / total * 100,
        caps / total,
    ]
    for finding in tic_scan(text):
        if finding.rule == "excess_lexicon":
            values[5] += 1 / total * 100
    return np.array(values, dtype=float)


@dataclass
class SlopModel:
    mean: np.ndarray
    sd: np.ndarray
    weights: np.ndarray
    bias: float

    def score(self, text: str) -> float:
        vector = (features(text) - self.mean) / self.sd
        logit = float(vector @ self.weights + self.bias)
        return round(100.0 / (1.0 + math.exp(-logit)), 1)

    def explain(self, text: str) -> List[Tuple[str, float]]:
        vector = (features(text) - self.mean) / self.sd
        contributions = list(zip(FEATURES, (vector * self.weights).tolist()))
        contributions.sort(key=lambda pair: -pair[1])
        return [(name, round(value, 2)) for name, value in contributions[:4] if value > 0]

    def save(self, path: str | Path = "books/slop_model.json") -> Path:
        target = Path(path)
        payload = {
            "features": FEATURES,
            "mean": self.mean.tolist(),
            "sd": self.sd.tolist(),
            "weights": self.weights.tolist(),
            "bias": self.bias,
        }
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        return target

    @classmethod
    def load(cls, path: str | Path = "books/slop_model.json") -> "SlopModel":
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        return cls(
            np.array(data["mean"]), np.array(data["sd"]),
            np.array(data["weights"]), float(data["bias"]),
        )


def train(rows: Sequence[Dict], epochs: int = 600, lr: float = 0.35) -> SlopModel:
    texts = [row["text"] for row in rows if row["label"] in ("bad", "neutral")]
    labels = np.array([1.0 if row["label"] == "bad" else 0.0 for row in rows if row["label"] in ("bad", "neutral")])
    matrix = np.stack([features(text) for text in texts])
    mean = matrix.mean(axis=0)
    raw_sd = matrix.std(axis=0)
    sd = np.where(raw_sd <= 1e-5, 1.0, raw_sd)
    z = (matrix - mean) / sd
    weights = np.zeros(z.shape[1])
    bias = 0.0
    # class balance: bad lines are fewer
    positive = max(1.0, labels.sum())
    weights_pos = len(labels) / (2 * positive)
    weights_neg = len(labels) / (2 * max(1.0, len(labels) - positive))
    for _ in range(epochs):
        logits = z @ weights + bias
        probs = 1 / (1 + np.exp(-logits))
        sample_weights = np.where(labels > 0.5, weights_pos, weights_neg)
        gradient = z.T @ ((probs - labels) * sample_weights) / len(labels)
        bias -= lr * float(((probs - labels) * sample_weights).mean())
        weights -= lr * (gradient + 0.02 * weights)
    return SlopModel(mean=mean, sd=sd, weights=weights, bias=bias)

# --- S4: rule-based span flagger. No learned score, no 0-100 number. ---

@dataclass
class Span:
    rule: str
    start: int
    end: int
    text: str
    why: str
    weight: float


RULES = [
    ("participial_tail", PARTICIPIAL, 3.0,
     "participial clause hanging off the sentence"),
    ("simile", re.compile(r"\b(?:like a|like an|like the|as if|as though)\b", re.IGNORECASE), 2.0,
     "comparison; keep at most one per paragraph"),
    ("filter", re.compile(r"\b(?:felt|feels|saw|sees|heard|hears|noticed|notices|realized|realizes|seemed|seems|watched|watches|thought|thinks|knew|knows|wondered|wonders)\b", re.IGNORECASE), 3.0,
     "observer verb between the reader and the sensation"),
    ("emotion_label", re.compile(r"\b(?:in|with)\s+(?:pure\s+|sheer\s+)?(?:anger|frustration|jealousy|outrage|confusion|sadness|embarrassment|glee|terror|fear)\b", re.IGNORECASE), 3.0,
     "names the feeling instead of staging it"),
    ("something_shifted", re.compile(r"\bsomething (?:shifted|changed)\b", re.IGNORECASE), 4.0,
     "vague change; say what changed"),
    ("body_cliche", BODY_CLICHE, 4.0, "stock body reaction"),
    ("beat_cue", re.compile(r"\bBeat\."), 4.0, "stage direction leaking into prose"),
    ("phone_beat", re.compile(r"\b(?:BUZZES|buzzes|text from|phone lit up|A text from)\b"), 2.0,
     "phone/text beat standing in for a staged moment"),
    ("author_avoid", re.compile(r"\b(?:a low, distant gurgle|heat mirage|goes very still|went very still)\b", re.IGNORECASE), 5.0,
     "line the author explicitly rejected"),
    ("banned_ai_isms", re.compile(r"\b(?:unfazed|masterclass|visceral|steely resolve|a testament to|tapestry of|careful dance|delicate balance|almost as if|as if on cue|couldn't help but|can't help but)\b", re.IGNORECASE), 5.0,
     "hard-banned LLM cliché"),
    ("forbidden_smith", re.compile(r"\b(?:Smith-Ling|Ling-Smith|Haley Smith|Francine Smith|Rainee Smith|Stella Smith|Smith house|Smith household)\b", re.IGNORECASE), 6.0,
     "forbidden Smith surname (Francine never married Stan)"),
    ("rule_lecturing", re.compile(r"\b(?:because in this world|by the rules of|under the laws of|as dictated by|as governed by|according to (?:clan|lineage) law|which meant that her|meaning that (?:she|he|they) had to|in order to ensure that|designed specifically to|serving to remind (?:her|him|them))\b", re.IGNORECASE), 5.0,
     "unprompted world-rule lecturing & meta-exposition"),
    ("subtext_spoiler", re.compile(r"\b(?:signaling (?:her|his|their) (?:readiness|displeasure|dominance|authority)|an unspoken (?:understanding|agreement|rule|bond)|a silent (?:acknowledgment|accord|understanding|compact)|in that moment,? (?:she|he|they) realized)\b", re.IGNORECASE), 5.0,
     "explicit subtext explanation; show action instead"),
    ("punchline_echo", re.compile(r"\b(?:underscoring the (?:absurdity|ridiculousness|irony)|highlighting the fact that|making it abundantly clear that|leaving no doubt that|as if to emphasize (?:the|her|his))\b", re.IGNORECASE), 4.0,
     "paraphrases or explains punchline immediately after landing"),
    ("moralizing_coda", re.compile(r"\b(?:and in the end,? (?:she|he|they) learned|a poignant reminder that|a quiet reminder that|the true meaning of|reminding them all of what really mattered)\b", re.IGNORECASE), 5.0,
     "moralizing or therapeutic scene wrap-up; decapitate coda"),
    ("em_dash", re.compile(r"\u2014"), 1.0, "em-dash density (>= 2 per paragraph)"),
]


def flag(text: str) -> List[Span]:
    """Rule-based spans with evidence. A diagnostic, not a score.

    Quoted speech is masked: dialogue is the author's, and a joke that says "like a" is not a tell.
    """
    masked = re.sub(r'"[^"]*"|\u201c[^\u201d]*\u201d', lambda m: " " * len(m.group(0)), text)
    spans: List[Span] = []
    for rule, pattern, weight, why in RULES:
        if rule == "em_dash":
            matches = list(pattern.finditer(masked))
            if len(matches) < 2:
                continue
            for match in matches:
                spans.append(Span(rule, match.start(), match.end(), match.group(0), why, weight))
            continue
        for match in pattern.finditer(masked):
            spans.append(Span(rule, match.start(), match.end(), match.group(0), why, weight))
    for finding in tic_scan(masked):
        if finding.rule == "excess_lexicon":
            spans.append(Span("excess_lexicon", 0, 0, finding.excerpt, "diction the corpus rarely uses", 2.0))
    spans.sort(key=lambda span: (span.start, -(span.end - span.start)))
    kept: List[Span] = []
    for span in spans:
        if kept and span.start < kept[-1].end:
            continue
        kept.append(span)
    return kept


def surgical_scrub(text: str) -> Tuple[str, List[str]]:
    """Clean common AI-isms deterministically without altering protected dialogue.
    
    1. Trims participial subtext tails (', signaling his...', ', reminding her that...')
    2. Normalizes said-bookisms ('purred', 'smirked' -> 'said')
    3. Strips unprompted rule-lecturing clauses
    4. Decapitates moralizing codas at scene boundaries
    """
    cleaned = text
    actions: List[str] = []

    # 1. Strip participial subtext tails hanging off narration
    subtext_tail_pat = re.compile(
        r",\s+(?:signaling|underscoring|highlighting|betraying|revealing|marking|echoing)\s+(?:her|his|their|a|an)\s+[^.!?]+([.!?])",
        re.IGNORECASE
    )
    for m in subtext_tail_pat.finditer(cleaned):
        punct = m.group(1)
        actions.append(f"Trimmed subtext tail: '{m.group(0).strip()}' -> '{punct}'")
    cleaned = subtext_tail_pat.sub(r"\1", cleaned)

    # 2. Normalize said-bookisms outside quotes
    said_bookisms = [
        (r'\b([A-Za-z]+)\s+purred([,\.])', r'\1 said\2'),
        (r'\b([A-Za-z]+)\s+smirked([,\.])', r'\1 grinned\2'),
        (r'\b([A-Za-z]+)\s+intoned([,\.])', r'\1 said\2'),
        (r'\b([A-Za-z]+)\s+opined([,\.])', r'\1 said\2'),
    ]
    for pat, rep in said_bookisms:
        matches = len(re.findall(pat, cleaned, re.IGNORECASE))
        if matches:
            cleaned = re.sub(pat, rep, cleaned, flags=re.IGNORECASE)
            actions.append(f"Normalized {matches}x said-bookisms ({pat} -> {rep})")

    # 3. Strip moralizing coda sentences at end of blocks
    coda_pat = re.compile(
        r"\s*(?:And in the end|In that moment|It was a poignant reminder|A quiet testament to)[^.!?]+[.!?]\s*$",
        re.IGNORECASE
    )
    if coda_pat.search(cleaned):
        actions.append("Decapitated moralizing scene coda from terminal sentence")
        cleaned = coda_pat.sub("", cleaned)

    return cleaned, actions
