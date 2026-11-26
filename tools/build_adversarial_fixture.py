"""Generate the adversarial guard fixture (40+ cases)."""

from __future__ import annotations

import json
from pathlib import Path

CASES = []
BASE = "Rainee set the tray down and looked at the door."

for index, name in enumerate(
    ["Detective Marsh", "Uncle Bob", "Cousin June", "Officer Price", "Aunt Vera", "Nana Rose", "Coach Dan"]
):
    CASES.append({"id": f"invented_person_{index}", "original": BASE,
                  "candidate": f"{name} set the tray down and looked at the door.", "expect_reject": True})

for index, name in enumerate(["Dad", "my father", "Stan", "Roger", "Steve", "Barry", "Toshi"]):
    CASES.append({"id": f"forbidden_{index}", "original": BASE,
                  "candidate": f"{name} set the tray down and looked at the door.", "expect_reject": True})

PAIRS = [("Rainee", "Francine"), ("Rainee", "Haley"), ("Francine", "Haley"),
         ("Rainee", "Stan"), ("Haley", "Rainee"), ("Francine", "Rainee"), ("Stan", "Rainee")]
for index, (first, second) in enumerate(PAIRS):
    CASES.append({"id": f"role_swap_{index}", "original": f"{first} slapped {second} in the hall.",
                  "candidate": f"{second} slapped {first} in the hall.", "expect_reject": True})

COUNTS = [("three", "four"), ("two", "three"), ("four", "five"), ("five", "six"),
          ("one", "two"), ("three", "two"), ("six", "seven")]
for index, (before, after) in enumerate(COUNTS):
    CASES.append({"id": f"count_{index}",
                  "original": f"She stacked {before} Tupperware containers on the table.",
                  "candidate": f"She stacked {after} Tupperware containers on the table.",
                  "expect_reject": True})

QUOTES = [("Absolutely not.", "Probably not."), ("That was the sushi.", "That was the burrito."),
          ("I'm aware.", "I don't care."), ("It's jasmine.", "It's lavender."),
          ("Gorgeous, though.", "Beautiful, though."), ("Tell her.", "Don't tell her."),
          ("Quiet, Haley.", "Hush, Haley.")]
for index, (before, after) in enumerate(QUOTES):
    CASES.append({"id": f"quote_{index}", "original": f'She said, "{before}"',
                  "candidate": f'She said, "{after}"', "expect_reject": True})

for index, (obj, verb) in enumerate([("Tupperware", "laughed"), ("The lipstick", "replied"),
                                     ("The fridge", "sighed"), ("The dress", "shrugged"),
                                     ("The toilet", "whispered")]):
    CASES.append({"id": f"personification_{index}", "original": BASE,
                  "candidate": f"{obj} {verb} at her from the counter.", "expect_reject": True})

GOOD = [
    "Rainee put the tray down and stared at the door.",
    "Rainee set the tray on the counter, then looked toward the door.",
    "The tray went down. Rainee looked at the door.",
    "Rainee lowered the tray and checked the door.",
    "Rainee set the tray aside and looked at the door.",
]
for index, text in enumerate(GOOD):
    CASES.append({"id": f"good_{index}", "original": BASE, "candidate": text, "expect_reject": False})


def main() -> int:
    target = Path("tests/fixtures/guards_adversarial.json")
    target.write_text(
        json.dumps({"fixture": "adversarial correction cases", "cases": CASES}, indent=2),
        encoding="utf-8",
    )
    print(f"written: {target} ({len(CASES)} cases)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
