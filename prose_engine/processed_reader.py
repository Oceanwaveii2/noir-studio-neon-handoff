"""Copy-first import of the authored MO2 reader manuscript as a new workspace."""
from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path

from story_graph.episode_timeline import TimelineStore, encode_graph
from story_graph.scenarios.foxy_mo2_dag import build_foxy_mo2_dag
from .notebook import NotebookStore, _blocks, digest, joined
from .source_migration import publish_workspace, verify_bundle


_NAMES = r'(Francine|Rainee(?:-Peter)?|Haley|Stella|Roger)'
_VERBS = r'(?:said|asked|replied|answered|whispered|shouted|yelled|called|muttered|declared|gasped|announced|exclaimed|snapped|laughed|cried|boomed|murmured|added|smirked|scoffed)'


def _speaker(text):
    """Return a single explicit dialogue attribution; never use name occurrence alone."""
    if not re.search(r'["“”]', text):
        return None
    patterns = [r'["”]\s*[,;.!?—-]*\s*' + _NAMES + r'\s+' + _VERBS + r'\b',
                r'\b' + _NAMES + r'\s+' + _VERBS + r'\s*[:,—-]\s*["“]']
    found = {m.group(1).casefold() for pattern in patterns for m in re.finditer(pattern, text, re.I)}
    return next(iter(found)) if len(found) == 1 else None


def _mo2_graph():
    dag = build_foxy_mo2_dag()
    order = dag.validate()
    nodes = [{'id': node.id, 'title': node.name, 'type': 'beat',
              'data': {'scene': node.scene_id, 'description': node.description,
                       'primary_character': node.primary_character, 'source': 'foxy_mo2_dag'}}
             for node in (dag.nodes[key] for key in order)]
    edges = [{'from': dependency, 'to': key, 'type': 'dependency'}
             for key in order for dependency in dag.nodes[key].dependencies]
    return {'nodes': nodes, 'edges': edges}


def publish_processed_workspace(bundle, destination, manuscript, *, expected_sha256):
    """Create a new workspace; retain its initial 1.0 version as history and backup."""
    source = Path(manuscript)
    raw = source.read_bytes()
    if hashlib.sha256(raw).hexdigest() != expected_sha256:
        raise ValueError('Processed manuscript changed; inspect the new version first')
    text = raw.decode('utf-8-sig')
    if len(re.findall(r'^###\s+SCENE\s+\d+:', text, re.M)) != 7:
        raise ValueError('Expected the seven-scene processed reader manuscript')
    payload = verify_bundle(bundle)
    out = Path(destination).resolve()
    if out.exists():
        raise ValueError('Choose a new processed-workspace destination')
    receipt = publish_workspace(bundle, out)
    store = TimelineStore(out/'timeline.sqlite')
    notebook = NotebookStore(store)
    prior = notebook.open('spring-break')
    episode = store.get_episode('spring-break')
    if (episode['head'] != 1 or prior['revision'] != 1 or prior['timeline_revision'] != 1 or
            prior['masks'] or prior['default_protection'] != 100):
        raise ValueError('Fresh workspace was unexpectedly changed')
    graph = encode_graph(_mo2_graph())
    source_name = 'work/americandad/foxy_mo2_hybrid_novel.md'
    cells = _blocks(text, source_name, 2)
    for cell in cells:
        body = cell['text'].strip()
        if re.match(r'^#{1,6}\s+SCENE\s+\d+:', body, re.I):
            cell['kind'] = 'scene-heading'
        elif re.search(r'["“”]', body):
            speaker = _speaker(body)
            if speaker:
                base = 'rainee' if speaker.startswith('rainee') else speaker
                cell['kind'] = 'character'; cell['speaker'] = base
                cell['form'] = 'peter_griffin_celestial_variant' if speaker == 'rainee-peter' else base
                cell['binding_evidence'] = {'status': 'explicit-named-attribution', 'source': source_name}
            else:
                cell['kind'] = 'unresolved'
        else:
            cell['kind'] = 'narrator'
    if joined(cells) != text:
        raise ValueError('Processed manuscript was not preserved exactly')
    state = {'schema_version':1, 'episode':'spring-break', 'branch':episode['branch'],
             'default_protection':100, 'blocks':cells, 'masks':[], 'stale_masks':[]}
    with store._connect() as c:
        c.execute('BEGIN IMMEDIATE')
        row = c.execute('SELECT * FROM imported_episode_sources WHERE episode=?', ('spring-break',)).fetchone()
        if not row: raise ValueError('Original 1.0 source association is missing')
        c.execute('CREATE TABLE IF NOT EXISTS superseded_source_bindings(episode TEXT, payload TEXT NOT NULL)')
        c.execute('INSERT INTO superseded_source_bindings VALUES(?,?)',('spring-break',json.dumps(dict(row),ensure_ascii=False)))
        # This fresh workspace retains the 1.0 source association in the archive
        # and recovery copy; it must not apply to the separate processed text.
        c.execute('DELETE FROM imported_episode_sources WHERE episode=?',('spring-break',))
        c.execute('INSERT INTO revisions VALUES(?,?,?,?,?,?)',('spring-break',2,graph,text,source_name,digest(text)))
        c.execute('UPDATE episodes SET head=2,title=? WHERE id=?',('Spring Break · Season 3 · Processed MO2','spring-break'))
        c.execute('INSERT INTO notebook_revisions VALUES(?,?,?,?)',('spring-break',2,2,json.dumps(state,ensure_ascii=False)))
        c.execute('UPDATE notebook_heads SET head=2 WHERE episode=?',('spring-break',))
    check = notebook.open('spring-break')
    if check['stale'] or joined(check['blocks']) != text:
        raise ValueError('Processed notebook did not reopen exactly')
    receipt.update({'initial_episode':'spring-break','processed_source':source_name,
                    'processed_source_sha256':expected_sha256,'processed_revision':2,
                    'processed_scenes':7,'processed_blocks':len(cells),
                    'explicit_speaker_blocks':sum(b['kind']=='character' for b in cells),
                    'unresolved_dialogue_blocks':sum(b['kind']=='unresolved' for b in cells),
                    'graph':'foxy_mo2_dag; source dialogue matches are evidence, not timeline cutoffs',
                    'prior_1_0_spring_break':'retained in revision 1 and migration-recovery.sqlite'})
    temp = out/'workspace.processed.tmp'
    with temp.open('xb') as f:
        f.write(json.dumps(receipt,ensure_ascii=False,sort_keys=True).encode('utf-8'))
        f.flush();os.fsync(f.fileno())
    os.replace(temp,out/'workspace.json')
    return receipt
