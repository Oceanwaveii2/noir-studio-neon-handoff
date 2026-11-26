"""Immutable fork results for continuation. These records never promote canon."""
from __future__ import annotations

import json

from . import scene_fragments as f, source_timing
from .scene_override import _unpack
from .universe_scope import checked_id
from .world_laws import WorldLawStore


SLOT = '[Continue from the saved scene.]\n'
TABLE = 'scene_branch_results'


def _error(code,message):
    raise f.SceneFragmentError(code,message)


def _replay(c,scope,ident):
    checked_id(ident,'Saved replay')
    row=c.execute('SELECT * FROM scene_replay_receipts WHERE episode=? AND id=?',
                  (scope['episode'],ident)).fetchone() if f._has(c,'scene_replay_receipts') else None
    if not row:
        _error('missing_result','Choose a saved replay in this branch')
    value=_unpack(row)
    if (value['scope']!=scope or value['writes_canon'] is not False
            or f.digest(f.encoded(value['frames']))!=value['world_sha256']):
        _error('wrong_result','The replay receipt does not match this saved branch')
    profile=c.execute('SELECT sha256,payload FROM scene_replay_profiles WHERE episode=? AND id=?',
                      (scope['episode'],value['profile'])).fetchone()
    if not profile or profile['sha256']!=value['profile_sha256']:
        _error('stale_result','The branch rules no longer match the saved replay')
    _unpack(profile)
    return value,row['sha256']


def _book(c,scope,head,script,exact):
    row=(c.execute('''SELECT r.payload FROM notebook_heads h JOIN notebook_revisions r
                      ON r.episode=h.episode AND r.revision=h.head WHERE h.episode=? AND r.timeline_revision=?''',
                   (scope['episode'],head)).fetchone() if f._has(c,'notebook_heads') else None)
    book=json.loads(row['payload']) if row else None
    masks={m['id']:m for m in book['masks']} if book else {}
    m=masks.get(exact['id'])
    if (not book or ''.join(b['text'] for b in book['blocks'])!=script or not m or not m.get('hard') or m['value']!=100
            or m['sha256']!=exact['sha256'] or f.digest(script[m['start']:m['end']])!=m['sha256']):
        _error('stale_branch_lock','The inherited exact dialogue no longer matches this branch')
    return book


def _lineage(c,scope,parent,beat):
    row=c.execute('SELECT parent,fork_episode,fork_beat FROM branches WHERE id=?',(scope['branch'],)).fetchone()
    if (scope['branch']==parent['branch'] or scope['episode']==parent['episode'] or row is None
            or tuple(row)!=(parent['branch'],parent['episode'],beat)):
        _error('wrong_branch','The saved result must belong to the actual timeline fork')


def install(store,request,*,parent,parent_replay,fork_event,child_replay):
    """Register a bounded authored fork after its scene successfully replays on a copy."""
    with store._connect() as c:
        c.execute('BEGIN IMMEDIATE')
        scope,head=f.SceneFragmentStore._scope(c,request)
        source,source_head=f.SceneFragmentStore._scope(c,parent)
        old,oldsha=_replay(c,source,parent_replay)
        branch,branchsha=_replay(c,scope,child_replay)
        _lineage(c,scope,source,old['timeline_cutoff'])
        if (old['timeline_revision']!=source_head or branch['timeline_revision']!=head
                or old['timeline_cutoff']!=branch['timeline_cutoff'] or branch['law_revision']!=old['law_revision']
                or old['history_sha256']!=branch['history_sha256']):
            _error('stale_result','The fork must preserve the common saved timeline cutoff')
        focus=next((x for x in old['frames'] if x['event']==fork_event),None)
        last=branch['frames'][-1]
        shared=next((x for x in branch['frames'] if x['event']==fork_event),None)
        if (not focus or not shared or focus['operation']!='line' or last is shared
                or (focus['state'],focus['effects'])!=(shared['state'],shared['effects'])):
            _error('wrong_fork','Both replays must reach the identical protected-line state before diverging')
        prefix_old=old['frames'][:old['frames'].index(focus)+1]
        prefix_new=branch['frames'][:branch['frames'].index(shared)+1]
        if ([{k:v for k,v in frame.items() if k!='node'} for frame in prefix_old]
                != [{k:v for k,v in frame.items() if k!='node'} for frame in prefix_new]):
            _error('wrong_fork','The common prefix must preserve all prior transitions')
        graph=f.SceneFragmentStore(store)
        left,original,_=graph.pinned_replay(c,source,source_head,old)
        right,script,graphsha=graph.pinned_replay(c,scope,head,branch)
        if graphsha!=branch['graph_sha256']:
            _error('stale_result','The current branch graph no longer matches its replay')
        def passage(g,node):
            ident=next(n['passage'] for n in g['graph']['nodes'] if n['id']==node)
            return next(p for p in g['graph']['passages'] if p['id']==ident)
        start=len(script)-len(SLOT)
        prefix=original[left['anchor']['start']:passage(left,focus['node'])['end']]
        if (not script.startswith(prefix) or not script.endswith(SLOT) or not last['node'] or start>3600
                or right['anchor']['start']!=0 or right['anchor']['end']>start
                or script[passage(right,last['node'])['end']:start].strip()):
            _error('wrong_slot','The slot must follow the last replayed passage and preserve the exact common prefix')
        exact=focus['effects'][0]['protected_line']
        _book(c,scope,head,script,exact)
        data={'schema_version':1,'scope':scope,'timeline_revision':head,'slot':{'start':start,'end':len(script),'sha256':f.digest(SLOT)},
              'source_sha256':f.digest(script),'exact_dialogue':exact,'shared_prefix_sha256':f.digest(prefix),
              'parent':{'scope':source,'replay':old['id'],'receipt_sha256':oldsha,'fork':fork_event,
                        'frame_sha256':f.digest(f.encoded(focus)),'timeline_cutoff':old['timeline_cutoff']},
              'replay':branch['id'],'replay_sha256':branchsha,'terminal_event':last['event'],
              'frame_sha256':f.digest(f.encoded(last)),'world_sha256':branch['world_sha256'],'law_revision':branch['law_revision']}
        data['id']=f._id('scene-branch-result',data)
        raw=f.encoded(data)
        c.execute('''CREATE TABLE IF NOT EXISTS scene_branch_results (
            episode TEXT PRIMARY KEY REFERENCES episodes(id), id TEXT NOT NULL UNIQUE, payload TEXT NOT NULL, sha256 TEXT NOT NULL)''')
        row=c.execute('SELECT * FROM scene_branch_results WHERE episode=?',(scope['episode'],)).fetchone()
        if row:
            if _unpack(row)!=data:
                _error('branch_exists','This episode already owns a different saved branch result')
        else:
            c.execute('INSERT INTO scene_branch_results VALUES(?,?,?,?)',(scope['episode'],data['id'],raw,f.digest(raw)))
        return data


