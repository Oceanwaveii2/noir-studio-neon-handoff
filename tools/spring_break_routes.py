"""Stage, reopen and join two offline routes on the copied Spring Break workspace."""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from copy import deepcopy
import json
from pathlib import Path
from secrets import token_urlsafe
from shutil import copy2
import subprocess
import sys
from threading import Thread
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from prose_engine import scene_bridges, scene_clips
from prose_engine.notebook import NotebookStore, joined
from prose_engine.service_daemon import NoirService, ServiceHTTP
from story_graph import scene_branches, scene_bridge, scene_fragments as fragments
from story_graph.episode_timeline import TimelineStore
from story_graph.scene_override import SceneReplayStore, _unpack
from telemetry.scene_bridge_trace import Trace, read_trace
from tools.spring_break_bridge import BASE, EPISODE as SEED, PARENT, ROOT, TRAVEL, JOIN_PARTY, sha
from tools.spring_break_bridge_run import verify_boundaries
from tools.verify_fx06_mind_drafts import backup, load, put, studio


OUT = ROOT / '.app-steward/local/noir-evo09-12'
RUN = 'spring-break-offline-routes'
ROUTES = {
    'landing': ('spring-break-landing-handoff', 'Spring Break · Landing Handoff'),
    'window': ('spring-break-window-handoff', 'Spring Break · Driver’s Window Handoff'),
}
LINES = {
    'landing': {
        'round-up': [
            ('Nurse Franny', 'All three of you, with me. Leave Haley some room.'),
            ('Rainee 1', 'Single file. I will take the front.'),
            ('Rainee 2', 'Haley, just say if you need a minute.'),
            ('Rainee 3', 'You two are both standing in the doorway.'),
        ],
        'leave-house-supplies': [('Haley', 'Keys and lasagna. I got it.')],
        'head-to-driveway': [('Nurse Franny', 'Front passenger first. Everyone else, around the back.')],
    },
    'window': {
        'bring-trio-to-door': [
            ('Nurse Franny', 'Easy on the stairs. Stella already has her.'),
            ('Rainee 1', 'Let them clear the door, then we go.'),
            ('Rainee 2', 'I can wait. Haley, you good?'),
            ('Rainee 3', 'The door opens toward us.'),
        ],
        'keys-through-window': [
            ('Nurse Franny', 'Three trays in the house. Hang on to those keys.'),
            ('Haley', 'I heard you. Go already.'),
        ],
    },
}


def no_writer(*_):
    raise AssertionError('An offline Spring Break action attempted to use a story writer')


def timeline(path):
    return TimelineStore(path / 'timeline.sqlite')


def clone(source, target):
    backup(source, target)
    (target / 'timeline.clips').mkdir()
    for path in (source / 'timeline.clips').glob('*.mp4'):
        copy2(path, target / 'timeline.clips' / path.name)
        assert sha(target / 'timeline.clips' / path.name) == path.stem


def _at(actors, place):
    return {f'at:{actor}:{place}' for actor in actors}


