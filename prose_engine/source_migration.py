"""Copy-first source publication and notebook migration; no provider dependency."""
from contextlib import closing
import json
import os
from pathlib import Path
import sqlite3
from uuid import uuid4

from story_graph.source_imports import load_source, sha, encoded, blocks, source_junctions
from story_graph.episode_timeline import TimelineStore
from .notebook import NotebookStore


def write_new(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('xb') as f: f.write(data)


def verify_bundle(bundle):
    bundle = Path(bundle)
    receipt = json.loads((bundle/'bundle.json').read_text(encoding='utf-8'))
    raw = (bundle/'payload.json').read_bytes()
    if sha(raw) != receipt['payload_sha256']: raise ValueError('Bundle payload changed')
    payload = json.loads(raw)
    if receipt['edition'] != payload['edition']: raise ValueError('Bundle edition mismatch')
    for item in payload['files']:
        path = bundle/'original'/item['path']
        if path.is_symlink() or not path.is_file() or sha(path.read_bytes()) != item['sha256']:
            raise ValueError('Preserved original changed: '+item['path'])
    return payload


def publish_bundle(source, root):
    payload = load_source(source); target = Path(root)/payload['edition']
    if target.exists():
        existing = verify_bundle(target)
        if existing['files'] != payload['files']: raise ValueError('Existing edition differs')
        return target
    target.mkdir(parents=True, exist_ok=False)
    # Failure leaves an explicitly incomplete new directory; never deletes user data.
    for item in payload['files']:
        data = (Path(source)/item['path']).read_bytes()
        if sha(data) != item['sha256']: raise ValueError('Source changed during migration')
        write_new(target/'original'/item['path'], data)
    raw = encoded(payload); write_new(target/'payload.json', raw)
    write_new(target/'bundle.json', encoded({'status':'COMPLETE','edition':payload['edition'],
              'payload_sha256':sha(raw),'source_root':str(Path(source).resolve())}))
    verify_bundle(target)
    return target


def native_copy(source, destination):
    source = Path(source).resolve(); destination = Path(destination).resolve()
    if destination.exists(): raise ValueError('Backup destination already exists')
    with closing(sqlite3.connect(source.as_uri()+'?mode=ro', uri=True)) as src, closing(sqlite3.connect(destination)) as dst:
        src.backup(dst)
        if dst.execute('PRAGMA integrity_check').fetchone() != ('ok',): raise ValueError('Native copy is corrupt')


def _graph(payload):
    nodes = {}; edges = []
    for cid, d in payload['definitions'].items():
        nodes[cid] = {'id':cid,'type':'source-character','title':d['display_name'],
                      'data':{'edition':payload['edition'],'status':'historical-source-definition'}}
        for state in d.get('states', []):
            nodes[state['id']] = {'id':state['id'],'type':'source-form','title':state['label'],
                                 'data':{'entity':cid,'source':d['source_path'],'live_node':'unavailable'}}
    for kind in ('state_instances','transform_instances'):
        for item in payload['graph'][kind]:
            nodes[item['id']] = {'id':item['id'],'type':'source-state' if kind=='state_instances' else 'source-transition',
                                'title':item.get('state_id',item.get('to_state')), 'data':item}
    for edge in payload['graph']['edges']:
        for ident in (edge['from'],edge['to']):
            if ident not in nodes:
                nodes[ident] = {'id':ident,'type':'source-unresolved','title':ident,'data':{'status':'unresolved-source-reference'}}
        edges.append({'from':edge['from'],'to':edge['to'],'type':edge['type']})
    return {'nodes':list(nodes.values()),'edges':edges}


def publish_workspace(bundle, destination, *, base=None):
    payload = verify_bundle(bundle); out = Path(destination).resolve()
    if out.exists():
        receipt = json.loads((out/'workspace.json').read_text(encoding='utf-8'))
        if receipt['edition'] != payload['edition']: raise ValueError('Destination belongs to another edition')
        with closing(sqlite3.connect((out/'timeline.sqlite').as_uri()+'?mode=ro', uri=True)) as c:
            row = c.execute('SELECT sha256 FROM imported_editions WHERE id=?',(payload['edition'],)).fetchone()
            if row != (sha(encoded(payload)),): raise ValueError('Existing imported edition changed')
        return receipt  # Do not replace author edits on an idempotent rerun.
    out.mkdir(parents=True, exist_ok=False)
    staging = out/'timeline.incomplete.sqlite'
    if base: native_copy(base, staging)
    store = TimelineStore(staging)
    fresh = not store.cards()
    if fresh: store.add_starter_cards()
    branch = 'main' if fresh else payload['edition']
    mapping = {}
    if not fresh:
        with store._connect() as c: c.execute('INSERT INTO branches(id) VALUES(?)',(branch,))
    from story_graph.episode_timeline import encode_graph
    graph = _graph(payload); graph_text = encode_graph(graph)
    with store._connect() as c:
        c.execute('BEGIN IMMEDIATE')
        c.execute('CREATE TABLE IF NOT EXISTS imported_editions(id TEXT PRIMARY KEY,payload TEXT NOT NULL,sha256 TEXT NOT NULL)')
        c.execute('''CREATE TABLE IF NOT EXISTS imported_episode_sources(episode TEXT PRIMARY KEY REFERENCES episodes(id),
            edition TEXT NOT NULL REFERENCES imported_editions(id), start INTEGER NOT NULL,end INTEGER NOT NULL,
            revision INTEGER NOT NULL,graph_sha256 TEXT NOT NULL)''')
        c.execute('INSERT INTO imported_editions VALUES(?,?,?)',(payload['edition'],encoded(payload).decode('utf-8'),sha(encoded(payload))))
        for number, section in enumerate(payload['sections']):
            if section['start'] == section['end']: continue
            eid = section['episode'] if fresh else payload['edition']+'-'+section['episode']
            mapping[section['episode']] = eid
            if not c.execute('SELECT 1 FROM episodes WHERE id=?',(eid,)).fetchone():
                c.execute('INSERT INTO episodes(id,title,branch,position) VALUES(?,?,?,?)',(eid,section['title'],branch,number*10))
                c.execute('INSERT INTO revisions VALUES(?,?,?,?,?,?)',(eid,0,'{"nodes":[],"edges":[]}', '', '',sha(b'')))
            else: c.execute('UPDATE episodes SET title=? WHERE id=?',(section['title'],eid))
            script = payload['text'][section['start']:section['end']]
            c.execute('INSERT INTO revisions VALUES(?,?,?,?,?,?)',(eid,1,graph_text,script,payload['edition'],sha(script.encode('utf-8'))))
            c.execute('UPDATE episodes SET head=1 WHERE id=?',(eid,))
            c.execute('INSERT INTO imported_episode_sources VALUES(?,?,?,?,?,?)',
                      (eid,payload['edition'],section['start'],section['end'],1,sha(graph_text.encode('utf-8'))))
        if not fresh:
            eid=payload['edition']+'-tapped-out'
            c.execute('INSERT INTO episodes(id,title,branch,position) VALUES(?,?,?,30)',(eid,'Tapped Out · no source supplied',branch))
            c.execute('INSERT INTO revisions VALUES(?,?,?,?,?,?)',(eid,0,'{"nodes":[],"edges":[]}', '', '',sha(b'')))
    nb = NotebookStore(store); counts = {}
    for section in payload['sections']:
        eid = mapping.get(section['episode'])
        if not eid: continue
        n = nb.open(eid); bound = blocks(payload,section)
        nb.save(eid,n['revision'],1,bound,100,[],_trusted_structure=True)
        counts[eid] = {'blocks':len(bound),'character_blocks':sum(b['kind']=='character' for b in bound),
                       'unresolved_blocks':sum(b['kind']=='unresolved' for b in bound)}
    # A native recovery copy is made before publication and any writer can open it.
    native_copy(staging, out/'migration-recovery.sqlite')
    os.replace(staging,out/'timeline.sqlite')
    receipt = {'status':'COMPLETE','edition':payload['edition'],'bundle':str(Path(bundle).resolve()),
               'base_timeline':str(Path(base).resolve()) if base else None,'initial_episode':mapping['spring-break'],
               'episodes':mapping,'counts':counts,'default_protection':100,
               'source_diagnostics':payload['diagnostics'],'held_profiles':list(payload['raw_config']),
               'rollback':'Select the prior workspace; original stores and native migration-recovery.sqlite retained.',
               'live_provider_calls':0}
    write_new(out/'workspace.json',encoded(receipt))
    return receipt


def selected_workspace(pointer):
    pointer = Path(pointer)
    if not pointer.is_file(): return None
    data = json.loads(pointer.read_text(encoding='utf-8'))
    if data.get('workspace') is None: return None
    workspace = Path(data['workspace'])
    if sha((workspace/'workspace.json').read_bytes()) != data['workspace_sha256']:
        raise ValueError('Selected migration receipt changed')
    if not (workspace/'timeline.sqlite').is_file(): raise ValueError('Selected migration timeline is missing')
    return workspace, json.loads((workspace/'workspace.json').read_text(encoding='utf-8'))


def activate(workspace, pointer, expected='missing'):
    pointer = Path(pointer); current = pointer.read_bytes() if pointer.exists() else None
    if (sha(current) if current is not None else 'missing') != expected: raise ValueError('Workspace selection changed')
    workspace = Path(workspace).resolve()
    receipt = json.loads((workspace/'workspace.json').read_text(encoding='utf-8'))
    verify_bundle(receipt['bundle'])
    if not (workspace/'timeline.sqlite').is_file(): raise ValueError('Workspace timeline missing')
    data = {'workspace':str(workspace),'workspace_sha256':sha((workspace/'workspace.json').read_bytes()),
            'previous':json.loads(current) if current else None}
    pointer.parent.mkdir(parents=True,exist_ok=True)
    history = pointer.parent/('workspace-selection-'+uuid4().hex+'.json')
    write_new(history,encoded({'before':data['previous'],'after':data}))
    temp = pointer.parent/(pointer.name+'.'+uuid4().hex+'.tmp')
    write_new(temp,encoded(data))
    # Cooperative expected-byte check immediately before replacing a tiny local pointer.
    if (pointer.read_bytes() if pointer.exists() else None) != current: raise ValueError('Workspace selection changed during activation')
    os.replace(temp,pointer)
    return data


def rollback(pointer, expected):
    pointer = Path(pointer); current = pointer.read_bytes()
    if sha(current) != expected: raise ValueError('Workspace selection changed')
    data = json.loads(current); prior = data['previous']
    # Preserve the current selection in a recovery receipt; a null selection uses the original default store.
    write_new(pointer.parent/('workspace-rollback-'+uuid4().hex+'.json'),current)
    if prior is None:
        # Keep a valid explicit disabled selection rather than deleting history.
        prior = {'workspace':None,'workspace_sha256':None,'previous':data}
    temp=pointer.parent/(pointer.name+'.'+uuid4().hex+'.tmp');write_new(temp,encoded(prior))
    if pointer.read_bytes()!=current: raise ValueError('Workspace selection changed during rollback')
    os.replace(temp,pointer)
    return prior
