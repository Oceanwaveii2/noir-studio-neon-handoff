"""Versioned Antigravity 1.0 data adapter; never executes its code or promotes canon."""
from __future__ import annotations

from dataclasses import replace
import hashlib
import json
from pathlib import Path
import re

from .character_forms import AFM_JUNCTIONS, CharacterForm, CharacterJunction

ADAPTER = 'antigravity-data-v1'


def sha(data):
    return hashlib.sha256(data).hexdigest()


def encoded(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True).encode('utf-8')


def load_source(root):
    root = Path(root).resolve()
    names = ['HOT_SCOOMP_COMPLETE_CHRONOLOGY.md', 'out/graphs/master.graph.json',
             'out/graphs/master.chain.json', 'out/graphs/master.report.json']
    config = root / 'narrative_composer/config'
    names += [p.relative_to(root).as_posix() for p in sorted(config.rglob('*')) if p.is_file() and p.suffix in ('.json', '.md')]
    data = {}
    for name in names:
        path = root / name
        if path.is_symlink() or not path.is_file() or path.stat().st_size > 10_000_000:
            raise ValueError('Missing, linked or oversized source: ' + name)
        data[name] = path.read_bytes()
    return adapt(data, str(root))


def adapt(data, origin='fixture'):
    text = data['HOT_SCOOMP_COMPLETE_CHRONOLOGY.md'].decode('utf-8-sig')
    objects = {p: json.loads(b.decode('utf-8-sig')) for p, b in data.items() if p.endswith('.json')}
    graph = objects['out/graphs/master.graph.json']; chain = objects['out/graphs/master.chain.json']
    report = objects['out/graphs/master.report.json']
    if any(x.get('schema_version') != 1 for x in (graph, chain)):
        raise ValueError('Unsupported Antigravity schema')
    sources = [n['params']['text'] for n in chain['nodes'] if n['type'] == 'text_source']
    if len(sources) != 1 or sources[0].replace('\r\n', '\n') != text.replace('\r\n', '\n'):
        raise ValueError('Operator-chain source does not correspond to chronology')
    lines = text.splitlines(keepends=True); offsets = [0]
    for line in lines: offsets.append(offsets[-1] + len(line))
    headings = [(i, line) for i, line in enumerate(lines) if re.match(r'^#\s+', line)]
    spring = [(i, line) for i, line in headings if 'SPRING BREAK' in line.upper()]
    if len(spring) != 1:
        raise ValueError('Spring Break section is missing or ambiguous')
    first = spring[0][0]; last = next((i for i, _ in headings if i > first), len(lines))
    files = [{'path': p, 'sha256': sha(b), 'bytes': len(b)} for p, b in sorted(data.items())]
    edition = 'ag1-' + sha(encoded(files))[:20]
    definitions = {}
    for path, item in objects.items():
        if '/config/graph/characters/' in path:
            cid = item['entity_id']
            if cid in definitions: raise ValueError('Duplicate source character identity')
            definitions[cid] = {**item, 'source_path': path}
    # Only explicit dialogue discoveries are identity evidence. Action-word guesses stay archived.
    for item in report.get('discoveries', {}).get('entities', []):
        cid = item['entity_id']
        if cid not in definitions and item.get('evidence', '').startswith('Dialogue speaker cue'):
            definitions[cid] = {'entity_id': cid, 'display_name': item['display_name'], 'base_state': 'base',
                'aliases': [item['display_name'].upper()], 'states': [], 'transforms': [],
                'source_path': 'out/graphs/master.report.json', 'discovered': True}
    ids = set()
    for kind in ('state_instances', 'transform_instances'):
        for item in graph[kind]:
            line = item['at']['line']
            if item['id'] in ids or type(line) is not int or not 1 <= line <= len(lines):
                raise ValueError('Invalid or duplicate graph line anchor')
            ids.add(item['id'])
    return {'schema_version': 1, 'adapter': ADAPTER, 'edition': edition, 'origin': origin,
            'files': files, 'text': text, 'line_offsets': offsets, 'graph': graph, 'chain': chain, 'report': report,
            'definitions': definitions, 'raw_config': {p: v for p, v in objects.items() if '/config/' in p},
            'sections': [{'episode': 'afm-prelude', 'title': 'Antigravity 1.0 · Prequel', 'start': 0, 'end': offsets[first], 'line': 1},
                         {'episode': 'spring-break', 'title': 'Spring Break · Season 3 · Antigravity 1.0', 'start': offsets[first], 'end': offsets[last], 'line': first + 1},
                         {'episode': 'hot-scoomp', 'title': 'Hot Scoomp · Antigravity 1.0', 'start': offsets[last], 'end': len(text), 'line': last + 1}],
            'correspondence': 'exact-codepoints' if sources[0] == text else 'CRLF/LF-only; original bytes retained',
            'diagnostics': {'canon_leaks': graph.get('canon_leaks', []), 'unresolved_cues': graph.get('unresolved_cues', []),
                            'violations': report.get('violations', []),
                            'policy': 'Historical diagnostics retained, not adjudicated. No imported record is an approved canon event.'}}


