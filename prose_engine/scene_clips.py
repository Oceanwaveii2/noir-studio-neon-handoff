"""Local clip intake and scoped writing notes. Media never enters a writer request."""
from __future__ import annotations

from decimal import Decimal, InvalidOperation
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
from tempfile import NamedTemporaryFile

from story_graph import scene_fragments as f
from story_graph.scene_override import _unpack
from story_graph.universe_scope import checked_id


COMMANDS = frozenset('scene.clips.' + op for op in ('open','attach','detach','preview','run'))
PURPOSES = ('cutaway','personality','performance','timing')
ACTOR_PURPOSES = ('personality','performance')
MAX_FILE = 128 * 1024 * 1024
MAX_ASSETS = 30
MAX_PER_BEAT = 6
LIMITS = {'input_bytes':16_000,'output_chars':1_400}
_TYPES = {'.mp4': ('video/mp4', 'mov', 'h264'), '.webm': ('video/webm', 'webm', ('vp8','vp9','av1'))}


def _error(code, message):
    raise f.SceneFragmentError(code, message)


def _probe(path, suffix):
    tool = shutil.which('ffprobe')
    if not tool:
        _error('media_probe_missing','FFprobe is required to read clip timings')
    _, demuxer, codecs = _TYPES[suffix]
    try:
        result = subprocess.run([tool,'-v','error','-protocol_whitelist','file','-f',demuxer,
            '-select_streams','v:0','-show_entries','stream=codec_name,duration,start_time:format=duration,start_time',
            '-of','json',str(path)],capture_output=True,timeout=15,check=True)
        data=json.loads(result.stdout)
        stream=data['streams'][0]
        codec=stream['codec_name']
        if codec not in ((codecs,) if isinstance(codecs,str) else codecs):
            raise ValueError('Unsupported video codec')
        span=Decimal(stream['duration'] if stream.get('duration') not in (None,'N/A') else data['format']['duration'])
        start=Decimal(data['format'].get('start_time','0'))
        video_start=Decimal(stream.get('start_time','0'))
        if (not span.is_finite() or not start.is_finite() or not video_start.is_finite()
                or not Decimal('0.05') <= span <= 1800 or abs(start)>Decimal('.05') or abs(video_start)>Decimal('.05')):
            raise ValueError('Unsupported clip timebase')
        duration=int(span*1000)
    except (ValueError, KeyError, IndexError, TypeError, InvalidOperation, subprocess.SubprocessError):
        _error('unsupported_media','Use a playable H.264 MP4 or VP8/VP9/AV1 WebM with a timebase starting at zero')
    return {'duration_ms':duration,'clock':'clip-relative playback','video_codec':codec}


def _schema(c):
    c.execute('''CREATE TABLE IF NOT EXISTS scene_clip_assets (
        episode TEXT NOT NULL REFERENCES episodes(id), id TEXT NOT NULL, payload TEXT NOT NULL,
        sha256 TEXT NOT NULL, PRIMARY KEY(episode,id))''')
    c.execute('''CREATE TABLE IF NOT EXISTS scene_clip_pins (
        episode TEXT NOT NULL REFERENCES episodes(id), id TEXT NOT NULL, payload TEXT NOT NULL,
        sha256 TEXT NOT NULL, active INTEGER NOT NULL, PRIMARY KEY(episode,id))''')


def _rows(c,table,scope,active=False):
    if not f._has(c,table):
        return []
    where=' AND active=1' if active else ''
    valid=[]
    for row in c.execute(f'SELECT * FROM {table} WHERE episode=?'+where+' ORDER BY rowid',(scope['episode'],)):
        value=_unpack(row)
        if value['scope']==scope:
            valid.append(value)
    return valid


def _get(c,table,scope,ident,active=False):
    checked_id(ident,'Clip ID or assignment ID')
    if f._has(c,table):
        where=' AND active=1' if active else ''
        row=c.execute(f'SELECT * FROM {table} WHERE episode=? AND id=?'+where,(scope['episode'],ident)).fetchone()
        if row and (value:=_unpack(row))['scope']==scope:
            return value
    _error('unknown_clip','That clip or assignment is not available in this episode and branch')


