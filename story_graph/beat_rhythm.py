"""Independent, revisioned author direction for a single episode beat."""
from __future__ import annotations
from contextlib import nullcontext
import hashlib
import json
import re

from . import transaction_audit

OPTIONS={'intent':{'scene','beauty','comedy','transformation'},
         'pace':{'neutral','slow','measured','fast'},
         'pause':{'neutral','none','brief','held'},
         'comedy':{'none','setup','delay','payoff','reaction','escalation','release'},
         'cadence':{'neutral','flowing','varied','punchy','staccato'},
         'transition':{'neutral','smooth','abrupt','linger'}}

ACT_PRESETS = {
    'three_act': ('Setup', 'Confrontation', 'Resolution'),
    'six_act': ('Opening', 'Inciting turn', 'Complication', 'Midpoint', 'Crisis', 'Resolution'),
    'episodic_comedy': ('A-plot setup', 'B-plot setup', 'Escalation', 'A/B payoff'),
    'custom': (),
}

_STRUCTURE_DEFAULTS = {'marker': '', 'tension': None, 'duration_ms': None, 'pace': 'neutral',
                       'direction': '', 'sight': True, 'audio': True}


def _passage_key(beat):
    return f"{beat['start']}:{beat['end']}:" + hashlib.sha256(beat['text'].encode()).hexdigest()


def _structure(c, episode):
    if c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='act_structure_revisions'").fetchone():
        row = c.execute("SELECT revision,payload FROM act_structure_revisions WHERE episode=? ORDER BY revision DESC LIMIT 1",
                        (episode,)).fetchone()
        if row:
            return row['revision'], json.loads(row['payload'])
    return 0, {'preset': 'three_act', 'points': {}}


def _structure_point(point):
    if not isinstance(point, dict) or set(point) != set(_STRUCTURE_DEFAULTS):
        raise ValueError('Provide a complete beat timing and perception target')
    for key, limit in (('tension', 5), ('duration_ms', 3_600_000)):
        value = point[key]
        if value is not None and (type(value) is not int or not 0 <= value <= limit):
            raise ValueError(f'Invalid {key}')
    if point['pace'] not in OPTIONS['pace'] or any(type(point[k]) is not bool for k in ('sight', 'audio')):
        raise ValueError('Invalid pacing or perception settings')
    if any(not isinstance(point[k], str) or len(point[k]) > limit
           for k, limit in (('marker', 80), ('direction', 500))):
        raise ValueError('Shorten the turning-point label or direction')
    return point


def read_act_structure(timeline, c, episode, head, *, beat_id=None, viewpoint=None):
    from .beat_map import map_episode
    from .epistemic import viewpoint_diff

    mapping = map_episode(timeline, episode, head, _connection=c)
    revision, saved = _structure(c, episode)
    beats = mapping['beats']
    labels = ACT_PRESETS[saved['preset']]
    markers = {}
    for index, label in enumerate(labels):
        at = round(index * max(0, len(beats) - 1) / max(1, len(labels) - 1))
        markers.setdefault(at, []).append(label)
    points = []
    for index, beat in enumerate(beats):
        authored = saved['points'].get(_passage_key(beat), {})
        fields = {**_STRUCTURE_DEFAULTS, **authored}
        points.append({**fields, 'id': beat['id'], 'number': beat['number'], 'start': beat['start'], 'end': beat['end'],
                       'act': ' / '.join(markers.get(index, [])), 'configured': bool(authored)})
    chosen = next((beat for beat in beats if beat['id'] == beat_id), beats[0] if beats else None)
    diff = None
    if chosen and viewpoint:
        target = next(point for point in points if point['id'] == chosen['id'])
        events = timeline._resolve_rows(c, episode, chosen['scope_beat'],
                                        source_span=(chosen['start'], chosen['end']))
        diff = viewpoint_diff(events, viewpoint, sight=target['sight'], audio=target['audio'])
    return {'episode': episode, 'branch': mapping['branch'], 'timeline_revision': head, 'revision': revision,
            'preset': saved['preset'], 'presets': list(ACT_PRESETS), 'points': points,
            'selected': chosen['id'] if chosen else None, 'epistemic': diff}


def defaults():
    return {'intent':'scene','pace':'neutral','tension_start':None,'tension_end':None,
            'pause':'neutral','comedy':'none','cadence':'neutral','transition':'neutral',
            'author_override':'','source_id':'author','node_id':None}


