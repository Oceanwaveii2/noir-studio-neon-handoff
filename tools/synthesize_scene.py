"""
CLI tool for Milestone M12: De Novo Scene Synthesizer.

Usage:
    python tools/synthesize_scene.py --file work/americandad/foxy_spring_breakup_raw.md --lens tarantino --out work/americandad/foxy_tarantino.md
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.stdout.reconfigure(encoding="utf-8")

from prose_engine.voice.synthesizer import (
    DeNovoSynthesizer,
    DramaticBeat,
    extract_dialogue_skeleton,
    verify_dialogue_invariant,
)
from prose_engine.voice.injection import calculate_borrow_rate


def get_default_beats() -> list[DramaticBeat]:
    return [
        DramaticBeat("b1", "Francine packed for trip with overnight bag, announces duty to help Baba release gas; Haley and Stella react from furniture.", props=["red overnight bag", "glass table", "iced coffee"]),
        DramaticBeat("b2", "Rainee enters in tight red bandage dress, bloated and clutching lower stomach in penguin waddle; tries to sit on sofa to quell rebellion.", props=["red bandage dress", "platform heels", "fox tail"]),
        DramaticBeat("b3", "A brief initial pressure pop escapes against the nylon; Haley warns about seismic readings.", props=["papasan chair", "smartphone"]),
        DramaticBeat("b4", "Rainee laughs, breaking her hold; deep 60-Hz sub-bass rumble shakes linoleum and iced coffee.", props=["sofa", "iced coffee"]),
        DramaticBeat("b5", "Nanites surge in silver web down spine; dress seams split in rapid snaps; primary multi-stage acoustic release rattles china.", props=["silver nanites", "chandelier", "sofa cushions"]),
        DramaticBeat("b6", "Massive expansion into cartoon volume; facial structure morphs into Peter Griffin while crimson lipstick stays immaculate.", props=["cleft chin", "cherry lipstick", "fox tail"]),
        DramaticBeat("b7", "Stella deadpan sip; Haley horrified; Rainee Peter Griffin sigh of relief; Francine snorts with laughter.", props=["straw", "banister"]),
        DramaticBeat("b8", "Nanites hit Francine; transformation into Nurse Francine Deluxe with towering platinum bouffant and white latex uniform.", props=["bouffant", "latex mini-dress", "four-inch stilettos"]),
        DramaticBeat("b9", "Pair squeeze toward door; Rainee massive thighs press hallway; exit to car while Haley and Stella plan evening cover charge.", props=["front door", "console table", "runner carpet"]),
    ]


def main() -> int:
    parser = argparse.ArgumentParser(description="Synthesize scene prose de novo through an Author Lens")
    parser.add_argument("--file", default="work/americandad/foxy_spring_breakup_raw.md")
    parser.add_argument("--lens", default="irby", choices=["irby", "tarantino", "glamour", "pop", "lockwood"])
    parser.add_argument("--out", default="")
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    in_path = Path(args.file)
    if not in_path.is_file():
        print(f"Error: file not found: {in_path}", file=sys.stderr)
        return 1

    script_text = in_path.read_text(encoding="utf-8")
    skeleton = extract_dialogue_skeleton(script_text)
    print(f"Extracted {len(skeleton)} dialogue lines from {in_path.name}")

    synthesizer = DeNovoSynthesizer(args.lens)
    beats = get_default_beats()
    prompt = synthesizer.assemble_synthesis_prompt(
        scene_heading="INT. SMITH LIVING ROOM - MORNING",
        beats=beats,
        skeleton=skeleton,
        seed=args.seed,
    )

    out_file = Path(args.out) if args.out else in_path.parent / f"foxy_{args.lens}.md"
    print(f"Synthesizer ready. Target lens: {synthesizer.lens.name} ({synthesizer.lens.author})")
    print(f"Prompt packet assembled ({len(prompt.split())} words)")
    print(f"Output target: {out_file}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