def _directory(store):
    path=Path(store.path).resolve().with_suffix('.clips')
    if path.is_symlink():
        _error('media_changed','The local clip store is unavailable')
    return path


def _asset_path(store,asset):
    if asset['suffix'] not in _TYPES:
        _error('media_changed','The clip format has changed')
    path=_directory(store)/(f._sha(asset['content_sha256'])+asset['suffix'])
    if path.is_symlink() or not path.is_file() or path.stat().st_size!=asset['bytes']:
        _error('media_changed','The pinned clip bytes are missing or changed')
    if path.stat().st_mtime_ns != asset.get('stored_mtime_ns'):
        with path.open('rb') as file:
            if hashlib.file_digest(file,'sha256').hexdigest()!=asset['content_sha256']:
                _error('media_changed','The pinned clip bytes are missing or changed')
    return path


def intake(store,request,stream,length):
    """Stream and probe a named upload. Only hash-derived filenames reach the disk."""
    name=request.get('name')
    if (not isinstance(name,str) or not name.strip() or len(name)>160 or '/' in name or '\\' in name
            or any(ord(ch)<32 for ch in name)):
        _error('invalid_media_name','Choose a clip filename')
    suffix=Path(name).suffix.lower()
    if suffix not in _TYPES or type(length) is not int or not 1 <= length <= MAX_FILE:
        _error('unsupported_media','Choose an MP4 or WebM clip up to 128 MiB')
    with store._connect() as c:
        scope,_=f.SceneFragmentStore._scope(c,request)
    root=_directory(store)
    root.mkdir(exist_ok=True)
    temp=None
    try:
        sha=hashlib.sha256()
        with NamedTemporaryFile(mode='wb',dir=root,suffix=suffix,delete=False) as file:
            temp=Path(file.name)
            left=length
            while left:
                data=stream.read(min(left,1024*1024))
                if not data:
                    _error('short_upload','The clip upload ended early')
                file.write(data)
                sha.update(data)
                left-=len(data)
        ident=f._id('clip',scope,sha.hexdigest())
        with store._connect() as c:
            c.execute('BEGIN IMMEDIATE')
            actual,_=f.SceneFragmentStore._scope(c,request)
            if actual!=scope:
                _error('wrong_scope','Clip destination changed during upload')
            assets=_rows(c,'scene_clip_assets',scope)
            prior=next((a for a in assets if a['id']==ident),None)
            if prior:
                _asset_path(store,prior)
                return prior
            if len(assets)>=MAX_ASSETS:
                _error('media_limit','This episode has reached its 30 clip limit')
            parsed=_probe(temp,suffix)
            asset={'id':ident,'scope':scope,'name':name,'content_sha256':sha.hexdigest(),'bytes':length,
                   'suffix':suffix,'mime':_TYPES[suffix][0],**parsed}
            output=root/(asset['content_sha256']+suffix)
            if output.is_symlink():
                _error('media_changed','The local clip store is unavailable')
            if not output.exists():
                os.replace(temp,output)
            else:
                _asset_path(store,asset)
            asset['stored_mtime_ns']=output.stat().st_mtime_ns
            _asset_path(store,asset)
            _schema(c)
            raw=f.encoded(asset)
            c.execute('INSERT INTO scene_clip_assets VALUES(?,?,?,?)',(scope['episode'],ident,raw,f.digest(raw)))
            return asset
    finally:
        if temp is not None:
            temp.unlink(missing_ok=True)


def media(store,request):
    with store._connect() as c:
        scope,_=f.SceneFragmentStore._scope(c,request)
        asset=_get(c,'scene_clip_assets',scope,request.get('id'))
    return asset,_asset_path(store,asset)


def parse_byte_range(value,total):
    if value is None:
        return 0,total-1
    match=re.fullmatch(r'bytes=(\d{0,15})-(\d{0,15})',value)
    if not match or not any(match.groups()):
        raise ValueError('Unsupported byte range')
    a,b=match.groups()
    if not a:
        start,end=max(0,total-int(b)),total-1
    else:
        start,end=int(a),min(total-1,int(b) if b else total-1)
    if not 0<=start<=end<total:
        raise ValueError('Range lies outside the clip')
    return start,end