def window_program(source):
    """Shift the assembly to the front door and the key handoff until after boarding."""
    spec = deepcopy(source)
    party = (*TRAVEL, *JOIN_PARTY)
    travel = set(TRAVEL)
    old = {a['id']: a for a in spec['actions']}
    entrance, driveway = spec['scenes']
    entrance.update(id='front-door', heading='### SCENE 5: THE FRONT DOOR',
                    location='**INT. LING HOUSE - FRONT ENTRY**')
    driveway['heading'] = '### SCENE 6: THE DRIVER’S WINDOW'

    def action(ident, scene, needs, adds, drops, text):
        return {'id': ident, 'scene': scene, 'needs': sorted(needs), 'adds': sorted(adds),
                'drops': sorted(drops), 'stage': text}

    old['depart']['needs'].append('supplies:keys_with_haley')
    old['depart']['required_silence'] = True
    spec['actions'] = [
        action('stella-helps-haley', 'front-door',
               {'at:haley:farther-down-hall', 'at:stella:house'},
               _at(JOIN_PARTY, 'front-door') | {'haley:mobile'},
               {'at:haley:farther-down-hall', 'at:stella:house'},
               'Stella meets Haley at the end of the hall and walks downstairs with her. They wait by the front door.'),
        action('bring-trio-to-door', 'front-door',
               _at(travel - {'francine'}, 'bathroom') | {'at:francine:hall', 'haley:mobile'},
               _at(TRAVEL, 'front-door') | {'travel:assembled'},
               _at(travel - {'francine'}, 'bathroom') | {'at:francine:hall'},
               'Nurse Franny brings the three Rainees downstairs to the front door, where Haley and Stella are waiting.'),
        action('cross-driveway', 'driveway', _at(party, 'front-door') | {'travel:assembled'},
               _at(party, 'driveway'), _at(party, 'front-door'),
               'Stella holds the door while the others step outside. Haley follows them to the sedan.'),
        old['board-sedan'],
        action('keys-through-window', 'driveway', _at(JOIN_PARTY, 'driveway') |
               {'at:francine:sedan', 'seat:francine:driver', 'supplies:keys_available',
                'supplies:meals_in_house', 'car:parked'},
               {'supplies:keys_with_haley', 'haley:knows_about_lasagna'}, {'supplies:keys_available'},
               'Through the open driver’s window, Nurse Franny puts the house keys in Haley’s hand and points back toward the house.'),
        old['depart'],
    ]
    return spec


def _translated(value, nodes):
    if isinstance(value, dict):
        return {key: _translated(item, nodes) for key, item in value.items()}
    if isinstance(value, list):
        return [_translated(item, nodes) for item in value]
    return nodes.get(value, value) if isinstance(value, str) else value


def seed_context(store):
    """Recover the exact archived fork and confirm its inputs before using it as a seed."""
    packet = load(BASE / 'verified/CUTAWAY_REPLAY.json')
    with store._connect() as c:
        bridge_row = c.execute('SELECT * FROM scene_bridge_specs WHERE episode=?', (SEED,)).fetchone()
        record = _unpack(bridge_row)
        replay, stamp = scene_branches._replay(c, record['scope'], record['replay'])
        assert stamp == record['replay_sha256']
        assert replay == packet['receipt']
        assert fragments.digest(fragments.encoded(packet['recipe'])) == replay['recipe_sha256']
        registry = fragments.SceneFragmentStore(store)
        row = registry._find(c, SEED, replay['fragment'], replay['fragment_revision'])
        assert row['sha256'] == replay['graph_sha256']
        raw = registry._record(row)
        _, template = registry._target_at(c, raw)
        public = registry._public(raw, replay['timeline_revision'], raw['revision'], 'OPENED')['fragment']
        profile = _unpack(c.execute('SELECT * FROM scene_replay_profiles WHERE episode=? AND id=?',
                                    (SEED, replay['profile'])).fetchone())['profile']
    assert template[record['slot']['start']:record['slot']['end']] == scene_bridges.SLOT
    return record, replay, raw, public, template, profile, packet['recipe']