def _validate(profile):
    if not isinstance(profile,dict) or set(profile)!=set(defaults()): raise ValueError('Beat direction fields are incomplete')
    for name,choices in OPTIONS.items():
        if not isinstance(profile[name],str) or profile[name] not in choices: raise ValueError('Invalid beat '+name)
    for name in ('tension_start','tension_end'):
        if profile[name] is not None and (type(profile[name]) is not int or not 0<=profile[name]<=5):
            raise ValueError('Tension must be empty or a whole number from 0 to 5')
    if not isinstance(profile['author_override'],str) or len(profile['author_override'])>500:
        raise ValueError('Beat direction must be text up to 500 characters')
    if not isinstance(profile['source_id'],str) or not re.fullmatch(r'[A-Za-z0-9_.:/-]{1,160}',profile['source_id']):
        raise ValueError('Beat source ID is invalid')
    if profile['node_id'] is not None and (not isinstance(profile['node_id'],str) or not re.fullmatch(r'[A-Za-z0-9_.:-]{1,160}',profile['node_id'])):
        raise ValueError('Beat graph node ID is invalid')


def _node(profile,graph,beat):
    if profile['node_id'] is None:return
    nodes=graph.get('nodes',[]) if isinstance(graph,dict) else []
    node=next((n for n in nodes if isinstance(n,dict) and n.get('id')==profile['node_id']),None)
    if not node or node.get('type')!='beat' or not isinstance(node.get('data'),dict) or type(node['data'].get('beat')) is not int or node['data']['beat']!=beat:
        raise ValueError('Linked beat graph node is missing or belongs to another beat')


def _edge_neighbors(graph,node_id):
    if not node_id or not isinstance(graph,dict):
        return {'incoming':[],'outgoing':[]}
    beat_nodes={}
    for n in graph.get('nodes') or []:
        if not isinstance(n,dict) or n.get('type')!='beat':continue
        data=n.get('data') or {}
        if type(data.get('beat')) is int and n.get('id') is not None:
            beat_nodes[str(n['id'])]=n
    if node_id not in beat_nodes:
        return {'incoming':[],'outgoing':[]}
    incoming=[];outgoing=[]
    for edge in graph.get('edges') or []:
        if not isinstance(edge,dict):continue
        src_id,dst_id=edge.get('from'),edge.get('to')
        if dst_id==node_id and src_id in beat_nodes:
            src=beat_nodes[src_id]
            incoming.append({'node_id':src['id'],'beat':src['data']['beat'],'title':str(src.get('title') or src['id']),'port':str(edge.get('fromPort') or '')})
        if src_id==node_id and dst_id in beat_nodes:
            dst=beat_nodes[dst_id]
            outgoing.append({'node_id':dst['id'],'beat':dst['data']['beat'],'title':str(dst.get('title') or dst['id']),'port':str(edge.get('fromPort') or '')})
    return {'incoming':incoming,'outgoing':outgoing}


def read(c,episode,beat,graph=None):
    if type(beat) is not int or not 0<=beat<=1_000_000: raise ValueError('Invalid beat')
    ep=c.execute('SELECT branch,status,head FROM episodes WHERE id=?',(episode,)).fetchone()
    if not ep or ep['status']=='archived': raise ValueError('Episode is unavailable or removed from the timeline')
    resolved_graph=graph
    if resolved_graph is None and ep['head']:
        head_row=c.execute('SELECT graph FROM revisions WHERE episode=? AND revision=?',(episode,ep['head'])).fetchone()
        if head_row and head_row['graph']:
            resolved_graph=json.loads(head_row['graph'])
    exists=c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='beat_rhythm_heads'").fetchone()
    row=None
    if exists:
        row=c.execute('''SELECT h.revision,r.payload FROM beat_rhythm_heads h
          LEFT JOIN beat_rhythm_revisions r ON r.episode=h.episode AND r.beat=h.beat AND r.revision=h.revision
          WHERE h.episode=? AND h.beat=?''',(episode,beat)).fetchone()
    if row is None: return {'episode':episode,'branch':ep['branch'],'beat':beat,'revision':0,
                            'status':'unset','profile':defaults(),'token':'none',
                            'edge_neighbors':{'incoming':[],'outgoing':[]}}
    if row['payload'] is None: raise ValueError('Beat rhythm revision is missing')
    profile=json.loads(row['payload']);_validate(profile)
    if graph is not None:_node(profile,graph,beat)
    encoded=json.dumps([episode,ep['branch'],beat,row['revision'],profile],sort_keys=True,ensure_ascii=False,separators=(',',':'))
    return {'episode':episode,'branch':ep['branch'],'beat':beat,'revision':row['revision'],
            'status':'configured','profile':profile,'token':hashlib.sha256(encoded.encode()).hexdigest(),
            'edge_neighbors':_edge_neighbors(resolved_graph,profile.get('node_id'))}