def _destination(store,c,scope,head,req):
    graph,script,graph_sha=f.SceneFragmentStore(store).pinned_replay(c,scope,head,req)
    ident=checked_id(req.get('node'),'Destination beat ID')
    node=next((n for n in graph['graph']['nodes'] if n['id']==ident and n['passage']
               and n['kind'] not in ('heading','reference')),None)
    if node is None:
        _error('wrong_beat','Choose a saved passage beat in the scene graph')
    passage=next(p for p in graph['graph']['passages'] if p['id']==node['passage'])
    return {'fragment':graph['id'],'fragment_revision':graph['revision'],'node':ident,'timeline_revision':head,
            'graph_sha256':graph_sha,'start':passage['start'],'end':passage['end'],'passage_sha256':passage['sha256']}


def _cutaway_frame(c,scope,destination,replay,event):
    if replay is None and event is None:
        return None
    checked_id(replay,'Replay receipt ID'); checked_id(event,'Replay beat')
    row=(c.execute('SELECT * FROM scene_replay_receipts WHERE episode=? AND id=?',(scope['episode'],replay)).fetchone()
         if f._has(c,'scene_replay_receipts') else None)
    trace=_unpack(row) if row else None
    if (not trace or trace['scope']!=scope or any(trace[k]!=destination[k] for k in
            ('fragment','fragment_revision','timeline_revision','graph_sha256'))
            or not any(frame['event']==event and frame['node']==destination['node'] for frame in trace['frames'])):
        _error('wrong_beat','That beat is not in the selected saved replay')
    return {'receipt':replay,'event':event}


def _attach(store,c,scope,head,req):
    dest=_destination(store,c,scope,head,req)
    asset=_get(c,'scene_clip_assets',scope,req.get('clip'))
    _asset_path(store,asset)
    start,end=f._range(req.get('start_ms'),req.get('end_ms'),asset['duration_ms'])
    mode=req.get('purpose')
    if mode not in PURPOSES:
        _error('invalid_purpose','Choose Cutaway, Personality, Performance, or Timing')
    from .scene_mind_support import allowed_use
    if not allowed_use(c,scope,asset['id'],mode):
        _error('wrong_purpose','This collection is for timing and reactions only; audition clips stay out of writing')
    if end-start>90_000:
        _error('clip_range_limit','Choose at most 90 seconds for one beat reference')
    actor=note=frame=None
    if mode=='cutaway':
        frame=_cutaway_frame(c,scope,dest,req.get('replay'),req.get('event'))
    else:
        note=f._label(req.get('note'),380).strip()
        if mode in ACTOR_PURPOSES:
            actor=f._label(req.get('character'),55).strip()
        if req.get('replay') is not None or req.get('event') is not None:
            _error('wrong_purpose','Only an audience cutaway is placed on a replay frame')
    data={'scope':scope,'destination':dest,'clip':asset['id'],'content_sha256':asset['content_sha256'],
          'start_ms':start,'end_ms':end,'purpose':mode,'character':actor,'note':note,'frame':frame}
    ident=f._id('clip-pin',data)
    current=[v for v in _rows(c,'scene_clip_pins',scope,True) if v['destination']==dest]
    if match:=next((v for v in current if v['id']==ident),None):
        return match
    if len(current)>=MAX_PER_BEAT:
        _error('beat_clip_limit','This beat already has six clip assignments')
    if mode=='cutaway' and any(v['purpose']=='cutaway' for v in current):
        _error('cutaway_exists','Remove the current cutaway before setting another for this beat')
    value=data|{'id':ident}
    _schema(c)
    raw=f.encoded(value)
    c.execute('''INSERT INTO scene_clip_pins VALUES(?,?,?,?,1)
                 ON CONFLICT(episode,id) DO UPDATE SET active=1''',(scope['episode'],ident,raw,f.digest(raw)))
    return value