def install_route(store, key, seed, path):
    record, original, fragment, old_public, script, profile, recipe = seed
    branch, title = ROUTES[key]
    episode = branch + '-scene'
    parent = record['parent']
    store.fork(branch, parent['branch'], parent['episode'], record['cutoff'])
    store.create_episode(episode, title, branch, 10)
    request = record['scope'] | {'branch': branch, 'episode': episode}
    revision = store.save(episode, 0, script=script, source_name='Spring Break MO2 r3 · offline bridge fork')
    notes = NotebookStore(store)
    opened = notes.open(episode)
    masks = [parent['frozen'] | {'value': 100, 'hard': True},
             {'id': record['editable_mask'], **record['slot'], 'value': 25,
              'sha256': fragments.digest(scene_bridges.SLOT)}]
    saved = notes.save(episode, opened['revision'], revision, opened['blocks'], 100, masks)
    assert joined(saved['blocks']) == script
    registry = fragments.SceneFragmentStore(store)
    evidence = fragment['declaration']['evidence']
    registry.register_evidence(request, evidence)
    fresh = registry.execute('scene.fragment.import', request | {
        'timeline_revision': revision, 'declaration': fragment['declaration'],
        'selection': {side: fragment['anchor'][side] for side in ('start', 'end')}})['fragment']
    new = {n['key']: n['id'] for n in fresh['graph']['nodes']}
    nodes = {n['id']: new[n['key']] for n in old_public['graph']['nodes']}
    args = request | {'timeline_revision': revision, 'fragment': fresh['id'],
                      'fragment_revision': fresh['revision'], 'law_revision': original['law_revision'],
                      'profile': original['profile']}
    replay_store = SceneReplayStore(store)
    replay_store.install_profile(args, _translated(profile, nodes))
    recipe = _translated(recipe, nodes)
    replay = replay_store.execute('scene.override.replay', args | {'recipe': recipe})['receipt']
    assert replay['frames'] == _translated(original['frames'], nodes)
    assert replay['overrides'] == original['overrides'] and not replay['writes_canon']
    program = record['program'] if key == 'landing' else window_program(record['program'])
    solved = scene_bridge.compile_bridge(program)
    assert solved['exit'] == record['exit']
    data = scene_bridges.install(store, request, parent=parent, replay=replay['id'], slot=record['slot'],
                                 editable_mask=record['editable_mask'], cast=record['cast'], program=program)
    for clip in evidence:
        media = path / 'timeline.clips' / (clip['sha256'] + '.mp4')
        assert sha(media) == clip['sha256']
        with media.open('rb') as stream:
            scene_clips.intake(store, request | {'name': 'Complete Cutaway.mp4'}, stream, media.stat().st_size)
    return {'request': request | {'bridge': data['id']}, 'scope': request, 'revision': revision,
            'slot': record['slot'], 'replay_args': args, 'replay': replay['id'], 'recipe': recipe,
            'world_sha256': replay['world_sha256'], 'solution': solved}


def candidate(solution, dialogue):
    parts = []
    for scene in solution['scenes']:
        lines = [scene['heading'], scene['location']]
        for beat in scene['beats']:
            lines.extend(('', beat['stage']))
            lines.extend(f'{speaker}: {words}' for speaker, words in dialogue.get(beat['id'], ()))
        parts.append('\n'.join(lines))
    return '\n\n'.join(parts)


def reject(command, action, payload, *messages):
    try:
        command(action, payload)
    except (RuntimeError, ValueError) as error:
        assert any(message.casefold() in str(error).casefold() for message in messages), str(error)
    else:
        raise AssertionError('An invalid branch operation was accepted')


@contextmanager
def local_service(store):
    class Offline:
        connect = staticmethod(no_writer)

    service = NoirService(store, ROOT / 'books', Offline())
    token = token_urlsafe(24)
    try:
        with ServiceHTTP(0, service, token) as server:
            worker = Thread(target=server.serve_forever, daemon=True)
            worker.start()
            origin = f'http://127.0.0.1:{server.server_port}'

            def command(action, payload):
                request = Request(origin + '/v1/command', json.dumps({'action': action, 'request': payload}).encode(),
                                  {'Content-Type': 'application/json', 'Authorization': 'Bearer ' + token})
                try:
                    with urlopen(request, timeout=30) as reply:
                        return json.load(reply)
                except HTTPError as error:
                    with error:
                        raise RuntimeError(json.load(error)['error']) from error

            try:
                yield command
            finally:
                server.shutdown()
                worker.join()
    finally:
        service.close()


