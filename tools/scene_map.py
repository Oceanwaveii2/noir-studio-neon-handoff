"""
Scene map diagram: what exists, what is bad AI, what is missing, what the edit does.

Source: the author's annotations in "Corrections II.pdf" (red = bad AI writing, green = direction
notes, black = the draft). Renders docs/scene_map.png and docs/scene_map.html.

    python tools/scene_map.py
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

WIDTH, HEIGHT = 1960, 880
BG = (11, 17, 32)
CARD = (15, 23, 42)
BORDER = (37, 51, 82)
TEXT = (226, 232, 240)
MUTED = (148, 163, 184)
RED = (248, 113, 113)
AMBER = (251, 191, 36)
GREEN = (74, 222, 128)
BLUE = (96, 165, 250)
VIOLET = (196, 181, 253)

SCENES = [
    {
        "title": "1 · KITCHEN",
        "spine": [
            "Francine packs Tupperware, sugar in coffee.",
            "She calls upstairs; Rainee answers, muffled.",
            "No Stan: he is not part of the domestic opening.",
        ],
        "errors": [
            "AI put the opening in the bedroom, not here.",
            "Stan was added to the kitchen — wrong for this scene.",
        ],
        "missing": [
            "The real opening: kitchen first.",
            "A reason Rainee must come downstairs.",
            "The call-and-answer connector.",
        ],
        "edits": [
            "Francine alone in the kitchen.",
            "Call up: \"We're going to be late!\"",
            "Rainee, O.S.: \"Coming!\"",
        ],
    },
    {
        "title": "2 · BEDROOM",
        "spine": [
            "Rainee dressed at the vanity.",
            "Her stomach turns; she runs for the bathroom.",
        ],
        "errors": [
            "\"Okay, girl. Big day…\" — AI dialogue, never asked for.",
            "Phone text from Francine \"LEAVING IN 40\" — invented.",
            "\"Then she hears it. A low, distant gurgle…\" — cliché.",
            "\"She goes very still… presses two fingers…\" — cliché.",
            "\"Beat.\" and the \"heat mirage\" mirror line.",
        ],
        "missing": [
            "Getting-dressed setup as a beat.",
            "The gas feeling before the bathroom.",
            "A physical reason to leave the room.",
        ],
        "edits": [
            "Cut phone text, gurgle, mirror, Beat.",
            "Keep the dress and the mirror.",
            "Add: \"No. Not today. I have a dress on.\"",
            "She walks out, hand on the wall.",
        ],
    },
    {
        "title": "3 · HALLWAY",
        "spine": [
            "Haley crosses in front of the bathroom door.",
            "The door closes hard behind Rainee.",
        ],
        "errors": [],
        "missing": [
            "The whole Haley beat — it did not exist.",
            "Blocking: she must walk across the door.",
            "A witness for the bathroom scene.",
        ],
        "edits": [
            "Add Haley with earbuds, crossing the door.",
            "One line: \"Gross.\"",
            "Sets up the through-door dialogue.",
        ],
    },
    {
        "title": "4 · BATHROOM",
        "spine": [
            "Rainee stuck on the toilet; farts; self-talk.",
            "Her farts smell like perfume — she modified herself.",
            "Haley talks to her through the door.",
        ],
        "errors": [
            "No connecting dialogue existed between them.",
            "The comedy beat was absent entirely.",
        ],
        "missing": [
            "The stuck-on-the-toilet scene.",
            "The reason the smell is perfume, not methane.",
            "Haley's lines and Rainee's replies.",
            "Sound through the door / vents.",
        ],
        "edits": [
            "Add self-talk: \"We're doing this today.\"",
            "Add: \"Thank God I modified that… toxic waste dump.\"",
            "Add Haley: \"flower shop died\" / \"I'm telling Mama!\"",
            "Add: \"It's jasmine.\" / \"It's a lot!\"",
            "Add Rainee: \"Tell her. She'll want the recipe.\"",
        ],
    },
    {
        "title": "5 · DOWNSTAIRS",
        "spine": [
            "Francine calls again; Rainee answers.",
            "One spray of perfume, for insurance; she leaves.",
        ],
        "errors": [],
        "missing": [
            "A connector back to Francine and the trip.",
            "Any exit beat.",
        ],
        "edits": [
            "\"I'm leaving with or without you!\" / \"Then leave with me!\"",
            "Perfume, Haley coughs, \"Gorgeous, though.\"",
            "Hands the scene back to the car.",
        ],
    },
]

WORLD_RULES = [
    "Two mothers: Rainee + Francine. No father, no \"Dad.\"",
    "Rainee is a shapeshifter; resizing a chair or the toilet is canon.",
    "Haley is human with dormant fox genes.",
    "Rainee modified her farts to smell like perfume, not methane — the smell is a perfume-shop joke.",
    "Stan is Rainee's CIA partner and Francine's ex-fiance; he is not in this scene.",
    "Tone: deadpan camp comedy.",
]

CONNECTORS = [
    ("Kitchen → Bedroom", "Francine calls up (added)"),
    ("Bedroom → Bathroom", "gas forces the exit (added)"),
    ("Hallway → Bathroom", "Haley at the door (added)"),
    ("Bathroom → Downstairs", "Francine calls again (added)"),
]


def _font(size: int, bold: bool = False):
    names = ["segoeuib.ttf", "segoeui.ttf"] if bold else ["segoeui.ttf", "arial.ttf"]
    for name in names:
        path = Path("C:/Windows/Fonts") / name
        if path.is_file():
            return ImageFont.truetype(str(path), size)
    return ImageFont.load_default()


def _wrap(draw, text, font, width):
    words = text.split()
    lines, current = [], ""
    for word in words:
        trial = (current + " " + word).strip()
        if draw.textlength(trial, font=font) <= width:
            current = trial
        else:
            if current:
                lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines


def _bullets(draw, x, y, width, items, color, font, limit=5):
    draw.ellipse([x, y + 5, x + 6, y + 11], fill=color)
    cursor = y
    for item in items[:limit]:
        for line in _wrap(draw, item, font, width - 16):
            draw.text((x + 14, cursor), line, font=font, fill=color)
            cursor += 17
        cursor += 3
    return cursor


def _card(draw, x, y, w, h, scene):
    draw.rounded_rectangle([x, y, x + w, y + h], radius=14, fill=CARD, outline=BORDER, width=2)
    draw.rectangle([x, y, x + w, y + 44], fill=(17, 28, 51))
    draw.text((x + 16, y + 11), scene["title"], font=_font(20, True), fill=TEXT)

    cursor = y + 58
    header = _font(12, True)
    body = _font(12)

    sections = [
        ("WHAT HAPPENS", scene["spine"], TEXT),
        ("BAD AI  (red marks)", scene["errors"], RED),
        ("MISSING  (green notes)", scene["missing"], AMBER),
        ("THE EDIT", scene["edits"], GREEN),
    ]
    for label, items, color in sections:
        draw.text((x + 16, cursor), label, font=header, fill=color if color != TEXT else MUTED)
        cursor += 20
        if items:
            cursor = _bullets(draw, x + 16, cursor, w - 28, items, color, body)
        else:
            draw.text((x + 16, cursor), "— none —", font=body, fill=MUTED)
            cursor += 20
        cursor += 10


def build_png(path: Path) -> Path:
    image = Image.new("RGB", (WIDTH, HEIGHT), BG)
    draw = ImageDraw.Draw(image)

    draw.text((50, 26), "AMERICAN FOXY MOM — SCENE MAP", font=_font(28, True), fill=TEXT)
    draw.text(
        (50, 62),
        "starting scene only · red = bad AI writing · amber = missing story/dialogue · green = the fix · blue = connector",
        font=_font(14), fill=MUTED,
    )

    # single-row legend
    draw.rectangle([0, 88, WIDTH, 89], fill=BORDER)
    lx = 50
    for label, color in (("bad AI", RED), ("missing", AMBER), ("edit", GREEN), ("connector", BLUE)):
        draw.ellipse([lx, 100, lx + 12, 112], fill=color)
        draw.text((lx + 20, 98), label, font=_font(12), fill=MUTED)
        lx += 170

    rule_y = 114
    draw.text((50, rule_y), "WORLD RULES (hard canon):", font=_font(12, True), fill=VIOLET)
    rule_y += 18
    for line in _wrap(draw, "   ·   ".join(WORLD_RULES), _font(11), WIDTH - 100):
        draw.text((50, rule_y), line, font=_font(11), fill=VIOLET)
        rule_y += 15

    margin = 40
    gap = 22
    card_w = (WIDTH - 2 * margin - 4 * gap) // 5
    card_y = 178
    card_h = 560
    for index, scene in enumerate(SCENES):
        x = margin + index * (card_w + gap)
        _card(draw, x, card_y, card_w, card_h, scene)
        if index < len(SCENES) - 1:
            arrow_y = card_y + card_h // 2
            draw.line([x + card_w + 2, arrow_y, x + card_w + gap - 6, arrow_y], fill=BLUE, width=3)
            draw.polygon(
                [(x + card_w + gap - 6, arrow_y - 6), (x + card_w + gap - 6, arrow_y + 6),
                 (x + card_w + gap + 2, arrow_y)],
                fill=BLUE,
            )

    draw.text(
        (50, HEIGHT - 62),
        "CONNECTORS (the lines that were missing): " + "   ·   ".join(f"{name} — {note}" for name, note in CONNECTORS),
        font=_font(12), fill=BLUE,
    )
    draw.text(
        (50, HEIGHT - 34),
        "Red = bad AI writing · Amber = missing story or dialogue · Green = the fix · Source: Corrections II.pdf + start_scene_corrected.md",
        font=_font(12), fill=MUTED,
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path)
    return path


HTML = """<!doctype html><html><head><meta charset="utf-8"><title>Scene map</title>
<style>
body{background:#0b1120;color:#e2e8f0;font-family:ui-sans-serif,system-ui;margin:0;padding:24px}
h1{color:#fbbf24;font-size:20px;margin:0 0 6px}
.hint{color:#94a3b8;font-size:13px;margin-bottom:18px}
.grid{display:grid;grid-template-columns:repeat(5,1fr);gap:14px}
.card{background:#0f172a;border:1px solid #253352;border-radius:12px;padding:12px}
.card h2{font-size:13px;color:#7dd3fc;margin:0 0 8px;letter-spacing:.05em}
h3{font-size:11px;text-transform:uppercase;letter-spacing:.08em;margin:10px 0 4px}
ul{margin:0;padding-left:16px}
li{font-size:12px;line-height:1.45;margin-bottom:3px}
.spine li{color:#e2e8f0}.bad li{color:#f87171}.missing li{color:#fbbf24}.edit li{color:#4ade80}
.none{color:#64748b;font-size:12px}
</style></head><body><h1>American Foxy Mom — scene map</h1>
<div class="hint">red = bad AI writing · amber = missing story/dialogue · green = the fix</div>
<div class="grid">{cards}</div></body></html>"""


def build_html(path: Path) -> Path:
    cards = []
    for scene in SCENES:
        def block(label, items, cls):
            if not items:
                return f'<h3 class="{cls.split()[0]}">{label}</h3><div class="none">— none —</div>'
            body = "".join(f"<li>{item}</li>" for item in items)
            return f'<h3 class="{cls.split()[0]}">{label}</h3><ul class="{cls}">{body}</ul>'

        cards.append(
            f'<div class="card"><h2>{scene["title"]}</h2>'
            + block("What happens", scene["spine"], "spine")
            + block("Bad AI", scene["errors"], "bad")
            + block("Missing", scene["missing"], "missing")
            + block("The edit", scene["edits"], "edit")
            + "</div>"
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(HTML.replace("{cards}", "".join(cards)), encoding="utf-8")
    return path


def main() -> int:
    png = build_png(Path("docs/scene_map.png"))
    html = build_html(Path("docs/scene_map.html"))
    print(f"written: {png}")
    print(f"written: {html}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