def form_id(payload, cid, state):
    definition = payload['definitions'][cid]
    if state == cid + '.state.' + definition['base_state']:
        return cid
    return payload['edition'] + ':' + state


def source_junctions(payload):
    result = {}
    for cid, d in payload['definitions'].items():
        forms = [CharacterForm(cid, d['display_name'], 'base')]
        for state in d.get('states', []):
            ident = form_id(payload, cid, state['id'])
            if ident != cid:
                forms.append(CharacterForm(ident, state['label'], 'transformation'))
        result[cid] = CharacterJunction(cid, tuple(forms))
    return result


def merge_junctions(base, imported):
    result = dict(base)
    for cid, group in imported.items():
        if cid not in result: result[cid] = group; continue
        existing = result[cid]
        known = {f.id for f in existing.forms}
        result[cid] = replace(existing, forms=existing.forms + tuple(f for f in group.forms if f.id not in known))
    return result


def editions(c):
    if not c.execute("SELECT 1 FROM sqlite_master WHERE name='imported_editions'").fetchone(): return []
    result = []
    for row in c.execute('SELECT payload,sha256 FROM imported_editions ORDER BY id'):
        raw = row['payload'].encode('utf-8')
        if sha(raw) != row['sha256']: raise ValueError('Imported edition fingerprint changed')
        result.append(json.loads(raw))
    return result


def junctions(c, base=None):
    result = dict(AFM_JUNCTIONS if base is None else base)
    for payload in editions(c): result = merge_junctions(result, source_junctions(payload))
    from .fx06_scene import add_forms
    from .form_graph_store import cue_junctions
    return merge_junctions(add_forms(c, result), cue_junctions(c))


def binding(c, episode):
    if not c.execute("SELECT 1 FROM sqlite_master WHERE name='imported_episode_sources'").fetchone(): return None
    row = c.execute('SELECT * FROM imported_episode_sources WHERE episode=?', (episode,)).fetchone()
    if not row: return None
    payload = next((p for p in editions(c) if p['edition'] == row['edition']), None)
    if payload is None: raise ValueError('Imported episode has no edition')
    return dict(row), payload


def active_at(payload, point, *, floor=0):
    active = {}; records = {}
    for item in sorted(payload['graph']['state_instances'], key=lambda value: value['at']['line']):
        cid = item['entity']; offset = payload['line_offsets'][item['at']['line'] - 1]
        if cid not in payload['definitions'] or item['source'] == 'inferred_intermediate' or not floor <= offset <= point: continue
        # Saved evidence must actually occur at its claimed line; unanchored machine guesses are held.
        line = payload['text'][offset:payload['line_offsets'][item['at']['line']]]
        if not item.get('evidence') or item['evidence'] not in line: continue
        definition = payload['definitions'][cid]
        states = {s['id'] for s in definition.get('states', [])}
        if item['state_id'] not in states and item['state_id'] != cid+'.state.'+definition['base_state']: continue
        active[cid] = form_id(payload, cid, item['state_id']); records[cid] = item
    return active, records


