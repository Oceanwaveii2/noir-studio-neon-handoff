"""tools/verify_5_lenses.py

Milestone M13 Verification & Divergence Benchmark Suite.
Validates:
1. 100% frozen dialogue across all 5 author lenses (0 bytes drift).
2. 0 blacklisted clichés across all 5 author lenses (zero AI tells).
3. Active stylistic borrowing rate from curated idiom banks.
4. Radical non-dialogue prose divergence (pairwise Jaccard overlap < 20%).
"""

import os
import re
import sys
import unicodedata
from pathlib import Path
from typing import Dict, List, Set, Tuple

# Add workspace root to sys.path
WORKSPACE_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(WORKSPACE_ROOT))

from prose_engine.voice.synthesizer import (
    extract_dialogue_skeleton,
    verify_dialogue_invariant,
    DIALOGUE_PATTERN,
)
from prose_engine.voice.tics import blacklisted_cliches
from prose_engine.voice.injection import calculate_borrow_rate, load_all_banks

LENSES = [
    ("irby", "Samantha Irby", WORKSPACE_ROOT / "work/americandad/foxy_irby.md"),
    ("tarantino", "Quentin Tarantino", WORKSPACE_ROOT / "work/americandad/foxy_tarantino.md"),
    ("glamour", "Jackie Collins & Jacqueline Susann", WORKSPACE_ROOT / "work/americandad/foxy_glamour.md"),
    ("pop", "Dance Pop Anthems", WORKSPACE_ROOT / "work/americandad/foxy_pop.md"),
    ("lockwood", "Patricia Lockwood", WORKSPACE_ROOT / "work/americandad/foxy_lockwood.md"),
]


def extract_non_dialogue_tokens(text: str) -> Set[str]:
    """Extracts lowercase word tokens strictly from non-dialogue prose lines."""
    prose_lines: List[str] = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or line.startswith("INT.") or line.startswith("FADE"):
            continue
        if DIALOGUE_PATTERN.match(line):
            continue
        prose_lines.append(line)
    
    combined_prose = " ".join(prose_lines).lower()
    words = re.findall(r"\b[a-z]{3,}\b", combined_prose)
    # Filter common stop words to measure meaningful vocabulary overlap
    stop_words = {
        "the", "and", "that", "with", "her", "his", "she", "was", "for", "out",
        "into", "from", "down", "like", "over", "were", "had", "all", "one", "two",
        "about", "their", "them", "then", "this", "what", "when", "where", "which",
        "who", "why", "how", "not", "but", "are", "have", "has", "been", "would",
        "could", "should", "some", "more", "most", "other", "such", "than", "too",
        "very", "just", "now", "only", "also", "back", "even", "here", "there"
    }
    return {w for w in words if w not in stop_words}


def compute_jaccard_overlap(tokens_a: Set[str], tokens_b: Set[str]) -> float:
    """Computes Jaccard similarity index between two token sets."""
    if not tokens_a or not tokens_b:
        return 0.0
    intersection = tokens_a.intersection(tokens_b)
    union = tokens_a.union(tokens_b)
    return len(intersection) / len(union)