def stage(out):
    checkpoint = load(out / 'checkpoint.json')
    path = out / 'workspace'
    store = timeline(path)
    trace = Trace(out / 'trace.jsonl', RUN)
    seed = seed_context(store)
    trace.emit('source.fork', 'CHECKED', frozen=seed[0]['parent']['frozen'], join=seed[0]['parent']['join'],
               story_provider_calls=0)
    routes = {key: install_route(store, key, seed, path) for key in ROUTES}
    landing = [f['id'] for f in routes['landing']['solution']['frames']]
    window = [f['id'] for f in routes['window']['solution']['frames']]
    assert landing.index('leave-house-supplies') < landing.index('board-sedan')
    assert window.index('board-sedan') < window.index('keys-through-window')
    assert landing != window
    impossible = window_program(seed[0]['program'])
    impossible['actions'] = [a for a in impossible['actions'] if a['id'] != 'keys-through-window']
    try:
        scene_bridge.compile_bridge(impossible)
    except ValueError as error:
        assert 'No authorized action sequence' in str(error)
    else:
        raise AssertionError('Departure was accepted without the house key handoff')

    with studio(path, routes['landing']['scope']['episode']) as (cmd, server):
        server.test_writer_factory = no_writer
        for key, route in routes.items():
            trace.scope = route['scope']
            request = route['request']
            preview = cmd('scene.bridge.preview', request)
            assert preview['provider_calls'] == 0
            continuation = preview['scope']['continuation']
            assert continuation['program'] == route['solution']
            turns = {turn['beat']: turn for turn in continuation['turns']}
            assert turns['reunion']['actors']['francine']['form'] == 'francine'
            peter = 'peter_griffin_celestial_variant'
            assert peter not in {a['form'] for a in turns['reunion']['actors'].values()}
            assert turns['peter-transformation']['actors']['rainee']['form'] == peter
            assert {actor['mind'] for actor in continuation['minds']} == {
                actor['mind'] for actor in seed[0]['cast']}
            assert not preview['scope']['events']
            text = candidate(route['solution'], LINES[key])
            save = request | {'plan': preview['plan'], 'text': text}
            if key == 'landing':
                early = deepcopy(LINES[key])
                early['check-haley'] = [('Rainee 2', 'Wait for me.')]
                reject(cmd, 'scene.bridge.save', save | {'text': candidate(route['solution'], early)}, 'unavailable')
                late = text.replace('Keys and lasagna. I got it.', 'The Hot Scoomp awakening already happened.')
                reject(cmd, 'scene.bridge.save', save | {'text': late}, 'unavailable', 'out-of-scope')
            result = cmd('scene.bridge.save', save)
            assert result['provider_calls'] == 0 and not result['replayed']
            assert len(cmd('scene.bridge.open', request)['drafts']) == 1
            assert cmd('scene.timeline.open', route['scope'] | {'timeline_revision': route['revision']})[
                'bridge_state'] == 'planned'
            route.update(plan=preview['plan'], save=result, text=text)
            trace.emit('draft.saved', 'CHECKED', plan=preview['plan'], draft=result['draft_id'],
                       candidate_sha256=result['candidate_sha256'], route_steps=[f['id'] for f in route['solution']['frames']],
                       active_minds=[a['mind'] for a in continuation['minds']], story_provider_calls=0)
    assert len({r['plan'] for r in routes.values()}) == 2
    assert len({r['save']['draft_id'] for r in routes.values()}) == 2
    assert len({r['save']['candidate_sha256'] for r in routes.values()}) == 2
    clone(path, out / 'before-rejoin')
    put(out / 'routes.json', routes)
    confirm_source(checkpoint)
    print('Two scoped route drafts are saved before rejoin. Both are ready to reopen after restart.')


def _rebind(cmd, route, head):
    requests = route['replay_args'] | {'timeline_revision': head}
    current = cmd('scene.fragment.open', route['scope'] | {'fragment': requests['fragment']})['fragment']
    rebound = cmd('scene.fragment.rebind', requests | {'fragment_revision': current['revision']})['fragment']
    replay = cmd('scene.override.replay', requests | {'fragment_revision': rebound['revision'], 'recipe': route['recipe']})['receipt']
    assert replay['world_sha256'] == route['world_sha256']
    return replay['id']


def _view(cmd, route, head):
    return cmd('scene.timeline.open', route['scope'] | {'timeline_revision': head})


def confirm_source(checkpoint):
    source = ROOT / checkpoint['source_workspace']
    assert {name: sha(source / name) for name in checkpoint['source_sha256']} == checkpoint['source_sha256']