class BeatRhythmStore:
    def __init__(self,timeline): self.timeline=timeline

    @staticmethod
    def _history(c,episode,beat,expected):
        exists=c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='beat_rhythm_history'").fetchone()
        row=c.execute('SELECT * FROM beat_rhythm_history WHERE episode=? AND beat=?',(episode,beat)).fetchone() if exists else None
        if not row or row['basis_revision']!=expected:return list(range(max(0,expected-1000),expected)),[]
        return json.loads(row['undo_stack']),json.loads(row['redo_stack'])

    def open(self,episode,beat):
        with self.timeline._connect() as c: return read(c,episode,beat)

    def open_structure(self, episode, head, *, beat_id=None, viewpoint=None):
        with self.timeline._connect() as c:
            c.execute('BEGIN')
            return read_act_structure(self.timeline, c, episode, head, beat_id=beat_id, viewpoint=viewpoint)

    def save_structure(self, episode, head, revision, preset, *, beat_id=None, point=None, viewpoint=None):
        from .beat_map import map_episode

        if not isinstance(preset, str) or preset not in ACT_PRESETS or type(revision) is not int:
            raise ValueError('Choose an act structure and supply its current revision')
        with self.timeline._connect() as c:
            c.execute('BEGIN IMMEDIATE')
            ep = self.timeline._require_active(c, episode)
            if ep['status'] != 'draft' or ep['head'] != head:
                raise ValueError('Episode is finished or the timing target changed')
            current, saved = _structure(c, episode)
            if current != revision:
                raise ValueError('Act structure changed; reload its current revision')
            saved['preset'] = preset
            if point is not None:
                mapping = map_episode(self.timeline, episode, head, _connection=c)
                beat = next((item for item in mapping['beats'] if item['id'] == beat_id), None)
                if not beat:
                    raise ValueError('Choose a current saved beat')
                saved['points'][_passage_key(beat)] = _structure_point(point)
            c.execute('''CREATE TABLE IF NOT EXISTS act_structure_revisions(
                episode TEXT NOT NULL, revision INTEGER NOT NULL, payload TEXT NOT NULL,
                PRIMARY KEY(episode, revision))''')
            c.execute('INSERT INTO act_structure_revisions VALUES(?,?,?)',
                      (episode, revision + 1, json.dumps(saved, ensure_ascii=False)))
            transaction_audit.record_project_edit(
                c, domain='timing', target=episode, operation='save_timing_targets', token=revision + 1,
                before_patch={'revision': revision}, after_patch={'revision': revision + 1})
            return read_act_structure(self.timeline, c, episode, head, beat_id=beat_id, viewpoint=viewpoint)

    def _replay_structure_revision(self, c, episode, before, after):
        if self.timeline._require_active(c, episode)['status'] != 'draft':
            raise ValueError('Reopen the episode before changing its timing.')
        current, state = _structure(c, episode)
        def saved(revision):
            if revision == 0:
                return {'preset': 'three_act', 'points': {}}
            row = c.execute('SELECT payload FROM act_structure_revisions WHERE episode=? AND revision=?',
                            (episode, revision)).fetchone()
            if row is None:
                raise ValueError('A saved timing revision is missing.')
            return json.loads(row['payload'])
        if state != saved(before):
            raise ValueError('The timing targets changed outside project history.')
        c.execute('INSERT INTO act_structure_revisions VALUES(?,?,?)',
                  (episode, current + 1, json.dumps(saved(after), ensure_ascii=False)))

    def save(self,episode,beat,expected_timeline,expected_rhythm,profile,*,_history_action=None,_history_target=None,
             _connection=None):
        _validate(profile)
        if type(expected_timeline) is not int or type(expected_rhythm) is not int or expected_rhythm<0:
            raise ValueError('Expected episode and beat direction revisions are required')
        with (nullcontext(_connection) if _connection is not None else self.timeline._connect()) as c:
            if _connection is None:
                c.execute('BEGIN IMMEDIATE')
            ep=c.execute('SELECT status,head FROM episodes WHERE id=?',(episode,)).fetchone()
            if not ep or ep['status']!='draft' or ep['head']!=expected_timeline: raise ValueError('Episode is missing, finished or stale')
            current=read(c,episode,beat)
            if current['revision']!=expected_rhythm: raise ValueError('Stale beat direction revision')
            undo,redo=self._history(c,episode,beat,expected_rhythm)
            if _history_action in ('undo','redo'):
                stack=undo if _history_action=='undo' else redo
                if not stack or stack[-1]!=_history_target:raise ValueError('Beat history changed; reload and try again')
            row=c.execute('SELECT graph FROM revisions WHERE episode=? AND revision=?',(episode,ep['head'])).fetchone()
            _node(profile,json.loads(row['graph']),beat)
            c.execute('''CREATE TABLE IF NOT EXISTS beat_rhythm_heads(episode TEXT NOT NULL,beat INTEGER NOT NULL,
                revision INTEGER NOT NULL,PRIMARY KEY(episode,beat))''')
            c.execute('''CREATE TABLE IF NOT EXISTS beat_rhythm_revisions(episode TEXT NOT NULL,beat INTEGER NOT NULL,
                revision INTEGER NOT NULL,payload TEXT NOT NULL,PRIMARY KEY(episode,beat,revision))''')
            c.execute('''CREATE TABLE IF NOT EXISTS beat_rhythm_history(episode TEXT NOT NULL,beat INTEGER NOT NULL,
                basis_revision INTEGER NOT NULL,undo_stack TEXT NOT NULL,redo_stack TEXT NOT NULL,PRIMARY KEY(episode,beat))''')
            revision=expected_rhythm+1
            c.execute('INSERT INTO beat_rhythm_revisions VALUES(?,?,?,?)',(episode,beat,revision,json.dumps(profile,ensure_ascii=False)))
            c.execute('INSERT OR REPLACE INTO beat_rhythm_heads VALUES(?,?,?)',(episode,beat,revision))
            if _history_action=='undo':undo.pop();redo.append(expected_rhythm)
            elif _history_action=='redo':redo.pop();undo.append(expected_rhythm)
            else:undo.append(expected_rhythm);redo=[]
            c.execute('INSERT OR REPLACE INTO beat_rhythm_history VALUES(?,?,?,?,?)',
                      (episode,beat,revision,json.dumps(undo),json.dumps(redo)))
            if _history_action:
                transaction_audit.step_project_edit(
                    c, domain='beat_rhythm', target=episode, token=f'{beat}:{_history_target}',
                    next_token=f'{beat}:{expected_rhythm}', undo=_history_action == 'undo')
            else:
                transaction_audit.record_project_edit(
                    c, domain='beat_rhythm', target=episode, operation='save_beat_direction',
                    token=f'{beat}:{expected_rhythm}', before_patch={'beat': beat, 'revision': expected_rhythm},
                    after_patch={'beat': beat, 'revision': revision})
            return read(c,episode,beat)

    def _history_step(self,episode,beat,expected_timeline,expected_rhythm,action, *, connection=None):
        if type(expected_rhythm) is not int or expected_rhythm<1: raise ValueError('No earlier beat direction revision')
        with (nullcontext(connection) if connection is not None else self.timeline._connect()) as c:
            current=read(c,episode,beat)
            if current['revision']!=expected_rhythm: raise ValueError('Stale beat direction revision')
            undo,redo=self._history(c,episode,beat,expected_rhythm);stack=undo if action=='undo' else redo
            if not stack:raise ValueError('No beat direction change to '+action)
            target=stack[-1]
            row=c.execute('SELECT payload FROM beat_rhythm_revisions WHERE episode=? AND beat=? AND revision=?',
                          (episode,beat,target)).fetchone()
            if target>0 and row is None: raise ValueError('Prior beat direction revision is missing')
            profile=json.loads(row['payload']) if row else defaults()
        return self.save(episode,beat,expected_timeline,expected_rhythm,profile,
                         _history_action=action,_history_target=target,_connection=connection)

    def undo(self,episode,beat,expected_timeline,expected_rhythm):return self._history_step(episode,beat,expected_timeline,expected_rhythm,'undo')
    def redo(self,episode,beat,expected_timeline,expected_rhythm):return self._history_step(episode,beat,expected_timeline,expected_rhythm,'redo')