def list_visible(c,scope):
    if not f._has(c,TABLE):
        return []
    rows=(_unpack(row) for row in c.execute('SELECT * FROM scene_branch_results ORDER BY rowid'))
    return [row for row in rows if scope in (row['scope'],row['parent']['scope'])]


def resolve(store,c,scope,head,result):
    checked_id(result,'Saved branch result')
    row=c.execute('SELECT * FROM scene_branch_results WHERE episode=? AND id=?',(scope['episode'],result)).fetchone() if f._has(c,TABLE) else None
    if not row or (record:=_unpack(row))['scope']!=scope:
        _error('wrong_result','Use a saved result from the current episode and branch')
    if record['timeline_revision']!=head:
        _error('stale_result','The episode changed since this branch result was saved')
    parent=record['parent']
    _lineage(c,scope,parent['scope'],parent['timeline_cutoff'])
    first,firstsha=_replay(c,parent['scope'],parent['replay'])
    child,childsha=_replay(c,scope,record['replay'])
    if (firstsha!=parent['receipt_sha256'] or childsha!=record['replay_sha256']
            or not any(frame['event']==parent['fork'] and f.digest(f.encoded(frame))==parent['frame_sha256'] for frame in first['frames'])):
        _error('stale_result','The parent or branch replay no longer matches its saved result')
    frame=child['frames'][-1]
    if f.digest(f.encoded(frame))!=record['frame_sha256'] or child['world_sha256']!=record['world_sha256']:
        _error('stale_result','The terminal frame changed')
    law=WorldLawStore.in_connection(c,project_id=scope['project'],universe_id=scope['universe'])
    if law['revision']!=record['law_revision']:
        _error('stale_result','World laws changed; replay the scene before continuing')
    approved=[item for item in store._resolve_rows(c,scope['episode'],child['timeline_cutoff']) if source_timing.visible_to(item,None)]
    if f.digest(f.encoded(approved))!=child['history_sha256']:
        _error('stale_result','Story history changed; replay the scene before continuing')
    _,script,graph=f.SceneFragmentStore(store).pinned_replay(c,scope,head,child)
    if graph!=child['graph_sha256'] or f.digest(script)!=record['source_sha256']:
        _error('stale_result','Scene source or graph changed after replay')
    _book(c,scope,head,script,record['exact_dialogue'])
    return record,row['sha256'],frame,script[:record['slot']['start']]


def seed(roles):
    """A fresh story receives abstract roles and a shape, with no source state."""
    f._object(roles,('lead','listener','helper'))
    if any(not isinstance(x,str) for x in roles.values()) or len(set(roles.values()))!=3:
        raise ValueError('Choose three distinct destination roles')
    cast={role:checked_id(ident,'Destination actor') for role,ident in roles.items()}
    return {'schema_version':1,'mode':'new-story','roles':cast,'beats':[
        {'kind':'setup','role':'lead'}, {'kind':'reaction','role':'listener'},
        {'kind':'pause'}, {'kind':'callback','role':'helper'}], 'inherited_facts':[], 'provider_calls':0}
