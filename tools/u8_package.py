"""Build an application-code-only wheel in a new local directory."""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[1]
PACKAGES = ("prose_engine", "story_graph", "telemetry", "tools")
RUNTIME_FILES = (
    'prose_engine/data/ai_voice_negatives.json', 'tools/__init__.py', 'tools/studio_ui.py',
    'tools/studio_form_store.py', 'tools/studio_media_http.py', 'tools/studio_clip_http.py',
    'tools/noir_client.py', 'tools/workbench_remote.py',
    'tools/v2_page.html', 'tools/world_laws_page.html', 'tools/timeline_page.html', 'tools/compose_blocks.js',
    'tools/scene_fragments_page.html', 'tools/scene_replay_page.html', 'tools/scene_minds_page.html',
    'tools/scene_clips_page.html', 'tools/scene_branches_page.html', 'tools/mind_inspector_page.html',
    'tools/fx06_page.html', 'tools/processing_page.html', 'tools/beat_media_page.html',
    'tools/racing_compare.html', 'tools/character_graph_comparison.html',
    'tools/assets/studio_body.html', 'tools/assets/studio_styles.css', 'tools/assets/studio_client.js',
    'tools/assets/studio_default_graph.json', 'tools/assets/workbench_connected.html', 'tools/assets/workbench_connected.js',
    'tools/assets/processing.css', 'tools/assets/processing.js', 'tools/assets/beat_media.js',
    'tools/vendor/litegraph.min.js', 'tools/vendor/litegraph.css', 'tools/vendor/cytoscape.min.js',
)


def is_link(path: Path) -> bool:
    info = path.lstat()
    return stat.S_ISLNK(info.st_mode) or bool(
        getattr(info, "st_file_attributes", 0) & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    )


def source_files():
    yield ROOT / "pyproject.toml"
    for package in PACKAGES[:-1]:
        base = ROOT / package
        if not base.is_dir() or is_link(base):
            raise ValueError(f"Application package is unavailable: {package}")
        for folder, directories, files in os.walk(base, followlinks=False):
            parent = Path(folder)
            directories[:] = sorted(name for name in directories
                                     if name != "__pycache__" and not is_link(parent / name))
            for name in sorted(files):
                source = parent / name
                if not is_link(source) and (name.endswith(".py") or name == "py.typed"):
                    yield source
    required = {ROOT/name for name in RUNTIME_FILES}
    assets = ROOT/'tools/assets'
    required.update(p for pattern in ('v2/*.css','v2/*.js','noir-*.gif','noir-*.png') for p in assets.glob(pattern))
    required.update((ROOT/'tools/vendor').glob('*LICENSE*.txt'))
    for path in sorted(required):
        if not path.is_file():
            raise ValueError(f'Missing application component: {path.relative_to(ROOT)}')
        if any(is_link(parent) for parent in (path, *path.parents) if parent.is_relative_to(ROOT) and parent != ROOT):
            raise ValueError(f'Linked application file: {path.relative_to(ROOT)}')
        yield path


def build(out: Path) -> Path:
    out.mkdir(parents=True, exist_ok=False)
    staging = out / "source"
    staging.mkdir()
    for source in source_files():
        target = staging / source.relative_to(ROOT)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
    wheels = out / "wheel"
    wheels.mkdir()
    cmd = [sys.executable, "-B", "-m", "pip", "wheel", "--no-index", "--no-deps",
           "--no-build-isolation", "--wheel-dir", str(wheels.resolve()), str(staging.resolve())]
    env = os.environ.copy()
    # Wheel ZIP timestamps otherwise vary even when every source byte is identical.
    env.update(SOURCE_DATE_EPOCH="315532800", PYTHONDONTWRITEBYTECODE="1")
    run = subprocess.run(cmd, capture_output=True, text=True, timeout=180, env=env)
    if run.returncode:
        raise RuntimeError("Wheel build failed: " + (run.stderr or run.stdout)[-1000:])
    found = list(wheels.glob("*.whl"))
    if len(found) != 1:
        raise RuntimeError("Expected exactly one wheel.")
    with zipfile.ZipFile(found[0]) as archive:
        names = archive.namelist()
        if any(not (name.startswith(tuple(p + "/" for p in PACKAGES))
                    or name.startswith("prose_engine-0.1.0.dist-info/")) for name in names):
            raise ValueError("Wheel contains an unexpected path.")
        for required in ('prose_engine/__init__.py', 'story_graph/__init__.py',
                         'telemetry/engine_run_logger.py', *RUNTIME_FILES):
            if required not in names:
                raise ValueError(f"Wheel is missing {required}.")
    return found[0]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True, help="new local directory")
    args = parser.parse_args()
    try:
        wheel = build(args.out)
    except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired) as exc:
        parser.exit(2, f"Release package unavailable: {exc}\n")
    print(f"Built code-only wheel: {wheel}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
