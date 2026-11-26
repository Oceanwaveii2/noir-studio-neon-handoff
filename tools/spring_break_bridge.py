"""Run the source-backed Spring Break bridge on an isolated workspace."""
from __future__ import annotations

import argparse
from contextlib import closing
from copy import deepcopy
from hashlib import file_digest
import json
from pathlib import Path
import re
import shutil
import sqlite3
import subprocess
from time import perf_counter

from prose_engine import scene_bridges as bridge
from prose_engine.episode_commands import EpisodeCommands
from prose_engine.notebook import DraftStore, NotebookStore, joined
from prose_engine.providers.session_attempts import SessionAttemptError
from story_graph import fx06_scene as fx, scene_branches, scene_bridge, scene_fragments as f
from story_graph.beat_map import map_episode
from story_graph.episode_timeline import TimelineStore
from story_graph.scene_override import SceneReplayStore
from story_graph.world_laws import WorldLawStore
from telemetry.scene_bridge_trace import Trace, read_trace, stamp
from tools.apply_fx06_francine_note import COMMON, RELAPSE_ENDING, corrected_plan
from tools.verify_fx06_mind_drafts import DBS, EFFORT, MODEL, backup, load, put, studio


ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT/'.app-steward/local/noir-fx06-spring-break-bridge-20261117'
RUN = 'spring-break-three-return-20261117'
PARENT = 'spring-break'
BRANCH = 'spring-break-three-return'
EPISODE = BRANCH+'-scene'
PILOT_BRANCH = 'fx06-francine-relapse'
LOCK = 'spring-break-haley-frozen'
MASK = 'spring-break-bridge-slot'
ROGER = "### SCENE 7: ROGER'S RUTGERS SPRING BREAK TAKEOVER"
JOIN_PARTY = ('haley', 'stella')
TRAVEL = ('francine', *fx.CAST)
SEATS = ('driver', 'front-passenger', 'rear-left', 'rear-right')


def sha(path):
    with Path(path).open('rb') as file:
        return file_digest(file, 'sha256').hexdigest()


def exact_span(text, prefix):
    hits = list(re.finditer(r'^'+re.escape(prefix)+r'[^\r\n]*', text, re.M))
    if len(hits) != 1:
        raise ValueError('A required source line is absent or ambiguous')
    return hits[0].span()


def evidence(ident, text, span):
    a, b = span
    return {'id': ident, 'start': a, 'end': b, 'sha256': f.digest(text[a:b])}


def source_anchors(store):
    ep = store.get_episode(PARENT)
    text = ep['script']
    if ep['branch'] != 'main' or ep['head'] != 3 or f.digest(text) != (
            'ef72ddba4f98496b06bc5e53236413082c4679d0a976e284e4ba03529f524895'):
        raise ValueError('Use the verified processed MO2 revision')
    anchors = {'release': exact_span(text, '*PFFFFFT-BOOOOOM!*'),
               'scent': exact_span(text, 'Dense clouds of sweet gardenia'),
               'notice': exact_span(text, 'Out in the upstairs hallway, Haley'),
               'line': exact_span(text, '"Mom!" Haley called through the closed door.'),
               'car': exact_span(text, 'Outside the red-brick two-story Ling house'),
               'departure': exact_span(text, "The engine roared. Francine and Rainee's red car"),
               'roger': exact_span(text, ROGER),
               'entry': exact_span(text, 'Before the exhaust had even cleared, Roger stood'),
               'meals': exact_span(text, '"Three nights of lasagna," Francine announced')}
    if (fx.PERFUME_LINE not in text[slice(*anchors['line'])] or
            not all(x in text[slice(*anchors['entry'])] for x in ('Haley and Stella', 'driveway')) or
            'four-door sedan' not in text[slice(*anchors['car'])]):
        raise ValueError('The saved source does not support the fork or handoff')
    supplies = [m for m in re.finditer(r'[^\r\n]+', text[anchors['roger'][0]:])
                if 'left us three trays of lasagna and the house keys' in m[0]]
    if len(supplies) != 1:
        raise ValueError('The retained scene must state who has the food and house keys')
    a = anchors['roger'][0]
    anchors['supplies'] = a+supplies[0].start(), a+supplies[0].end()
    mapping = map_episode(store, PARENT, ep['head'])
    cue_passage = [b for b in mapping['beats']
                   if b['start'] <= anchors['line'][0] and b['end'] >= anchors['line'][1]]
    if len(cue_passage) != 1:
        raise ValueError('The source cue does not map to one notebook passage')
    beat = cue_passage[0]
    frozen = evidence(LOCK, text, anchors['line'])
    parent = {'episode': ep['id'], 'branch': ep['branch'], 'revision': ep['head'],
              'text_sha256': mapping['source_sha256'], 'graph_sha256': mapping['graph_sha256'],
              'fork': frozen['end'], 'join': anchors['roger'][0], 'frozen': frozen,
              'source_evidence': [evidence(k, text, v) for k, v in anchors.items()]}
    return ep, anchors, beat, parent


