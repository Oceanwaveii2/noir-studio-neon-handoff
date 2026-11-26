import re
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from prose_engine import paths as prose_paths

novel_path = prose_paths.asset("work", "americandad", "foxy_mo2_hybrid_novel.md")
text = novel_path.read_text(encoding="utf-8")
paras = [p.strip() for p in text.split("\n\n") if p.strip()]

print(f"Total paragraphs: {len(paras)}")

# Let's inspect all matches and categorize them
patterns = {
    "EXPLICIT_EXPLANATION": r"\b(?:because|meaning that|which meant|which explained why|explaining that|as if to explain|in order to|so that she could|so that he could)\b",
    "RULE_OR_LORE_LECTURING": r"\b(?:rule|rules|protocol|constraint|affordance|invariant|glamour|nanite|nanites|huxian|celestial fox|matrilineal|lineage|clan law|ancient tradition)\b",
    "EDITORIAL_SIGNPOSTING": r"\b(?:reminding|reminder|signaling|underscoring|highlighting|testament|tapestry|delicate balance|unspoken|silent acknowledgment)\b",
    "AI_HEDGING_TICS": r"\b(?:almost as if|as if to say|as if on cue|couldn't help but|can't help but|seemed to|felt like|a wave of|something shifted)\b",
    "TELLING_VS_SHOWING": r"\b(?:she knew that|he knew that|realizing that|she felt a sense of|he felt a sense of|the weight of|a beat of silence)\b",
}

for idx, p in enumerate(paras):
    found = {}
    for cat, pat in patterns.items():
        m = re.findall(pat, p, re.IGNORECASE)
        if m:
            found[cat] = set(m)
    if found:
        print(f"\n[¶{idx}]")
        print(f"Text: {p[:180]}...")
        for cat, matches in found.items():
            print(f"   {cat}: {list(matches)}")