def replay_cues(store,trace):
    """Read a separate audience track. Never change an existing world receipt."""
    with store._connect() as c:
        scope,head=f.SceneFragmentStore._scope(c,trace['scope'])
        if trace['timeline_revision']!=head:
            return []
        return [{'clip':p['clip'],'start_ms':p['start_ms'],'end_ms':p['end_ms'],'event':p['frame']['event']}
                for p in _rows(c,'scene_clip_pins',scope,True) if p['purpose']=='cutaway' and p['frame']
                and p['frame']['receipt']==trace['id']]


def _binding(store,c,scope,head,request):
    dest=_destination(store,c,scope,head,request)
    pins=[v for v in _rows(c,'scene_clip_pins',scope,True) if v['destination']==dest]
    if not pins:
        _error('clip_pins_missing','Assign at least one clip to this beat first')
    # These are exact source-relative ranges; only the human observation is rendered.
    detailed=[]
    for pin in sorted(pins,key=lambda v:v['id']):
        asset=_get(c,'scene_clip_assets',scope,pin['clip'])
        _asset_path(store,asset)
        if asset['content_sha256']!=pin['content_sha256']:
            _error('media_changed','The clip edition has changed')
        detailed.append(pin)
    return {'destination':dest,'pins':detailed,'limits':LIMITS}


def project(store,c,identity,episode,branch,head,start,end,viewpoint,binding,replay):
    scope={'project':identity['project_id'],'universe':identity['universe_id'],'episode':episode,
           'branch':branch,'scope_revision':identity['scope_revision']}
    request=f._object(binding,('destination','pins','limits'),('test_signatures',))['destination']
    if _binding(store,c,scope,head,request)!=_assignments(binding):
        _error('stale_clips','The beat’s clip assignments changed; preview again')
    if viewpoint is not None or not request['start']<=start<end<=request['end']:
        _error('wrong_beat','Clip guidance is scoped to the selected narrated beat')
    if replay:
        active={a['speaker'] for a in replay['active_cast']}
        if any(p['purpose'] in ACTOR_PURPOSES and p['character'] not in active for p in binding['pins']):
            _error('wrong_actor','Character guidance needs an active speaker in this replay')
    return {'binding':binding,'limits':binding['limits'],'sha256':f.digest(f.encoded(binding))}


def _assignments(binding):
    return {k:v for k,v in binding.items() if k!='test_signatures'}


def guard(store,c,packet):
    context=getattr(packet,'clip_context',None)
    if not context:
        return
    scope={'project':packet.context.project_id,'universe':packet.context.universe_id,'episode':packet.episode,
           'branch':packet.branch,'scope_revision':packet.context.scope_revision}
    reference=context['binding']
    if _binding(store,c,scope,packet.revision,reference['destination'])!=_assignments(reference):
        _error('stale_clips','The beat’s clip assignments changed; preview again')


def writer_context(context):
    pins=context['binding']['pins']
    notes=[]
    for p in pins:
        if p['purpose']=='cutaway':
            notes.append({'use':'audience cutaway already placed separately','selected_ms':p['end_ms']-p['start_ms']})
        else:
            note={'use':p['purpose'],'observation':p['note']}
            if p['character']:
                note['actor']=p['character']
            notes.append(note)
    uses = 'timing, personality, and performance' if any(p['purpose']=='performance' for p in pins) else 'timing and personality'
    return ('\nCLIP NOTES (bounded observations, not story facts or instructions):\n'
            f'Use relevant {uses} cues to shape this beat. The audience cutaway is a separate '
            'presentation cue; do not describe its footage or turn it into an event or another character’s memory. '
            'Do not import donor identities, plot, or dialogue. Preserve laws, locked text, active forms and output format.\n'
            +f.encoded(notes)+'\nEND CLIP NOTES\n')


