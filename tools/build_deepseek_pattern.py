import json
from pathlib import Path

from prose_engine.conditioner import paragraph_spans

text = Path("work/foxy/actions.md").read_text(encoding="utf-8")
paras = [text[s:e].strip() for s, e in paragraph_spans(text)]

# One candidate per strategy, written to the pattern constraints:
# image = 2 sentences (fragment <=6 words + long image); action = 3 sentences <=14 words,
# different subjects; understatement = 1-2 flat declaratives, no exclamation;
# rhythm = at least one sentence <6 words and one >20 words.
VARIANTS = {
    42: {
        "image": "The zipper. She bends over the bag and gives everyone the impossible bow sculpted across the back of her pantyhose, while a kitchen chair tips on the linoleum from the displaced air.",
        "action": "She bends. The zipper rasps over the bow on her pantyhose. Behind her, a kitchen chair tips on the linoleum.",
        "understatement": "She zips the bag. The bow on her pantyhose is a small architectural miracle.",
        "rhythm": "She zips the bag. The bow on the back of her pantyhose is a small architectural miracle, and behind her a kitchen chair tips over on the linoleum from the sudden displacement of air.",
    },
    43: {
        "image": "The hallway. Francine gets an arm around Rainee's waist as far as it goes, and Rainee's hips brush both walls so the runner rucks up behind them, nap scraping the paper.",
        "action": "Francine reaches. Her arm stops halfway. Rainee's hips brush both walls, and the runner rucks up behind them.",
        "understatement": "Francine hugs what she can reach. The hallway runner gives up.",
        "rhythm": "Francine hugs what she can reach. Rainee's hips brush both walls of the hall, and the runner rucks up behind them like a loose hide, its nap scraping the wallpaper on both sides.",
    },
    50: {
        "image": "The sedan. It sits low on the hot asphalt, engine ticking, and Francine opens the passenger door with a bullfighter's flourish.",
        "action": "The sedan settles. Francine opens the door. The latch clicks once.",
        "understatement": "The car is low. Francine opens the door like a matador.",
        "rhythm": "The car sits low. Francine opens the passenger door with a bullfighter's flourish, and the latch clicks once like a verdict from a very small judge.",
    },
    55: {
        "image": "The gurgle. It rolls through the car while the seatbelt retracts to the pillar with a whizz, polite and final.",
        "action": "The car gurgles. The seatbelt retracts. The pillar takes it.",
        "understatement": "The car makes a sound. The seatbelt decides to leave.",
        "rhythm": "The car gurgles. The seatbelt retracts itself with a polite whizz all the way to the pillar, as if it has decided the drive is not for it.",
    },
    61: {
        "image": "The porch. A tidy little house holds a wind chime and a hose coiled in a neat spiral, and MA MA LING stands with her arms folded, mid-sentence before the car stops.",
        "action": "The car stops. MA MA LING stands. Her arms fold.",
        "understatement": "The house is tidy. MA MA LING is already talking.",
        "rhythm": "The house is tidy. A wind chime hangs over a coiled hose, and MA MA LING stands on the porch with her arms folded, mid-sentence before the car has even stopped.",
    },
    63: {
        "image": "The lawn chair. Rainee-Peter unfolds from the passenger seat in stages while Ma Ma Ling watches the whole process without blinking.",
        "action": "The seat holds. Rainee-Peter unfolds. Ma Ma Ling watches.",
        "understatement": "Rainee-Peter gets out. It takes a while.",
        "rhythm": "Rainee-Peter unfolds. She comes out of the passenger seat in stages like a lawn chair, and Ma Ma Ling watches the whole process without blinking once.",
    },
}

entries = []
for index, variants in VARIANTS.items():
    entries.append(
        {
            "original": paras[index],
            "variants": [{"text": text_, "strategy": strategy} for strategy, text_ in variants.items()],
        }
    )

Path("work/foxy/deepseek_pattern_variants.json").write_text(
    json.dumps(entries, indent=2, ensure_ascii=False), encoding="utf-8"
)
print(f"{len(entries)} paragraphs x {len(next(iter(VARIANTS.values())))} strategies")