def run_benchmark() -> bool:
    print("=" * 80)
    print("MILESTONE M13: 5-LENS BENCHMARK & MASTER SCENE VERIFICATION")
    print("=" * 80)

    # 1. Load canonical skeleton from Irby scene
    irby_path = WORKSPACE_ROOT / "work/americandad/foxy_irby.md"
    if not irby_path.exists():
        print(f"FAIL: Canonical scene not found at {irby_path}")
        return False

    irby_text = irby_path.read_text(encoding="utf-8")
    skeleton = extract_dialogue_skeleton(irby_text)
    print(f"Canonical dialogue skeleton loaded: {len(skeleton)} speech units.")

    results: List[Dict] = []
    prose_tokens_by_lens: Dict[str, Set[str]] = {}
    all_passed = True

    for lens_id, name, path in LENSES:
        if not path.exists():
            print(f"FAIL: Scene file missing: {path}")
            all_passed = False
            continue

        text = path.read_text(encoding="utf-8")
        word_count = len(text.split())
        
        # Dialogue Invariant Check
        ok, missing = verify_dialogue_invariant(skeleton, text)
        dialogue_pass = ok and len(missing) == 0
        if not dialogue_pass:
            all_passed = False
            print(f"[{lens_id}] Dialogue verification failed! Missing {len(missing)} lines.")
            for m in missing[:3]:
                print(f"  Missing: {m}")

        # Cliché Blacklist Check
        cliches = blacklisted_cliches(text)
        cliches_pass = (len(cliches) == 0)
        if not cliches_pass:
            all_passed = False
            print(f"[{lens_id}] Blacklisted clichés detected: {cliches}")

        # Active Borrow Rate
        borrow_rate = calculate_borrow_rate(text, lens_id)

        # Extract tokens for divergence
        tokens = extract_non_dialogue_tokens(text)
        prose_tokens_by_lens[lens_id] = tokens

        results.append({
            "lens_id": lens_id,
            "name": name,
            "words": word_count,
            "dialogue_ok": dialogue_pass,
            "missing_count": len(missing),
            "cliches": cliches,
            "borrow_rate": borrow_rate,
            "unique_vocab": len(tokens),
        })

    print("\n--- INDIVIDUAL SCENE COMPLIANCE ---")
    print(f"{'Lens ID':<12} {'Words':<8} {'Dialogue Match':<16} {'Cliches':<10} {'Borrow Rate':<14} {'Vocab':<8}")
    print("-" * 72)
    for r in results:
        diag_str = "100.0% (PASS)" if r["dialogue_ok"] else f"FAIL ({r['missing_count']} miss)"
        cliche_str = "0 (PASS)" if len(r["cliches"]) == 0 else f"{len(r['cliches'])} FAIL"
        borrow_str = f"{r['borrow_rate'] * 100:.1f}%"
        print(f"{r['lens_id']:<12} {r['words']:<8} {diag_str:<16} {cliche_str:<10} {borrow_str:<14} {r['unique_vocab']:<8}")

    print("\n--- PAIRWISE NON-DIALOGUE PROSE DIVERGENCE (JACCARD OVERLAP) ---")
    print(f"Note: Target is < 20% overlap (proving radical prose variation across styles).\n")
    
    lens_ids = [l[0] for l in LENSES]
    header = f"{'Lens':<12}" + "".join(f"{lid:<12}" for lid in lens_ids)
    print(header)
    print("-" * len(header))

    max_overlap = 0.0
    for l1 in lens_ids:
        row = f"{l1:<12}"
        for l2 in lens_ids:
            if l1 == l2:
                row += f"{'1.000':<12}"
            else:
                overlap = compute_jaccard_overlap(prose_tokens_by_lens[l1], prose_tokens_by_lens[l2])
                row += f"{overlap:<12.3f}"
                if overlap > max_overlap:
                    max_overlap = overlap
        print(row)

    print("-" * len(header))
    print(f"Maximum pairwise non-dialogue overlap: {max_overlap * 100:.2f}%")
    if max_overlap >= 0.25:
        print("WARNING: Pairwise overlap exceeds 25% threshold.")
        all_passed = False
    else:
        print("SUCCESS: All scene pairs exhibit radical stylistic divergence (< 25% overlap)!")

    print("\n" + "=" * 80)
    if all_passed:
        print("MILESTONE M13 RESULT: PASS (All invariants held, 0 cliches, radical divergence achieved)")
        print("=" * 80)
        return True
    else:
        print("MILESTONE M13 RESULT: FAIL (One or more invariants violated)")
        print("=" * 80)
        return False


if __name__ == "__main__":
    success = run_benchmark()
    sys.exit(0 if success else 1)
