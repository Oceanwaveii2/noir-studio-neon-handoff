"""Compare two saved texts and append an explicit reconciliation in a new copy."""

from __future__ import annotations

import argparse
import difflib
import json
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from prose_engine.notebook import NotebookStore, digest, joined
from story_graph.episode_timeline import TimelineStore
from tools.u8_recovery import copy_database


def repair(source: Path, out: Path, episode: str, preference: str) -> dict:
    source = source.resolve(strict=True)
    out = out.resolve()
    out.mkdir(parents=True, exist_ok=False)
    target = out / 'timeline.sqlite'
    copy_database(source, target)
    timeline = TimelineStore(target)
    notebook = NotebookStore(timeline)
    ep, nb = timeline.get_episode(episode), notebook.existing(episode)
    if nb is None:
        raise ValueError('This episode has no saved notebook to compare')
    first, second = ep['script'], joined(nb['blocks'])
    episode_sha, notebook_sha = digest(first), digest(second)
    (out / 'comparison.diff').write_bytes(''.join(difflib.unified_diff(
        first.splitlines(keepends=True), second.splitlines(keepends=True),
        fromfile=f'episode-r{ep["head"]}', tofile=f'notebook-r{nb["revision"]}',
    )).encode('utf-8'))
    result = notebook.reconcile_copy(
        episode, preference=preference, timeline_head=ep['head'], notebook_head=nb['revision'],
        episode_sha=episode_sha, notebook_sha=notebook_sha,
    )
    new = TimelineStore(target).get_episode(episode)
    loaded = NotebookStore(TimelineStore(target)).existing(episode)
    selected = second if preference == 'notebook' else first
    if (new['script'] != selected or new['script_sha256'] != digest(selected)
            or loaded is None or loaded['stale'] or joined(loaded['blocks']) != selected):
        raise ValueError('The copied recovery revision could not be verified')
    (out / 'selected-script.txt').write_bytes(selected.encode('utf-8'))
    receipt = {
        'source': str(source), 'copy': str(target), 'episode': episode,
        'original_timeline_revision': ep['head'], 'original_notebook_revision': nb['revision'],
        'episode_sha256': episode_sha, 'notebook_sha256': notebook_sha,
        'selected': preference, 'selected_sha256': digest(selected), 'bytes': len(selected.encode('utf-8')),
        'repaired_timeline_revision': result['timeline_revision'], 'repaired_notebook_revision': result['revision'],
        'protection_default': result['default_protection'], 'protected_masks_carried': len(result['masks']),
        'comparison': 'comparison.diff', 'applied_to_active_project': False,
    }
    (out / 'receipt.json').write_text(json.dumps(receipt, indent=2) + '\n', encoding='utf-8')
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', required=True, type=Path)
    parser.add_argument('--out', required=True, type=Path, help='A new directory for the isolated copy')
    parser.add_argument('--episode', required=True)
    parser.add_argument('--prefer', required=True, choices=('episode', 'notebook'))
    args = parser.parse_args()
    try:
        receipt = repair(args.source, args.out, args.episode, args.prefer)
    except (OSError, ValueError, sqlite3.Error) as exc:
        parser.exit(2, f'Copy repair stopped: {exc}\n')
    print(json.dumps(receipt, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
