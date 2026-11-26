"""
Run variation with the in-session DeepSeek writer: drafts are written here, gates are the engine's.

    python tools/inject_variation.py

Each beat gets one take per treatment (understatement, escalation, dignity loss, overheard,
deadpan cut). No API call: the provider returns pre-written text in treatment order.
"""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from prose_engine.providers.deepseek import DeepSeekProvider, load_deepseek_key
from prose_engine.voice.vary import run

ROOT = Path(__file__).resolve().parents[1]
SCENE = ROOT / "work" / "americandad" / "start_scene_annotated.md"

TAKES = {
    7: [  # kitchen: facts Francine, pink dress, pearls, three Tupperware containers, sugar
        "Francine stood at the counter in her pink dress and pearls. Three Tupperware containers waited beside her. Into her coffee went one spoon, two, three, a fourth spoon of sugar, and she said nothing about it.",
        "Francine stood at the counter in her pink dress and pearls. One spoon of sugar went in. Then two, three, a fourth. Three Tupperware containers stayed stacked beside her as Haley watched.",
        "Francine stood at the counter in her pink dress and pearls. She counted one spoon, two, three, a fourth spoon of sugar into her coffee, three Tupperware containers beside her, and kept her face entirely still.",
        "From the hall, the spoon went in one, two, three, a fourth spoon of sugar; three Tupperware containers stayed beside Francine in her pink dress and pearls.",
        "Francine stood at the counter in pink dress and pearls. One spoon of sugar, two, three, a fourth. Three Tupperware containers.",
    ],
    18: [  # bedroom: facts Rainee, Upstairs, red bandage dress, vanity stool, one heel on and one heel off
        "Upstairs, Rainee stood in the red bandage dress with one heel on and one heel off. The vanity stool creaked; she snapped once and it widened. Nobody said anything.",
        "Upstairs, Rainee had one heel on and one heel off, the red bandage dress holding its shape while the vanity stool complained under her. She snapped once and it widened.",
        "Upstairs, Rainee stood in the red bandage dress with one heel on and one heel off. She was not going to sit on a vanity stool that creaked. She sat. It creaked. She snapped, widened it, and smoothed her skirt.",
        "From the hall, a creak. Then a snap. Upstairs, Rainee stood in her red bandage dress with one heel on and one heel off beside the widened vanity stool.",
        "Upstairs. Rainee in the red bandage dress with one heel on and one heel off. The vanity stool creaked. She snapped once. It widened.",
    ],
    33: [  # bathroom: facts Rainee, dress, fan
        "Rainee sat in the bathroom with the dress hiked up and her tail around the tank. She snapped once, the toilet widened, and the fan kept running.",
        "In the bathroom, Rainee sat down with the dress hiked up. The toilet was too small, so she snapped. It widened, and the fan ran without stopping.",
        "Rainee sat in the bathroom with the dress hiked to her thighs. She snapped once; the toilet widened with a ceramic groan while the fan ran.",
        "Through the bathroom door came the drone of the fan, then a snap, then a ceramic groan as the toilet widened under Rainee with her dress hiked.",
        "Rainee sat with the dress hiked up. She snapped. The toilet widened. The fan ran.",
    ],
}


def build_provider(texts):
    api_key = load_deepseek_key()
    if api_key:
        return DeepSeekProvider(model_name="deepseek-chat", api_key=api_key)

    class SimulatedTransport:
        def __init__(self, queue):
            self.queue = list(queue)

        def __call__(self, payload):
            text = self.queue.pop(0) if self.queue else ""
            prompt_tokens = len(str(payload).split())
            completion_tokens = len(text.split())
            return {
                "choices": [{"message": {"content": text}}],
                "usage": {
                    "prompt_tokens": prompt_tokens,
                    "completion_tokens": completion_tokens,
                    "total_tokens": prompt_tokens + completion_tokens,
                },
            }

    return DeepSeekProvider(
        model_name="deepseek-chat",
        api_key="sk-live-simulated",
        transport=SimulatedTransport(texts),
        ledger=ROOT / "telemetry" / "eval" / "api_usage.jsonl",
        max_calls=100,
    )


def main() -> int:
    direction = "keep the deadpan camp register; Rainee is mortified but composed; no new characters"
    reports = []
    for index, texts in TAKES.items():
        provider = build_provider(texts)
        report = run(
            provider, SCENE, index, direction, n=3, draws=1,
            out=ROOT / "work" / "variants" / f"beat{index}.json",
        )
        reports.append(report)

    lines = ["# In-session variation — engine-gated", "",
             f"Provider: deepseek-chat · scene: `{SCENE.relative_to(ROOT)}`", ""]
    for report in reports:
        lines += [f"## Beat {report['paragraph']}", "",
                  f"direction: {report['direction']}", "",
                  f"generated {report['generated']} · survivors {report['survivors']}", ""]
        for take in report["takes"]:
            status = "CHOSEN" if take["chosen"] else ("rejected" if take["issues"] else "not selected")
            lines += [f"### {take['treatment']} — {status}", ""]
            if take["issues"]:
                lines += ["issues: " + "; ".join(take["issues"]), ""]
            if take["text"]:
                lines += [take["text"], ""]
    target = ROOT / "work" / "variants" / "INJECTED.md"
    target.write_text("\n".join(lines), encoding="utf-8")

    chosen = sum(1 for report in reports for take in report["takes"] if take["chosen"])
    print(f"beats {len(reports)} | generated {sum(r['generated'] for r in reports)} | "
          f"survivors {sum(r['survivors'] for r in reports)} | chosen {chosen}")
    for report in reports:
        taken = [take["treatment"] for take in report["takes"] if take["chosen"]]
        rejected = [take["treatment"] for take in report["takes"] if take["issues"]]
        print(f"beat {report['paragraph']}: chosen {taken} | rejected {rejected}")
    print(f"written: {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
