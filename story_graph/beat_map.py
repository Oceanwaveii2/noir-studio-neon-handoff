"""Conservative, source-linked projection of saved episode passages.

Paragraphs are provisional beats, not inferred story facts. Their order is
not evidence that a timeline event has already occurred.
"""
from __future__ import annotations

import hashlib
from bisect import bisect_left
import json
import re
import unicodedata
from pathlib import Path

_PARAGRAPH = re.compile(r'[^\r\n]+(?:(?:\r\n|\r(?!\n)|\n)(?![\t ]*(?:\r\n|\r(?!\n)|\n))[^\r\n]+)*')
_SCENE = re.compile(r'^(?:#{1,6}\s*)?(?:\*\*)?(?:INT\.|EXT\.|INT/EXT\.|I/E\.|SCENE\s+\d+\b)', re.I)
_REFERENCE_ROOT = Path(__file__).resolve().parents[1]


def _normalized(text):
    text=unicodedata.normalize('NFKC',text).casefold().translate(str.maketrans({'’':"'",'“':'"','”':'"','—':'-','–':'-'}))
    return re.sub(r'\s+',' ',text).strip()


def _link_unique_dialogue(text, beats, graph):
    """Attach unambiguous dialogue evidence; never infer a beat boundary."""
    full=_normalized(text)
    passages=[_normalized(beat['text']) for beat in beats]
    order=graph.validate();queries={}
    for number,ident in enumerate(order,1):
        node=graph.nodes[ident]
        for line in node.raw_dialogue:
            query=_normalized(line.get('text',''))
            if query: queries.setdefault(query,[]).append((number,ident,node.name))
    candidates={}
    for query,owners in queries.items():
        if len({item[1] for item in owners})!=1 or full.count(query)!=1:continue
        locations=[i for i,passage in enumerate(passages) if query in passage]
        if len(locations)!=1:continue
        number,ident,name=owners[0]
        candidates.setdefault(locations[0],{})[ident]={'beat_id':ident,'number':number,'name':name,
                                                        'evidence':'unique normalized dialogue match'}
    for index,matches in candidates.items():
        if len(matches)==1:beats[index]['graph_match']=next(iter(matches.values()))
        else:beats[index]['graph_match_status']='ambiguous'


def _saved_scene_starts(c, episode, revision, text):
    """Use typed headings only from a notebook that matches this source exactly."""
    if not c.execute("SELECT 1 FROM sqlite_master WHERE name='notebook_heads' AND type='table'").fetchone():
        return ()
    head = c.execute("""SELECT r.payload, r.timeline_revision
        FROM notebook_heads h JOIN notebook_revisions r ON r.episode=h.episode AND r.revision=h.head
        WHERE h.episode=?""", (episode,)).fetchone()
    if head is None or head['timeline_revision'] != revision:
        return ()
    blocks = json.loads(head['payload'])['blocks']
    if ''.join(block['text'] for block in blocks) != text:
        return ()
    cursor, starts = 0, []
    for block in blocks:
        raw = block['text']
        if block['kind'] == 'scene-heading' and raw.strip():
            first = re.search(r'[^\r\n]*\S[^\r\n]*', raw)
            if first:
                starts.append(cursor + first.start())
        cursor += len(raw)
    return tuple(starts)


def _passage_ranges(text, scene_starts):
    for match in _PARAGRAPH.finditer(text):
        start, end = match.span()
        first = bisect_left(scene_starts, start)
        last = bisect_left(scene_starts, end, first)
        for boundary in scene_starts[first:last]:
            if boundary > start:
                yield start, boundary, start in scene_starts
            start = boundary
        yield start, end, start in scene_starts