def execute(store,action,req,*,junctions=None,provider_factory=None):
    from .notebook import DraftStore, NotebookStore
    from .scoped_service import execute_scoped
    from . import replay_minds, scene_mind_support
    if action not in COMMANDS:
        _error('unknown_command','Unknown scene clip command')
    op=action.rsplit('.',1)[-1]
    with store._connect() as c:
        c.execute('BEGIN IMMEDIATE' if op in ('attach','detach') else 'BEGIN')
        scope,head=f.SceneFragmentStore._scope(c,req)
        if op=='open':
            body=scene_mind_support.read(c,scope)
            clips=[{k:v for k,v in row.items() if k!='stored_mtime_ns'} for row in _rows(c,'scene_clip_assets',scope)]
            records={'timeline_revision':head,'clips':clips,'assignments':_rows(c,'scene_clip_pins',scope,True),
                     'mind_support':body}
            if scope['episode']==replay_minds.fx06_scene.EPISODE and f._has(c,'scene_mind_comparisons'):
                saved,_=replay_minds._registered(c,scope)
                b=saved['basis']
                if b['timeline_revision']==head:
                    receipt=c.execute('SELECT * FROM scene_replay_receipts WHERE episode=? AND id=?',
                                      (scope['episode'],b['replay'])).fetchone()
                    if receipt:
                        records['draft_fragment']=b['fragment']
                        records['draft_node']=next(x['node'] for x in _unpack(receipt)['frames'] if x['event']==b['frame'])
        elif op=='attach':
            return {'assignment':_attach(store,c,scope,head,req),'provider_calls':0}
        elif op=='detach':
            before=_get(c,'scene_clip_pins',scope,req.get('assignment'))
            c.execute('UPDATE scene_clip_pins SET active=0 WHERE episode=? AND id=?',(scope['episode'],before['id']))
            return {'detached':before['id'],'provider_calls':0}
        else:
            binding=_binding(store,c,scope,head,req)
            exercise=req.get('test_signatures',False)
            if type(exercise)is not bool:
                _error('wrong_rule_test','Choose whether to test the saved character rules')
            if exercise and not scene_mind_support.read(c,scope):
                _error('wrong_rule_test','No character rules are saved in this scene')
            if exercise:
                binding['test_signatures']=True
            dest=binding['destination']
            # An audience cue can be attached independently and carries no prose instructions.
            if all(p['purpose']=='cutaway' for p in binding['pins']):
                _error('clip_guidance_missing','Add a personality or timing note, or a performance observation, to draft with clips')
            choice=None
            if scope['episode']==replay_minds.fx06_scene.EPISODE:
                saved,_=replay_minds._registered(c,scope)
                b=saved['basis']
                if (dest['fragment']!=b['fragment'] or dest['fragment_revision']!=b['fragment_revision']
                        or not dest['start']<=b['start']<b['end']<=dest['end']):
                    _error('wrong_beat','Use the saved active roast beat for the Rainee clip draft')
                incoming=replay_minds._request(saved,'all')
                choice=incoming['replay_binding']
            else:
                incoming=scope|{'revision':head,'beat':0,'start':dest['start'],'end':dest['end'],
                                 'provider':'codex-session','references':'none'}
    if op=='open':
        drafts=DraftStore(NotebookStore(store)).list(scope['episode'],scope['branch'])
        records['drafts']=[{'id':d['id'],'status':d['status'],'source_revision':d['source_revision']}
                           for d in reversed(drafts) if (d.get('writing_context') or {}).get('clip_context')][:30]
        return records|{'provider_calls':0}
    context={'junctions':junctions,'provider_factory':provider_factory,'replay_binding':choice,'clip_binding':binding}
    preview=execute_scoped(store,'rhythm-preview',incoming,**context)
    if preview['prompt_bytes']>LIMITS['input_bytes']:
        _error('clip_budget','This beat and its clip notes exceed the writing budget')
    plan=f._id('clip-draft',incoming,preview['scope'],preview['rhythm_guidance']['id'])
    if op=='preview':
        return preview|{'plan':plan}
    if req.get('plan')!=plan:
        _error('stale_clips','Preview these exact clip assignments before generating')
    incoming|={'request_id':plan,'clip_binding':binding,'rhythm_plan_id':preview['rhythm_guidance']['id']}
    result=execute_scoped(store,'generate',incoming,expected_clip_scope=preview['scope'],**context)
    return result|{'plan':plan,'provider_calls':result.get('provider_calls',0 if result.get('replayed') else 1)}