def prior_evidence(pilot):
    branches = load(pilot.parent/'branches.json')
    item = next(it for it in branches if it['scope']['branch']==PILOT_BRANCH)
    with closing(sqlite3.connect((pilot/'timeline.sqlite').as_uri()+'?mode=ro', uri=True)) as db:
        db.row_factory = sqlite3.Row
        saved, replay_digest = scene_branches._replay(db, item['scope'], item['replay']['id'])
        fragment = f.SceneFragmentStore._record(f.SceneFragmentStore._find(
            db, item['scope']['episode'], saved['fragment'], saved['fragment_revision']))
        clip = next(e for e in fragment['declaration']['evidence'] if e['id'] == 'complete-fusion')
        setup = fx.read(db)
    if saved != item['replay'] or not setup:
        raise ValueError('Run inputs lack the verified historical replay or Mind cards')
    clip_asset = pilot/'timeline.clips'/(clip['sha256']+'.mp4')
    if sha(clip_asset) != clip['sha256']:
        raise ValueError('The selected complete cutaway edition changed')
    manifestations = {actor['id']: actor['mind'] for actor in saved['frames'][-1]['state']['manifestations']}
    cards = []
    for actor in setup['actors']:
        ident = actor['form_id']
        mind = setup['mind_nodes'][ident]
        if manifestations.get(ident) != mind:
            raise ValueError('The historical replay and known Mind bindings disagree')
        cards.append({'form': ident, 'mind': mind, 'label': actor['speaker'],
                      'guidance': [actor['role'], *(t['try'] for t in actor['tendencies'][:2])],
                      'source_sha256': stamp({'actor': actor, 'binding': mind})})
    return item['profile'], saved, replay_digest, clip, clip_asset, cards


def write_variant(text, anchors, parent, clip):
    fork, join = parent['fork'], parent['join']
    sep = '\r\n\r\n' if text[fork:].startswith('\r\n') else '\n\n'
    # These are the saved author-approved cutaway beats. Only the later bridge is generated.
    body = text[:fork]
    base = anchors['release'][0]
    passages, nodes = [], []

    def node(key, kind, a, b, roles=()):
        tag = 'p-'+key
        passages.append({'id': tag, 'start': a-base, 'end': b-base, 'sha256': f.digest(body[a:b])})
        nodes.append({'id': key, 'kind': kind, 'label': key.replace('-', ' ').title(),
                      'passage': tag, 'roles': list(roles), 'evidence': []})

    # The program uses separate release, notice, and exact dialogue cues.
    node('scent', 'event', *anchors['release'])
    node('scent-reaches-hall', 'direction', *anchors['scent'])
    node('haley-senses', 'direction', *anchors['notice'], ('haley',))
    node('frozen-response', 'dialogue', *anchors['line'], ('haley',))
    for key, part in (
        ('cutaway-heading', '### SCENE 4: THE THREE RETURN'),
        ('initial-split', 'The closed door rattles. Where there was one Rainee in the bathroom, there are three. Francine arrives on the upstairs landing.'),
        *COMMON, *RELAPSE_ENDING,
    ):
        start = len(body)+len(sep)
        body += sep+part
        node(key, 'heading' if key.endswith('heading') else 'event', start, len(body))
    end = len(body)
    edges = [{'from': a['id'], 'to': b['id'], 'kind': 'sequence'} for a,b in zip(nodes,nodes[1:])]
    nodes.append({'id': 'cutaway-import', 'kind': 'reference', 'label': 'Scene Import · complete cutaway (shape only)',
                  'passage': None, 'roles': [], 'evidence': [clip['id']]})
    edges.extend({'from': 'cutaway-import', 'to': key, 'kind': 'influences'}
                 for key in ('initial-split', 'francine-reunion', 'relapse'))
    decl = {'schema_version': 1, 'title': 'Spring Break · the cutaway fork', 'passages': passages,
            'nodes': nodes, 'edges': edges, 'evidence': [clip],
            'roles': [{'id': 'haley', 'label': 'Haley', 'character_hint': 'haley', 'form_hint': 'haley'}]}
    slot = {'start': end+len(sep), 'end': end+len(sep)+len(bridge.SLOT)}
    return body+sep+bridge.SLOT+sep+text[join:], {'start': base, 'end': end}, decl, slot


