import re
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from prose_engine import paths as prose_paths

novel_path = prose_paths.asset("work", "americandad", "foxy_mo2_hybrid_novel.md")
if not novel_path.exists():
    print("Novel file not found!")
    exit(1)

text = novel_path.read_text(encoding="utf-8")
paras = [p.strip() for p in text.split("\n\n") if p.strip()]

print(f"Loaded {len(paras)} paragraphs from {novel_path.name}\n")

# Category 1: Explicit Rule-Stating / Meta-Exposition
RULE_PATTERNS = [
    (r"\b(?:rule|rules|protocol|protocols|invariant|affordance|constraint|mechanics|system)\b", "EXPLICIT_RULE_WORD"),
    (r"\b(?:because in this|as dictated by|under the laws of|by the logic of|governed by)\b", "RULE_GOVERNANCE"),
    (r"\b(?:meaning that|which meant that|ensuring that|in order to ensure|designed to)\b", "MECHANICAL_JUSTIFICATION"),
    (r"\b(?:nanite|nanites|glamour|celestial|huxian|matrilineal|lineage|clan)\b", "LORE_TERMINOLOGY"),
    (r"\b(?:two[- ]chair|inguinal hernia|ancestral farting)\b", "CANON_ANCHOR"),
]

# Category 2: Unneeded Explanations & Didactic Signposting
EXPLAINING_PATTERNS = [
    (r"\b(?:reminding (?:her|him|them|everyone)|served as a reminder|a reminder that)\b", "EXPLANATORY_REMINDER"),
    (r"\b(?:signaling (?:her|his|their)|underscoring|highlighting the fact that)\b", "EMOTIONAL_SIGNPOSTING"),
    (r"\b(?:an unspoken (?:understanding|agreement|rule)|silent acknowledgment)\b", "AI_UNSPOKEN_TROPE"),
    (r"\b(?:testament to|tapestry of|delicate dance|careful balance|masterclass)\b", "AI_EDITORIALIZING"),
    (r"\b(?:as if to say|as if on cue|almost as if|couldn't help but|can't help but)\b", "AI_HEDGING"),
    (r",\s+(?!(?:nothing|something|anything|everything|morning|evening|spring)\b)[a-z]+ing\b", "PARTICIPIAL_TAIL"),
]

findings = []

for idx, p in enumerate(paras):
    para_findings = []
    
    # Check rule patterns
    for pat, label in RULE_PATTERNS:
        matches = re.findall(pat, p, re.IGNORECASE)
        if matches:
            para_findings.append((label, matches))
            
    # Check explaining patterns
    for pat, label in EXPLAINING_PATTERNS:
        matches = re.findall(pat, p, re.IGNORECASE)
        if matches:
            para_findings.append((label, matches))
            
    if para_findings:
        findings.append((idx, p, para_findings))

print(f"Total paragraphs with potential AI-isms / rule-explanations: {len(findings)}\n")

for idx, p, hits in findings:
    hit_labels = set(h[0] for h in hits)
    # Highlight particularly egregious cases (rule words, mechanical justifications, editorializing, reminders)
    critical = hit_labels.intersection({"EXPLICIT_RULE_WORD", "RULE_GOVERNANCE", "MECHANICAL_JUSTIFICATION", "EXPLANATORY_REMINDER", "EMOTIONAL_SIGNPOSTING", "AI_EDITORIALIZING", "AI_HEDGING", "AI_UNSPOKEN_TROPE"})
    if critical:
        print(f"=== [¶{idx}] CRITICAL HITS: {list(critical)} ===")
        print(f"Excerpt: {p[:240]}...")
        for label, m in hits:
            if label in critical:
                print(f"   -> {label}: {set(m)}")
        print()