def join(out, scratch=False):
    checkpoint, routes = load(out / 'checkpoint.json'), load(out / 'routes.json')
    path = out / ('sibling-regression' if scratch else 'workspace')
    if scratch:
        clone(out / 'before-rejoin', path)
    trace = Trace(out / ('sibling-regression-trace.jsonl' if scratch else 'trace.jsonl'), RUN)
    store = timeline(path)
    notes = NotebookStore(store)
    parent = seed_context(store)[0]['parent']
    source = store.get_episode(PARENT)
    rehearsed = {}
    with local_service(store) as service:
        with ThreadPoolExecutor(max_workers=2) as workers:
            jobs = {key: workers.submit(service, 'draft.open', route['scope'] | {'draft': route['save']['draft_id']})
                    for key, route in routes.items()}
            for key, job in jobs.items():
                saved = job.result()
                route = routes[key]
                trace.scope = route['scope']
                assert saved['text'] == route['text'] and saved['request_budget']['max_provider_calls'] == 0
                assert saved.get('attempt_id') is None and saved['provider'] == 'offline-bridge'
                assert scene_bridges.SLOT in store.get_episode(route['scope']['episode'])['script']
                reopened = service('scene.bridge.save', route['request'] | {'plan': route['plan'], 'text': saved['text']})
                assert reopened == route['save'] | {'replayed': True}
                rehearsed[key] = saved
                trace.emit('draft.resumed', 'CHECKED', mode='authenticated-service', draft=saved['id'],
                           candidate_sha256=route['save']['candidate_sha256'], story_provider_calls=0)
        reject(service, 'draft.open', routes['landing']['scope'] | {'draft': rehearsed['window']['id']}, 'branch')
        # Reopen through the episode CLI before any edit is applied.
        payload = routes['window']['scope'] | {'draft': rehearsed['window']['id']}
        cli = subprocess.run([sys.executable, '-B', '-m', 'prose_engine', 'episode', 'draft.open', '--timeline',
                              str(path / 'timeline.sqlite'), '--request', '-'],
                             cwd=ROOT, input=json.dumps(payload), text=True, encoding='utf-8',
                             capture_output=True, check=True, timeout=30)
        assert json.loads(cli.stdout) == rehearsed['window']

    outcome = {}
    with studio(path, routes['landing']['scope']['episode']) as (cmd, server):
        server.test_writer_factory = no_writer
        for key, route in routes.items():
            trace.scope = route['scope']
            episode = route['scope']['episode']
            opened = notes.existing(episode)
            before = joined(opened['blocks'])
            apply = route['scope'] | {'draft': rehearsed[key]['id'], 'timeline_revision': opened['timeline_revision'],
                                     'notebook_revision': opened['revision'], 'request_id': 'apply-' + rehearsed[key]['id']}
            saved = cmd('draft.apply', apply)
            assert saved['status'] == 'APPLIED'
            state = saved['notebook']
            text = joined(state['blocks'])
            slot = route['slot']
            assert text == before[:slot['start']] + route['text'] + before[slot['end']:]
            repeated = cmd('draft.apply', apply)
            assert repeated['status'] == 'REPLAYED' and repeated['receipt'] == saved['receipt']
            assert repeated['notebook'] == state
            proof = verify_boundaries(source['script'], text, parent, state)
            replay = _rebind(cmd, route, state['timeline_revision'])
            view = _view(cmd, route, state['timeline_revision'])
            assert view['bridge_state'] == 'applied' and view['replay'] == replay
            assert sum(clip['clip'] is not None for sc in view['scenes'] for beat in sc['beats']
                       for clip in beat['clips'] if clip['purpose'] == 'structure') == 3
            if key == 'landing':
                sibling = routes['window']
                assert cmd('draft.open', sibling['scope'] | {'draft': rehearsed['window']['id']}) == rehearsed['window']
                assert scene_bridges.SLOT in store.get_episode(sibling['scope']['episode'])['script']
            outcome[key] = {'apply': apply, 'receipt': saved['receipt'], 'replay': replay,
                            'script_sha256': fragments.digest(text), **proof}
            trace.emit('roger.join', 'CHECKED', draft=rehearsed[key]['id'], **outcome[key])
    assert store.get_episode(PARENT) == source
    assert outcome['landing']['roger_sha256'] == outcome['window']['roger_sha256']
    assert outcome['landing']['script_sha256'] != outcome['window']['script_sha256']
    confirm_source(checkpoint)
    put(out / ('sibling-regression-outcome.json' if scratch else 'joined.json'), outcome)
    print('Both independently resumed drafts reached the exact Roger rejoin.')


