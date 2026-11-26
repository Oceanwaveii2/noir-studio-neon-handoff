import json
from pathlib import Path

from prose_engine.conditioner import paragraph_spans

text = Path("work/foxy/actions.md").read_text(encoding="utf-8")
paras = [text[s:e].strip() for s, e in paragraph_spans(text)]

VARIANTS = {
    42: [
        "She bends to zip the overnight bag, the zipper's rasp loud in the quiet kitchen, giving everyone a view of the impossible bow sculpted on the back of her pantyhose. A kitchen chair tips on the linoleum from the sudden displacement of air.",
        "She bends to zip the bag and the zipper complains the whole way, giving everyone a view of the impossible bow sculpted on the back of her pantyhose. A kitchen chair rocks on the linoleum from the displaced air.",
        "She bends over the overnight bag and works the zipper up in one long rasp, giving everyone a view of the impossible bow sculpted on the back of her pantyhose. Behind her, a kitchen chair tips on the linoleum from the sudden displacement of air.",
    ],
    43: [
        "Francine loops an arm around Rainee's waist—well, as far as her arms can reach. Rainee's hips brush both sides of the hallway runner, its nap scraping the wallpaper, making the rug ruck up like a loose hide.",
        "Francine loops an arm around Rainee's waist—well, as far as her arms can reach. Rainee's hips brush both walls of the hallway, and the runner rucks up behind them like a loose hide, its nap scraping the paper.",
        "Francine gets an arm around Rainee's waist—well, as far as her arms can reach. Rainee's hips brush both sides of the hallway runner, scraping its nap against the wallpaper, and the rug rucks up behind them like a loose hide.",
    ],
    50: [
        "The sedan sits low and patient on the hot asphalt, like a dog that knows it is about to be asked for something unreasonable. Francine opens the passenger door with a bullfighter's flourish and a soft click of the latch.",
        "The sedan sits low on the hot asphalt, patient as a dog that knows it is about to be asked for something unreasonable. Francine opens the passenger door with a bullfighter's flourish, and the latch clicks like a struck tooth.",
        "The sedan sits low and patient on the hot asphalt, like a dog that knows it is about to be asked for something unreasonable. Francine opens the passenger door with a bullfighter's flourish and a click of the latch that sounds like a verdict.",
    ],
    55: [
        "A low gurgle rolls through the car, sour and wet. The seatbelt retracts itself with a polite whizz, all the way to the pillar, as if it has decided to leave.",
        "A low gurgle rolls through the car, sour and wet, and the seatbelt retracts itself with a polite whizz all the way to the pillar, as if it has decided to leave.",
        "A low gurgle rolls through the car, sour and wet. The seatbelt retracts itself with a polite whizz, all the way to the pillar, as if it has decided to leave and take its chances elsewhere.",
    ],
    61: [
        "A tidy little house with a wind chime clinking in the heat and a hose coiled like a sleeping snake, beaded with water. MA MA LING stands on the porch, arms folded, mid-sentence before the car has even stopped.",
        "A tidy little house with a wind chime ticking in the heat and a hose coiled like a sleeping snake, still beaded from the morning. MA MA LING stands on the porch, arms folded, mid-sentence before the car has even stopped.",
        "A tidy little house with a wind chime clinking in the heat and a hose coiled like a sleeping snake, water still beaded along its length. MA MA LING stands on the porch with her arms folded, mid-sentence before the car has even stopped.",
    ],
    63: [
        "Rainee-Peter unfolds from the passenger seat in stages, like a lawn chair, the door groaning as she clears it. Ma Ma Ling watches the whole process without blinking.",
        "Rainee-Peter unfolds from the passenger seat in stages, like a lawn chair, the door groaning and the gravel crunching under her sneakers. Ma Ma Ling watches the whole process without blinking.",
        "Rainee-Peter unfolds from the passenger seat in stages, like a lawn chair, the door groaning as she clears it. Ma Ma Ling watches the whole thing without blinking once.",
    ],
}

entries = [{"original": paras[index], "variants": variants} for index, variants in VARIANTS.items()]
target = Path("work/foxy/variants.json")
target.write_text(json.dumps(entries, indent=2, ensure_ascii=False), encoding="utf-8")
print(f"{len(entries)} paragraphs, {sum(len(v) for v in VARIANTS.values())} variants -> {target}")
