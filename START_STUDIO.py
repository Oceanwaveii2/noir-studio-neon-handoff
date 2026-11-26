"""Create a small local demo and launch the packaged Studio app."""
import argparse
from pathlib import Path

from story_graph.episode_timeline import TimelineStore
from story_graph.form_graph_store import FormGraphStore
from tools.studio_ui import run_server


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8788)
    args = parser.parse_args()
    root = Path(__file__).resolve().parent
    local = root / ".noir-demo"
    local.mkdir(exist_ok=True)
    path = local / "timeline.sqlite"
    timeline = TimelineStore(path, project_id="neon-demo", universe_id="night-station")
    if not timeline.cards():
        timeline.create_episode("night-station", "Night Station", "main", 1)
        timeline.save("night-station", 0, script=(
            "INT. NIGHT STATION - NIGHT\n\nThe station clock stopped at six.\n"
            "MARA: Keep the clock still.\n"), source_name="Packaged demonstration fixture")
    forms = FormGraphStore(timeline.form_graph_path)
    for identifier, label in (("mara", "Mara"), ("jules", "Jules")):
        if identifier not in forms.junctions():
            forms.change({"action": "add_character", "revision": forms.read()["revision"],
                          "character_id": identifier, "label": label})
    print(f"Open http://127.0.0.1:{args.port}/v2?episode=night-station", flush=True)
    run_server(port=args.port, timeline_path=path, timeline_only=True, initial_episode="night-station")


if __name__ == "__main__":
    main()