def restore(out):
    routes, outcomes = load(out / 'routes.json'), load(out / 'joined.json')
    trace = Trace(out / 'trace.jsonl', RUN)
    restored = out / 'restored'
    if restored.exists():
        restored = out / f'restored-{trace.sequence + 1}'
    clone(out / 'workspace', restored)
    store = timeline(restored)
    parent = seed_context(store)[0]['parent']
    source = store.get_episode(PARENT)['script']
    with studio(restored, routes['landing']['scope']['episode']) as (cmd, server):
        server.test_writer_factory = no_writer
        for key, route in routes.items():
            trace.scope = route['scope']
            expected = outcomes[key]
            result = cmd('draft.apply', expected['apply'])
            assert result['status'] == 'REPLAYED' and result['receipt'] == expected['receipt']
            repeated_save = cmd('scene.bridge.save', route['request'] | {'plan': route['plan'], 'text': route['text']})
            assert repeated_save == route['save'] | {'replayed': True}
            state = result['notebook']
            final_text = joined(state['blocks'])
            assert verify_boundaries(source, final_text, parent, state)['roger_sha256'] == expected['roger_sha256']
            assert _view(cmd, route, state['timeline_revision'])['replay'] == expected['replay']
            for command in ('notebook.undo', 'notebook.redo'):
                state = cmd(command, route['scope'] | {
                    'timeline_revision': state['timeline_revision'], 'notebook_revision': state['revision'],
                    'request_id': f'{key}-{command.replace(".", "-")}'})['notebook']
                saved = joined(state['blocks'])
                assert (scene_bridges.SLOT in saved) == command.endswith('.undo')
                assert verify_boundaries(source, saved, parent, state)['frozen_sha256'] == expected['frozen_sha256']
            assert joined(state['blocks']) == final_text and fragments.digest(final_text) == expected['script_sha256']
            replay = _rebind(cmd, route, state['timeline_revision'])
            assert _view(cmd, route, state['timeline_revision'])['replay'] == replay
            (out / (key + '-bridge.md')).write_text(route['text'] + '\n', 'utf-8')
            trace.emit('workspace.restored', 'CHECKED', draft=route['save']['draft_id'],
                       receipt=expected['receipt'], undo_redo_exact=True, story_provider_calls=0)
    stale = out / 'parent-drift'
    if stale.exists():
        stale = out / f'parent-drift-{trace.sequence + 1}'
    backup(out / 'before-rejoin', stale)
    changed = timeline(stale)
    ep = changed.get_episode(PARENT)
    notes = NotebookStore(changed)
    book = notes.existing(PARENT)
    end = len(ep['script'])
    updated = notes.edit_text(PARENT, book['revision'], ep['head'], end, end, '\n')
    assert updated['timeline_revision'] != ep['head']
    with studio(stale, routes['window']['scope']['episode']) as (cmd, server):
        server.test_writer_factory = no_writer
        route = routes['window']
        before = changed.get_episode(route['scope']['episode'])
        reject(cmd, 'draft.apply', outcomes['window']['apply'], 'parent episode changed')
        assert changed.get_episode(route['scope']['episode']) == before
    trace.emit('parent.drift', 'REJECTED', exact_parent_revision_required=True, story_provider_calls=0)
    confirm_source(load(out / 'checkpoint.json'))
    put(out / 'verification.json', {'story_provider_calls': 0, 'routes': outcomes, 'resume_before_join': True,
                                    'service_and_cli_opened_scope': True, 'undo_redo_exact': True,
                                    'source_files_verified': True, 'parent_drift_rejected': True,
                                    'restored_workspace': str(restored),
                                    'trace_records': len(read_trace(out / 'trace.jsonl'))})
    print('The restored workspace reopened both routes and reproduced both manuscripts after Undo and Redo.')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('phase', choices=('stage', 'join', 'restore'))
    parser.add_argument('--out', type=Path, default=OUT)
    parser.add_argument('--scratch', action='store_true', help='join a scratch copy of the pre-join checkpoint')
    args = parser.parse_args(argv)
    if args.phase == 'join':
        join(args.out, args.scratch)
    elif args.phase == 'stage':
        stage(args.out)
    else:
        restore(args.out)


if __name__ == '__main__':
    main()