def snapshot(c, episode, revision, script, graph_hash, start, end, viewpoint=None):
    found = binding(c, episode)
    if found is None: return None
    link, payload = found
    if graph_hash != link['graph_sha256']:
        raise ValueError('Imported source graph changed; restore it or reimport a distinct version')
    original = payload['text'][link['start']:link['end']]
    alignment = 'exact-original'
    if script == original:
        point = link['start'] + start
    else:
        # Earlier edits may shift positions. Only reuse an exact, ordered,
        # source-anchored block; otherwise fall back to the episode start.
        point = link['start']
        alignment = 'conservative-episode-start'
        if c.execute("SELECT 1 FROM sqlite_master WHERE name='notebook_heads'").fetchone():
            row = c.execute('''SELECT r.payload,r.timeline_revision FROM notebook_heads h
                               JOIN notebook_revisions r ON r.episode=h.episode AND r.revision=h.head
                               WHERE h.episode=?''', (episode,)).fetchone()
            if row is not None and row['timeline_revision'] == revision:
                state = json.loads(row['payload'])
                blocks = state.get('blocks', [])
                if ''.join(b.get('text', '') for b in blocks) == script:
                    position = 0; ranges = []; ordered = True; previous = link['start']
                    for block in blocks:
                        text = block.get('text', ''); source = block.get('source') or {}
                        origin = source.get('global_start'); a0 = source.get('start'); b0 = source.get('end')
                        if (source.get('edition') == payload['edition'] and type(origin) is int and
                                type(a0) is int and type(b0) is int and b0 >= a0):
                            length = b0 - a0
                            if origin < previous or not link['start'] <= origin <= origin + length <= link['end']:
                                ordered = False
                            previous = origin + length
                            original_block = payload['text'][origin:origin+length]
                            if text == original_block and sha(original_block.encode('utf-8')) == source.get('sha256'):
                                ranges.append((position, position+len(text), origin))
                        position += len(text)
                    matches = [(a,b,o) for a,b,o in ranges if a <= start < b]
                    if ordered and len(matches) == 1:
                        a, _, origin = matches[0]
                        point = origin + start - a
                        alignment = 'unchanged-source-block'
    # Historical forms from earlier sections are evidence, not proof they
    # remained active across episodes. Approved timeline events handle carryover.
    active, records = active_at(payload, point, floor=link['start'])
    projected = []
    for cid, ident in sorted(active.items()):
        definition = payload['definitions'][cid]
        state = next((s for s in definition.get('states', []) if form_id(payload, cid, s['id']) == ident), None)
        projected.append({'character_id': cid, 'display_name': definition['display_name'], 'active_form': ident,
                          'state_id': records[cid]['state_id'], 'state_label': state['label'] if state else definition['display_name'],
                          'port_id': f'character:{cid}:form:{ident}', 'source_node': records[cid]['id'],
                          'source_line': records[cid]['at']['line'], 'evidence': records[cid]['evidence'],
                          'source_kind': records[cid]['source'], 'live_node_status': 'unavailable',
                          'personality_relationship_knowledge': 'held-unscoped-source-profile'})
    return {'edition': payload['edition'], 'adapter': ADAPTER, 'as_of_source_offset': point,
            'source_sha256': sha(payload['text'].encode('utf-8')), 'characters': projected,
            'status': 'historical-source-evidence-not-canon', 'viewpoint': viewpoint, 'alignment': alignment,
            'diagnostic_counts': {'canon_leaks': len(payload['diagnostics']['canon_leaks']),
                                  'unresolved_cues': len(payload['diagnostics']['unresolved_cues'])},
            'note': 'Use only as evidence for this exact source version. It does not approve events, resolve diagnostics, supply private knowledge or establish a live character mind.'}


def aliases(payload):
    result = {}
    for cid, d in payload['definitions'].items():
        for cue in set(d.get('aliases', []) + [d['display_name'].upper()]):
            result.setdefault(cue.upper(), set()).add((cid, None))
        for state in d.get('states', []):
            for cue in state.get('cue_aliases', []):
                name = cue['cue'].upper()
                result.setdefault(name, set())
                result[name].discard((cid, None)); result[name].add((cid, form_id(payload, cid, state['id'])))
    return result


def blocks(payload, section):
    """Exact line-preserving blocks: a cue owns following speech, not action paragraphs."""
    script = payload['text'][section['start']:section['end']]
    lookup = aliases(payload); parts = re.split(r'((?:\r\n|\r(?!\n)|\n)[ \t]*(?:\r\n|\r(?!\n)|\n)+)', script)
    chunks = [parts[i] + (parts[i+1] if i+1 < len(parts) else '') for i in range(0, len(parts), 2)]
    result = []; offset = 0; pending = None
    for chunk in chunks:
        if not chunk: continue
        stripped = chunk.strip(); first = stripped.splitlines()[0] if stripped else ''
        cue = re.sub(r"\s*\((?:CONT['’]?D|O\.S\.|V\.O\.)\)\s*$", '', first.strip('* ')).upper()
        owners = lookup.get(cue, set()) if first.strip('* ') == first.strip('* ').upper() else set()
        kind = 'narrator'; speaker = form = None; status = 'narration'
        if stripped.startswith('#') or re.match(r'^`?(?:INT\.|EXT\.|INT/EXT\.)', stripped):
            kind = 'scene-heading'; pending = None
        elif len(owners) == 1:
            speaker, form = next(iter(owners)); kind = 'character'; status = 'explicit-source-cue'; pending = (speaker, form)
            if form is None:
                form = active_at(payload,section['start']+offset,floor=section['start'])[0].get(speaker,speaker)
                pending = (speaker,form)
        elif stripped.startswith(('"', '“', '(')) and pending:
            speaker, form = pending; kind = 'character'; status = 'adjacent-source-dialogue'
        else:
            pending = None
            if first == first.upper() and re.search(r'[A-Z]', first) and len(first) < 90 and not stripped.startswith(('#', '---')):
                kind = 'unresolved'; status = 'ambiguous-or-unmatched-cue'
        ident = payload['edition'] + '-' + str(section['start'] + offset)
        result.append({'id': ident, 'kind': kind, 'speaker': speaker, 'form': form, 'text': chunk,
                       'source': {'name': payload['edition'], 'timeline_revision': 1, 'start': offset,
                                  'end': offset+len(chunk), 'sha256': sha(chunk.encode('utf-8')),
                                  'global_start': section['start']+offset, 'edition': payload['edition']},
                       'binding_evidence': {'status': status, 'cue': first if speaker else None}})
        offset += len(chunk)
    if ''.join(b['text'] for b in result) != script: raise ValueError('Imported blocks changed source text')
    return result
