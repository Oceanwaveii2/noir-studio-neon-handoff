"""Register an existing FX06 evidence packet on an explicitly selected timeline."""
from __future__ import annotations

import argparse
from decimal import Decimal
from hashlib import file_digest
import json
from pathlib import Path

from prose_engine.evidence_exchange import TIMING_PAIR, install_appearance, install_catalog
from story_graph.episode_timeline import TimelineStore


def sha(path):
    with Path(path).open('rb') as stream:
        return file_digest(stream, 'sha256').hexdigest()


def _source(manifest, ident, availability, path):
    rows = [item for item in manifest['sources'] if item['id'] == ident]
    if len(rows) != 1 or rows[0]['availability'] != availability or rows[0]['sha256'] != sha(path):
        raise ValueError('The selected file does not match the inspected handoff source')
    return rows[0]


def _microseconds(seconds):
    exact = Decimal(str(seconds)) * 1_000_000
    if not exact.is_finite() or exact != exact.to_integral_value():
        raise ValueError('Handoff clock is more precise than integral microseconds or is not finite')
    return int(exact)


def load_catalog(handoff, clip, diagram, draft, *, source_id='src-fusion'):
    manifest = json.loads((handoff/'clip_manifest.json').read_text('utf-8'), parse_float=Decimal)
    source = _source(manifest, source_id, 'file_inspected', clip)
    visual = None
    if diagram is not None:
        image = _source(manifest, 'src-diagram', 'image_inspected', diagram)
        visual = {'id': image['id'], 'sha256': image['sha256'], 'region': [0, 0, 10_000, 10_000]}
    selected = []
    with (handoff/'evidence_packet.jsonl').open(encoding='utf-8') as rows:
        for line in rows:
            if not line.strip():
                continue
            item = json.loads(line, parse_float=Decimal)
            if (item.get('kind') != 'observation' or item.get('source_id') != source_id or
                    item.get('modality') != 'visible' or item.get('confidence') != 'direct_sample' or
                    item.get('time_basis') != 'file_pts' or item.get('observable_action') not in TIMING_PAIR):
                continue
            if (item['source_sha256'] != source['sha256'] or item.get('canon_eligible') is not False or
                    item.get('personality_eligible') is not False):
                raise ValueError('Handoff observation is not timing-only evidence from the matched file')
            selected.append({'id': item['id'], 'range_us': list(map(_microseconds, item['time_s'])),
                             'observation': item['observable_action'], 'method': item['timing_method'],
                             'actor_identity': item['actor_identity'], 'speaker_identity': item['speaker_identity']})
    return {'clip': {'id': source_id, 'sha256': source['sha256'], 'duration_us': _microseconds(source['duration_s'])},
            'visual': visual, 'draft': draft, 'evidence': selected}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    for name in ('timeline', 'scope'):
        p.add_argument('--'+name, required=True, type=Path)
    for name in ('handoff', 'clip'):
        p.add_argument('--'+name, type=Path)
    p.add_argument('--result', required=True)
    p.add_argument('--draft')
    p.add_argument('--diagram', type=Path)
    p.add_argument('--appearance', type=Path, help='Versioned appearance catalog JSON')
    p.add_argument('--image', type=Path, help='Original bytes for the appearance catalog')
    args = p.parse_args()
    if not args.timeline.is_file():
        p.error('Choose an existing copied timeline')
    try:
        scope = json.loads(args.scope.read_text('utf-8'))
        if args.appearance:
            if not args.image or any((args.handoff, args.clip, args.draft, args.diagram)):
                p.error('Use --appearance with --image and its saved branch result')
            from PIL import Image
            catalog = json.loads(args.appearance.read_text('utf-8'))
            with Image.open(args.image) as source:
                if (source.format not in ('JPEG', 'PNG', 'WEBP') or source.size !=
                        (catalog['image']['width'], catalog['image']['height'])):
                    raise ValueError('The appearance image format or dimensions do not match')
                source.verify()
            if catalog['image']['sha256'] != sha(args.image):
                raise ValueError('The appearance image fingerprint does not match')
            digest = install_appearance(TimelineStore(args.timeline), scope, args.result, catalog)
            print(json.dumps({'schema_version':1, 'appearance_sha256':digest, 'observations':len(catalog['evidence'])}))
            return
        if not (args.handoff and args.clip and args.draft) or args.image:
            p.error('Use --handoff, --clip and --draft to register timing evidence')
        catalog = load_catalog(args.handoff, args.clip, args.diagram, args.draft)
        install_catalog(TimelineStore(args.timeline), scope, args.result, catalog)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        p.exit(2, f'Could not register exchange evidence: {exc}\n')
    print(f'Registered {len(catalog["evidence"])} sampled timings for {args.result}')


if __name__ == '__main__':
    main()
