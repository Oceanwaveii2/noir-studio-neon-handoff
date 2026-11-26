import json
from pathlib import Path

from prose_engine.conditioner import paragraph_spans

text = Path("work/foxy/actions.md").read_text(encoding="utf-8")
paras = [text[s:e].strip() for s, e in paragraph_spans(text)]

# Structure kept (short beats + concrete detail), length restored.
VARIANTS = {
    42: {
        "action": "She bends to the bag. The zipper rasps over the impossible bow on her pantyhose. Behind her, a kitchen chair tips on the linoleum, and nobody catches it.",
        "image": "The zipper. She bends over the bag and works it up in one long rasp over the impossible bow on her pantyhose, while behind her a kitchen chair tips on the linoleum from the displaced air.",
    },
    43: {
        "action": "Francine reaches for Rainee's waist. Her arm stops halfway, defeated by the geometry. Rainee's hips brush both walls, and the runner rucks up behind them.",
        "image": "The hallway. Francine gets an arm around Rainee's waist as far as it goes, and Rainee's hips brush both walls so the runner rucks up behind them, nap scraping the wallpaper.",
    },
    50: {
        "action": "The sedan settles on the hot asphalt. Francine opens the passenger door. The latch clicks like a verdict.",
        "image": "The sedan. It sits low on the hot asphalt, patient as a dog that knows what is coming, and Francine opens the passenger door with a bullfighter's flourish.",
    },
    55: {
        "action": "The car gurgles. The seatbelt retracts with a polite whizz all the way to the pillar. It stays there.",
        "image": "The gurgle. It rolls through the car while the seatbelt retracts to the pillar with a polite whizz, as if it has decided the drive is not for it.",
    },
    61: {
        "action": "The car stops. MA MA LING stands on the porch, arms folded. Her sentence is already underway.",
        "image": "The porch. A tidy little house holds a wind chime ticking in the heat and a hose coiled like a sleeping snake, and MA MA LING waits with her arms folded, mid-sentence before the car stops.",
    },
    63: {
        "action": "The seat holds. Rainee-Peter unfolds from the passenger seat in stages, like a lawn chair. Ma Ma Ling watches without blinking.",
        "image": "The lawn chair. Rainee-Peter comes out of the passenger seat in stages, the door groaning as she clears it, and Ma Ma Ling watches the whole process without blinking once.",
    },
}

entries = []
for index, variants in VARIANTS.items():
    entries.append(
        {
            "original": paras[index],
            "variants": [{"text": t, "strategy": s} for s, t in variants.items()],
        }
    )

Path("work/foxy/deepseek_rich_variants.json").write_text(
    json.dumps(entries, indent=2, ensure_ascii=False), encoding="utf-8"
)
print(f"{len(entries)} paragraphs x 2")