def route_for(world):
    at = lambda actors, place: {f'at:{actor}:{place}' for actor in actors}
    state = {f'at:{a}:{v["location"]}' for a, v in world['actors'].items()}
    state |= {f'form:{a}:{v["form"]}' for a, v in world['actors'].items()}
    # The reused Scene 7 establishes Roger's position at entry; no bridge prose moves or speaks for him.
    state |= {'car:parked', 'supplies:meals_in_house', 'supplies:keys_available',
              'at:stella:house', 'roger:driveway_at_join'}
    party = (*TRAVEL, *JOIN_PARTY)
    seats = {f'seat:{p}:{seat}' for p,seat in zip(TRAVEL,SEATS)}

    def permit(ident, scene, needs, adds, drops, stage):
        return {'id': ident, 'scene': scene, 'needs': sorted(needs), 'adds': sorted(adds),
                'drops': sorted(drops), 'stage': stage}

    actions = [
        permit('check-haley', 'hall', {'at:haley:farther-down-hall', 'at:francine:hall', 'at:stella:house'},
               {'at:haley:hall', 'at:stella:hall', 'haley:mobile'}, {'at:haley:farther-down-hall', 'at:stella:house'},
               'Haley steadies herself at the far end of the hall, then walks back to the landing. Stella meets her at the stairs.'),
        permit('round-up', 'hall', at(fx.CAST, 'bathroom') | {'at:francine:hall', 'haley:mobile'},
               at(fx.CAST, 'hall') | {'travel:assembled'}, at(fx.CAST, 'bathroom'),
               'Nurse Franny calls the three Rainees out of the bathroom. They step into the hall as three separate people.'),
        permit('leave-house-supplies', 'hall', at(party, 'hall') | {'supplies:keys_available', 'supplies:meals_in_house'},
               {'supplies:keys_with_haley', 'haley:knows_about_lasagna'}, {'supplies:keys_available'},
               'Nurse Franny leaves the house keys with Haley and points her back toward the three trays of lasagna inside.'),
        permit('head-to-driveway', 'driveway', at(party, 'hall') | {'travel:assembled', 'supplies:keys_with_haley'},
               at(party, 'driveway'), at(party, 'hall'),
               'Nurse Franny heads out with the three Rainees. Haley and Stella follow as far as the driveway.'),
        permit('board-sedan', 'driveway', at(TRAVEL, 'driveway') | {'car:parked'},
               at(TRAVEL, 'sedan') | seats, at(TRAVEL, 'driveway'),
               'Nurse Franny takes the wheel. Rainee 1 takes the front passenger seat, and Rainee 2 and Rainee 3 take the back seats.'),
        permit('depart', 'driveway', seats | at(JOIN_PARTY, 'driveway') | {'car:parked'},
               {'car:departed'}, {'car:parked'},
               'Nurse Franny starts the engine and the red sedan pulls away. Haley and Stella stay in the driveway.'),
    ]
    names = ['Nurse Franny', *fx.SPEAKERS]
    return {'start': sorted(state), 'actions': actions,
            'required': sorted(at(TRAVEL,'sedan') | seats | at(JOIN_PARTY,'driveway') |
                               {'car:departed','roger:driveway_at_join','supplies:keys_with_haley',
                                'supplies:meals_in_house','haley:knows_about_lasagna','haley:mobile'}),
            'forbidden': sorted({'car:parked','at:haley:sedan','at:stella:sedan','at:rainee:sedan'}),
            'scenes': [
                {'id':'hall','heading':'### SCENE 5: THE LANDING',
                 'location':'**INT. LING HOUSE - UPSTAIRS LANDING**',
                 'speakers':names+['Haley','Stella'],'required_speakers':names},
                {'id':'driveway','heading':'### SCENE 6: THE DEPARTURE',
                 'location':'**EXT. LING HOUSE - DRIVEWAY - 08:15 A.M.**',
                 'speakers':names+['Haley','Stella'],'required_speakers':['Nurse Franny']},
            ]}