def map_episode(store, episode, revision, *, viewpoint=None, _connection=None):
    if _connection is None:
        with store._connect() as c:
            c.execute('BEGIN')
            return map_episode(store, episode, revision, viewpoint=viewpoint, _connection=c)
    from .universe_scope import verify_scope
    if type(revision) is not int:
        raise ValueError('A saved episode revision is required')
    c = _connection
    ep = c.execute('SELECT * FROM episodes WHERE id=?', (episode,)).fetchone()
    if ep is None: raise ValueError('Unknown episode')
    row = c.execute('SELECT * FROM revisions WHERE episode=? AND revision=?', (episode, ep['head'])).fetchone()
    item = dict(ep, script=row['script'], source_name=row['source_name'])
    if item['head'] != revision:
        raise ValueError('Episode changed; refresh the beat map')
    text = item['script']
    source = hashlib.sha256(text.encode('utf-8')).hexdigest()
    if source != row['script_sha256']:
        raise ValueError('Episode text does not match its saved fingerprint')
    scene_starts = _saved_scene_starts(c, episode, revision, text)
    scenes, beats = [], []

    def scene(title, explicit):
        number = len(scenes) + 1
        result = {'id': f'scene-{number}', 'title': title, 'explicit': explicit, 'beats': []}
        scenes.append(result)
        return result

    current = None
    for start, end, typed_scene in _passage_ranges(text, scene_starts):
        raw = text[start:end]
        if not raw.strip():
            continue
        line_end = re.search(r'\r\n|\r|\n', raw)
        first = raw[:line_end.start()] if line_end else raw
        if typed_scene or _SCENE.match(first.strip()):
            current = scene(first.strip(), True)
            current['heading_range'] = {'start': start, 'end': start + len(first),
                                        'sha256': hashlib.sha256(first.encode('utf-8')).hexdigest()}
            if not line_end or not raw[line_end.end():].strip():
                continue
            start += line_end.end()
            raw = text[start:end]
        if current is None:
            current = scene('Unmarked scene', False)
        number = len(beats) + 1
        anchor = hashlib.sha256(f'{episode}\0{revision}\0{source}\0{start}\0{end}'.encode()).hexdigest()[:20]
        entry = {'id': 'passage-' + anchor, 'number': number, 'scene_id': current['id'],
                 'start': start, 'end': end, 'text': raw, 'scope_beat': 0,
                 'timing': 'unverified'}
        beats.append(entry)
        current['beats'].append(entry['id'])
    identity = verify_scope(c)
    result={'episode': episode, 'branch': item['branch'], 'revision': revision,
            'project_id': identity['project_id'], 'universe_id': identity['universe_id'],
            'source_name': item['source_name'], 'source_sha256': source,
            'graph_sha256': hashlib.sha256(row['graph'].encode('utf-8')).hexdigest(),
            'method': 'typed-scene-paragraphs-provisional-v1' if scene_starts else 'paragraphs-provisional-v1',
            'scenes': scenes, 'beats': beats}
    if identity.get('kind')=='afm-starters' and episode=='spring-break':
        root=_REFERENCE_ROOT
        paths=(('work/americandad/foxy_mo2_hybrid_novel.md','mo2'),
               ('work/americandad/foxy_mo2_master_stage_directions.md','mo2'),
               ('work/americandad/foxy_spring_breakup_prose_engine_master.md','legacy'))
        for name,kind in paths:
            path=root/name
            if not path.is_file():continue
            # Support the original bytes and previously imported universal-newline
            # copies without treating other textual changes as the same source.
            source_text=path.read_bytes().decode('utf-8-sig')
            normalized_source=source_text.replace('\r\n','\n').replace('\r','\n')
            source_hashes={hashlib.sha256(value.encode('utf-8')).hexdigest() for value in (source_text,normalized_source)}
            if source not in source_hashes:continue
            if kind=='mo2':
                from .scenarios.foxy_mo2_dag import build_foxy_mo2_dag
                graph=build_foxy_mo2_dag();graph_path='story_graph/scenarios/foxy_mo2_dag.py';graph_id='spring-break-mo2'
            else:
                from .scenarios.spring_breakup_dag import build_spring_breakup_dag
                graph=build_spring_breakup_dag();graph_path='story_graph/scenarios/spring_breakup_dag.py';graph_id='spring-breakup-legacy'
            _link_unique_dialogue(text,beats,graph)
            graph_source=root/graph_path
            result['graph_evidence']={'id':graph_id,'beat_count':len(graph.nodes),
                'matched_passages':sum('graph_match' in beat for beat in beats),
                'source':name,'source_sha256':source,
                'graph_sha256':hashlib.sha256(graph_source.read_bytes()).hexdigest(),
                'timing':'unverified'}
            break
    from .beat_anchors import project
    return project(store, c, result, viewpoint)