def prepare(out, checkpoint):
    out.mkdir(exist_ok=False)
    trace = Trace(out/'TRACE.jsonl', RUN)
    trace.emit('run.manifest', 'OPENED', checkpoint='checkpoint.json', note='pause.json',
               dispatch_limit=1, trace_precedes_workspace=True)
    vault = checkpoint.parent
    record = load(checkpoint)
    resume = load(vault/'resume.json')
    with trace.span('workspace.copy') as (_, event):
        assert all(sha(path)==digest for path,digest in resume['sha_at_resume'].items())
        backup(vault/'source-recovery', out/'studio', record['before_databases'])
        event.update(checkpoint_db_hashes=record['before_databases'], integrity_check='ok', live_workspaces_unchanged=True)
    timeline = TimelineStore(out/'studio/timeline.sqlite')
    notebooks = NotebookStore(timeline)
    with trace.span('source.anchors') as (_, event):
        source, anchors, beat, parent = source_anchors(timeline)
        book = notebooks.existing(PARENT)
        assert book['timeline_revision'] == source['head'] and not book['stale']
        assert joined(book['blocks']) == source['script']
        cutoff = beat['scope_beat']
        put(out/'SOURCE_ANCHORS.json', parent | {'cutoff': cutoff, 'source_passage': beat['id'],
                                                'timing_status': beat['timing']})
        event.update(parent_revision=parent['revision'], notebook_revision=book['revision'],
                     source_sha256=parent['text_sha256'], frozen=parent['frozen'], fork=parent['fork'],
                     join=parent['join'], source_passage=beat['id'], timeline_cutoff=cutoff,
                     timing_status=beat['timing'], artifact='SOURCE_ANCHORS.json')
    with trace.span('import.source', mode='reused-evidence') as (_, event):
        profile, old_replay, replay_digest, clip, media, cast = prior_evidence(Path(record['pilot_workspace']))
        copied = out/'studio/timeline.clips'
        copied.mkdir()
        shutil.copyfile(media, copied/media.name)
        assert sha(copied/media.name) == clip['sha256']
        put(out/'IMPORTED_EVIDENCE.json',
            {'conversion': 'reused verified analysis', 'historical_replay': old_replay['id'],
             'historical_replay_sha256': replay_digest, 'clip': clip,
             'minds': [{k: a[k] for k in ('mind','form','source_sha256')} for a in cast]})
        event.update(clip=clip, imported_minds=[a['mind'] for a in cast],
                     provider_attempts=0, raw_scene_conversion='not invoked', artifact='IMPORTED_EVIDENCE.json')
    with trace.span('timeline.fork') as (_, event):
        timeline.fork(BRANCH, source['branch'], PARENT, cutoff)
        timeline.create_episode(EPISODE, 'Spring Break · The Three Return', BRANCH, 10)
        identity = timeline.scope()
        scope = {'project':identity['project_id'], 'universe':identity['universe_id'],
                 'scope_revision':identity['scope_revision'], 'episode':EPISODE, 'branch':BRANCH}
        trace.scope = scope
        script, fragment_range, declaration, slot = write_variant(source['script'], anchors, parent, clip)
        rev = timeline.save(EPISODE, 0, script=script, source_name='Spring Break MO2 r3 · copied three-Rainee fork')
        assert script[:parent['fork']] == source['script'][:parent['fork']]
        first = notebooks.open(EPISODE)
        proposed = [
            parent['frozen'] | {'value':100,'hard':True},
            {'id': MASK, **slot, 'value':25, 'sha256':f.digest(bridge.SLOT)},
        ]
        if book['masks'] or book.get('stale_masks'):
            raise ValueError('The source has pre-existing masks that need explicit branch mapping')
        saved = notebooks.save(EPISODE, first['revision'], rev, first['blocks'], 100, proposed)
        assert joined(saved['blocks']) == script
        event.update(branch_scope=scope, source_revision=rev, notebook_revision=saved['revision'],
                     source_prefix_sha256=f.digest(script[:parent['fork']]), slot=slot,
                     source_from_checkpoint=True, canonical_write=False)
    replay_store = SceneReplayStore(timeline)
    with trace.span('import.bind') as (_, event):
        replay_store.fragments.register_evidence(scope, [clip])
        result = replay_store.fragments.execute('scene.fragment.import', scope | {'timeline_revision':rev,
                                                'declaration':declaration,'selection':fragment_range})
        fragment = result['fragment']
        nodes = {n['key']: n['id'] for n in fragment['graph']['nodes']}
        policies, recipe = corrected_plan(nodes, profile, True)
        policies.update(id='spring-break-cutaway-v1', cutoff=cutoff)
        policies['locations'] = list(dict.fromkeys(policies['locations']))
        policies['protected_line']['lock'] = LOCK
        # In the actual MO2 text, Haley observes the cloud in a distinct passage before speaking.
        next(v for v in recipe['events'] if v['id']=='haley-notices')['node'] = nodes['haley-senses']
        args = scope | {'timeline_revision':rev,'fragment':fragment['id'],'fragment_revision':fragment['revision'],
                         'law_revision':WorldLawStore(timeline).open()['revision'],'profile':policies['id']}
        replay_store.install_profile(args, policies)
        edges = [edge for edge in fragment['graph']['edges'] if edge['kind']=='influences']
        assert {edge['to'] for edge in edges} == {nodes[k] for k in ('initial-split','francine-reunion','relapse')}
        assert {edge['from'] for edge in edges} == {nodes['cutaway-import']}
        put(out/'FRAGMENT.json',fragment)
        event.update(fragment=fragment['id'], revision=fragment['revision'], cutaway_node=nodes['cutaway-import'],
                     exact_influence_edges=edges, target_passages=[n['passage'] for n in fragment['graph']['nodes']
                         if n['id'] in {e['to'] for e in edges}], artifact='FRAGMENT.json')
    with trace.span('cutaway.replay') as (span, event):
        replay = replay_store.execute('scene.override.replay', args | {'recipe':recipe})['receipt']
        assert replay['world_sha256'] == stamp(replay['frames'])
        assert not replay['approved_event_ids'] and not replay['writes_canon']
        persisted = {'args':args,'recipe':recipe,'receipt':replay}
        put(out/'CUTAWAY_REPLAY.json', persisted)
        steps = {r['id']:r for r in recipe['events']}
        prev = {}
        for frame in replay['frames']:
            state = frame['state']
            changes = {k:{'before':prev.get(k),'after':v} for k,v in state.items() if prev.get(k)!=v}
            trace.emit('cutaway.frame', 'CHECKED', parent=span, step=frame['event'], destination=frame['node'],
                       operation=frame['operation'], dependencies=steps.get(frame['event'],{}).get('after',[]),
                       state_before=stamp(prev), state_after=stamp(state), changes=changes, effects=frame['effects'])
            prev = state
        event.update(replay=replay['id'], world_sha256=replay['world_sha256'], frame_count=len(replay['frames']),
                     borrowed=[{k:s[k] for k in ('event','operator','transfer','excluded')} for s in replay['overrides']],
                     artifact='CUTAWAY_REPLAY.json')
    with trace.span('bridge.plan') as (span, event):
        program = route_for(replay['frames'][-1]['state'])
        solved = scene_bridge.compile_bridge(program)
        saved_bridge = bridge.install(timeline, scope, parent=parent, replay=replay['id'], slot=slot,
                                      editable_mask=MASK, cast=cast, program=program)
        put(out/'BRIDGE_PLAN.json', {'binding':saved_bridge,'solved':solved})
        terms = {a['id']:a for a in program['actions']}
        prev = set(solved['start'])
        for frame in solved['frames']:
            facts = set(frame['state'])
            trace.emit('bridge.frame', 'CHECKED', parent=span, step=frame['id'], scene=frame['scene'],
                       needs=terms[frame['id']]['needs'], adds=sorted(facts-prev), drops=sorted(prev-facts),
                       state_before=stamp(sorted(prev)), state_after=stamp(sorted(facts)))
            prev = facts
        event.update(bridge=saved_bridge['id'], scenes=[s['id'] for s in solved['scenes']],
                     states_examined=solved['states_examined'], required=solved['goal'], reached=solved['exit'],
                     scoped_imports=saved_bridge['imports'], artifact='BRIDGE_PLAN.json')
    with trace.span('writer.preview', mode='studio-api') as (_, event), studio(out/'studio',EPISODE) as (cmd, _):
        request = scope | {'bridge':saved_bridge['id']}
        preview = cmd('scene.bridge.preview', request)
        assert preview['provider_calls'] == 0 and preview['prompt_bytes'] < bridge.LIMITS['input_bytes']
        assert preview['scope']['continuation']['binding']['bridge'] == saved_bridge['id']
        put(out/'PREVIEW.json', {'request':request,'preview':preview,'prepared_script_sha256':f.digest(script)})
        event.update(plan=preview['plan'], prompt_bytes=preview['prompt_bytes'], limits=bridge.LIMITS,
                     draft_count=0, provider_attempts=0, artifact='PREVIEW.json')
    print('Prepared and traced the real copied Spring Break, at zero writer calls.')


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('phase', choices=('prepare','probes','live','recheck','finish'))
    p.add_argument('--out', type=Path, default=BASE/'verified')
    p.add_argument('--checkpoint', type=Path, default=BASE/'checkpoint.json')
    args = p.parse_args()
    out,checkpoint=args.out.resolve(),args.checkpoint.resolve()
    if args.phase == 'prepare':
        prepare(out,checkpoint)
    else:
        from tools import spring_break_bridge_run as stages
        if args.phase == 'finish':
            stages.apply_and_recover(out,checkpoint)
        else:
            getattr(stages,args.phase)(out)


if __name__ == '__main__':
    main()
