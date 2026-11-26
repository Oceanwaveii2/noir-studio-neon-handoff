"""Stage and verify the reviewed Spring Break attachments on a restored workspace."""

import argparse
from copy import deepcopy
from hashlib import file_digest
import json
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from prose_engine.episode_commands import EpisodeCommands
from prose_engine.notebook import NotebookStore, digest
from prose_engine.scene_clips import intake
from prose_engine.scoped_pipeline import build_packet, prompt_for
from story_graph import fx06_scene, scene_branches, scene_fragments
from story_graph.episode_timeline import TimelineStore
from tools.prepare_spring_scene_plan import EPISODES, SIBLINGS


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'deliverables/NOIR_FX06_GAG_COLLECTION_20261116'
PLACEHOLDER = '[Scene to write]'
PETER = 'peter_griffin_celestial_variant'
TIMING = {
    'peter-release': ('ad-s03e07-francine-password',
                      'If stomach pain is already present, give it a beat to register. '
                      'Leave a short pause before the sound. Keep the knockback at its own beat.'),
    'group-release': ('fg-s17e13-wine-lunch',
                      'Keep the three short sounds distinct. Let the last one land before the listener reacts.'),
    'group-roast': ('fg-s09e02-lois-dinner',
                    'Let the first remark land. Hold briefly for the listener’s delayed reaction before the next reply.'),
}
EDIT = 'When the group is about to answer at once, wait for the first reply before reinforcing the group rule.'


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def write(path, data):
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def sha(path):
    with path.open('rb') as stream:
        return file_digest(stream, 'sha256').hexdigest()


def history(store):
    with store._connect() as c:
        tables = ('events', 'episode_drafts', 'episode_writing_runs', 'scene_replay_receipts')
        return {name: digest(scene_fragments.encoded([list(row) for row in c.execute(
                    f'SELECT * FROM {name} ORDER BY rowid')])) for name in tables}


def boundaries(store, plan):
    script = store.get_episode(plan['scope']['episode'])['script']
    frozen, join = plan['frozen'], plan['rejoin']
    cue, suffix = script[frozen['start']:frozen['end']], script[join['start']:]
    assert digest(cue) == frozen['sha256'] and len(cue.encode('utf-8')) == 107
    assert digest(suffix) == join['sha256'] and len(suffix.encode('utf-8')) == 4568
    return {'cue_sha256': digest(cue), 'cue_utf8_bytes': 107,
            'roger_sha256': digest(suffix), 'roger_utf8_bytes': 4568}


def stage_assets(store, scope, cutaway_sha, index):
    def upload(path, name, expected):
        assert sha(path) == expected
        with path.open('rb') as stream:
            asset = intake(store, scope | {'name': name}, stream, path.stat().st_size)
        assert asset['content_sha256'] == expected
        return asset

    cutaway = upload(SOURCE / 'Neural Graph/Complete Cutaway.mp4', 'Complete Cutaway.mp4', cutaway_sha)
    library, durations = [], {}
    for row in index['rows']:
        ident, media = row['id'], row['media']
        asset = upload(SOURCE / 'Fart Media/Episode Clips' / ident / media['file'], ident + '.mp4', media['sha256'])
        assert row['can_supply_personality_memory_or_canon'] is False
        library.append({'source': ident, 'clip': asset['id'], 'category': row['category'],
                        'title': f"{row['show']} {row['local_episode_number']} · {row['subject']}",
                        'content_sha256': asset['content_sha256'], 'note': row['timing'],
                        'source_range_ms': [round(value * 1000) for value in row['source_range_s']]})
        durations[ident] = asset['duration_ms']
    return cutaway['id'], library, durations


def stage(store, out):
    """Use the existing importer and an empty target on the recovery copy."""
    api = EpisodeCommands(store).execute
    bundle = fx06_scene.load_bundle(SOURCE)
    donor_path = SOURCE / 'Mean Girls (2004)/Mined Evidence/donor_override.json'
    access = read(donor_path)['access']
    index = read(SOURCE / 'Fart Media/episode_index.json')
    scents = read(SOURCE / 'rainee_split_mind_support.json')
    receipt = {'history': history(store), 'branches': {}, 'source_manifests': bundle['manifests']}
    with store._connect() as c:
        scopes = [scene_branches._unpack(c.execute('SELECT * FROM scene_bridge_specs WHERE episode=?',
                                                  (episode,)).fetchone())['scope'] for episode in EPISODES]
    for scope in scopes:
        episode = scope['episode']
        request = scope | {'timeline_revision': store.get_episode(episode)['head']}
        plan = api('scene.plan.open', request)['plan']
        assert 'inputs' not in plan
        before = boundaries(store, plan)
        start, end = (plan['target'][key] for key in ('start', 'end'))
        notebook = NotebookStore(store)
        if store.get_episode(episode)['script'][start:end] != PLACEHOLDER:
            notebook.edit_text(episode, plan['notebook_revision'], plan['timeline_revision'],
                               start, end, PLACEHOLDER, planned_blocks=[{
                                   'kind': 'stage-direction', 'speaker': None, 'form': None, 'text': PLACEHOLDER,
                               }])
        request['timeline_revision'] = store.get_episode(episode)['head']
        plan = api('scene.plan.open', request)['plan']
        start, end = (plan['target'][key] for key in ('start', 'end'))
        if plan['target']['protection'] != [[start, end, 25]]:
            book = notebook.existing(episode)
            assert not any(mask['start'] < end and start < mask['end'] for mask in book['masks'])
            mask = {'id': 'scene-08b-writing-target', 'start': start, 'end': end, 'value': 25,
                    'sha256': digest(PLACEHOLDER)}
            notebook.save(episode, book['revision'], request['timeline_revision'], book['blocks'],
                          book['default_protection'], book['masks'] + [mask])
        api('episode.prepare', request)
        prepared = api('episode.preparation.open', request)['receipt']
        plan = api('scene.plan.open', request)['plan']
        assert digest(PLACEHOLDER) == plan['target']['sha256']
        assert plan['target']['protection'] == [[start, end, 25]]
        assert boundaries(store, plan) == before
        sockets = {row['form']: row for row in prepared['sockets'] if row['form'] in SIBLINGS}
        assert set(sockets) == set(SIBLINGS)
        cutaway, library, durations = stage_assets(store, scope, bundle['cutaway']['sha256'], index)
        package = {'schema_version': 1, 'cutaway': cutaway, 'timing_library': library, 'scent_rules': scents,
                   'donor': {'source': access['source'], 'title': 'Mean Girls (2004)', 'sha256': access['sha256'],
                             'review_sha256': sha(donor_path), 'window_ms': access['allow_interval_ms'],
                             'evidence': [{'id': item['id'], 'span_ms': item['span_ms']}
                                          for item in bundle['evidence'].values()]},
                   'minds': [{'port': sockets[actor['form_id']]['port'], 'form': actor['form_id'],
                              'mind': sockets[actor['form_id']]['mind']['node_id'],
                              'tendencies': actor['tendencies'], 'constraint': actor['constraint']}
                             for actor in bundle['actors']],
                   'timing_pins': [{'beat': beat, 'node': prepared['turn_sockets']['beats'][beat], 'source': ident,
                                    'selection_ms': [0, durations[ident]], 'direction': note}
                                   for beat, (ident, note) in TIMING.items()]}
        filename = out / (episode + '.inputs.json')
        write(filename, package)
        receipt['branches'][episode] = {'request': request, 'boundaries': before, 'preparation': prepared,
                                        'before_plan': plan['id'], 'package': filename.name}
    assert history(store) == receipt['history']
    write(out / 'staged.json', receipt)


def studio(origin):
    def web(path, data=None):
        headers = {'Origin': origin, 'Content-Type': 'application/json'} if data is not None else {}
        encoded = json.dumps(data, ensure_ascii=False).encode('utf-8') if data is not None else None
        with urlopen(Request(origin + path, encoded, headers), timeout=35) as response:
            return json.load(response)
    return web


def preview(api, store, plan):
    scope = plan['scope']
    target = plan['target']
    request = scope | {'scene_plan': plan['id'], 'revision': plan['timeline_revision'],
                       'notebook_revision': plan['notebook_revision'], 'beat': plan['cutoff'],
                       'start': target['start'], 'end': target['end'], 'provider': 'codex-session',
                       'references': 'none', 'scene_function': 'comedy'}
    value = api('run.selection.preview', request)
    assert value['scope']['continuation']['plan'] == plan
    assert value['provider_calls'] == 0 and value['generation_started'] is False
    packet = build_packet(store, scope['episode'], request['beat'], request['revision'], target['start'], target['end'],
                          project_id=scope['project'], universe_id=scope['universe'], branch=scope['branch'],
                          continuation_binding={'scene_plan': plan['id']})
    prompt = prompt_for(packet, scene_function='comedy', rhythm_guidance=value['rhythm_guidance'])
    assert value['prompt_sha256'] == digest(prompt)
    assert value['prompt_bytes'] == len(prompt.encode('utf-8')) and 0 < value['prompt_bytes'] <= 28_000
    return value['prompt_sha256'], prompt


def rejected(api, action, request, expected):
    try:
        api(action, request)
    except HTTPError as error:
        body = json.load(error)
        assert error.code == 400 and expected in body['error'], body
        return body
    raise AssertionError('The invalid input was accepted')


def turns(plan):
    return {turn['id']: turn for turn in plan['turns']}


def preflight(store, out, origin):
    web = studio(origin)

    def api(action, request):
        return web('/api/episode-command', request | {'action': action})

    staged = read(out / 'staged.json')
    checks = {}
    for episode, spec in staged['branches'].items():
        scope = spec['request']
        package = read(out / spec['package'])
        binding = scope | {'scene_plan': spec['before_plan'], 'preparation': spec['preparation']['id']}
        audition = deepcopy(package)
        audition['timing_pins'][0]['source'] = next(
            item['source'] for item in package['timing_library'] if item['category'] == 'emitter_candidate')
        wrong_node = deepcopy(package)
        wrong_node['timing_pins'][0]['node'] = spec['preparation']['turn_sockets']['beats']['split']
        wrong_form = deepcopy(package)
        wrong_form['minds'][0]['port'] = wrong_form['minds'][1]['port']
        wrong_source = package | {'cutaway': package['timing_library'][0]['clip']}
        tests = (
            ('audition', binding, audition, 'writing-eligible timing source'),
            ('wrong_beat', binding, wrong_node, 'exact writable replay beat'),
            ('wrong_port', binding, wrong_form, 'exact prepared form socket'),
            ('wrong_cutaway', binding, wrong_source, 'exact Complete Cutaway edition'),
            ('stale_preparation', binding | {'preparation': '0' * 64}, package, 'preparation receipt'),
        )
        checks[episode] = {name: rejected(api, 'scene.plan.inputs.attach', req | {'package': value}, message)
                           for name, req, value, message in tests}
        assert api('scene.plan.open', scope)['plan']['id'] == spec['before_plan']
        with store._connect() as c:
            from prose_engine.scene_mind_support import read as read_library
            assert read_library(c, scope) is None
    assert history(store) == staged['history']
    write(out / 'attachment-rejections.json', checks)


def verify_edits(api, open_plan, web, store, originals):
    episode = EPISODES[0]
    graph = web('/api/form-graph?' + urlencode({'episode': episode}))
    edit = {'action': 'save_node_data', 'character': 'rainee', 'episode': episode,
            'node': 'data:character:rainee:form:rainee-split-2'}
    before = {ep: preview(api, store, plan)[1] for ep, plan in originals.items()}
    changed = web('/api/form-graph', edit | {'revision': graph['revision'],
                                            'content': {'text_fields': {'behavior': EDIT}}})
    differences = {}
    try:
        for ep, old in originals.items():
            new = open_plan(ep)
            normalized = deepcopy(new['turns'])
            eligible = []
            old_turns = turns(old)
            for turn in normalized:
                for speaker in turn['speakers']:
                    if speaker['form'] == SIBLINGS[1]:
                        previous = next(item for item in old_turns[turn['id']]['speakers'] if item['form'] == SIBLINGS[1])
                        assert speaker['mind']['author_guidance'] == EDIT
                        assert speaker['mind']['tendencies'] == previous['mind']['tendencies']
                        assert speaker['mind']['revision'] != previous['mind']['revision']
                        speaker['mind'] = previous['mind']
                        eligible.append(turn['id'])
            assert normalized == old['turns']
            assert len(eligible) == (5 if ep == episode else 7)
            _, revised = preview(api, store, new)
            assert revised.count(EDIT) == len(eligible)
            assert revised.replace(EDIT + ' | ', '') == before[ep]
            differences[ep] = eligible
    finally:
        web('/api/form-graph', edit | {'action': 'undo_node_data', 'revision': changed['revision']})
    assert all(open_plan(ep) == plan for ep, plan in originals.items())
    return differences


def verify(store, out, origin):
    web = studio(origin)

    def api(action, request):
        return web('/api/episode-command', request | {'action': action})

    staged = read(out / 'staged.json')
    report = {'branches': {}, 'provider_calls': 0}

    def open_plan(episode):
        return api('scene.plan.open', staged['branches'][episode]['request'])['plan']

    originals = {episode: open_plan(episode) for episode in staged['branches']}
    for episode, spec in staged['branches'].items():
        request, prepared = spec['request'], spec['preparation']
        package = read(out / spec['package'])
        plan = originals[episode]
        assert plan['inputs']['library'] == {'title': 'Fart Media', 'eligible': 12, 'audition_only': 2}
        assert plan['inputs']['preparation'] == prepared['id']
        assert boundaries(store, plan) == spec['boundaries'] and plan['target']['sha256'] == digest(PLACEHOLDER)
        ledger = turns(plan)
        assert len(ledger) == (23 if episode == EPISODES[0] else 25)
        cuts = {ident: turn['structure'] for ident, turn in ledger.items() if
                turn.get('structure', {}).get('kind') == 'cutaway'}
        assert {ident: item['operator'] for ident, item in cuts.items()} == {
            'split': 'invert_merge', 'reunion': 'reuse_merge', 'destabilizes': 'invert_merge'}
        assert all((item['evidence']['selector']['start'], item['evidence']['selector']['end']) ==
                   (117400, 117500) for item in cuts.values())
        assert ledger['peter-transformation']['structure']['after'] == 'reunion'
        assert ledger['peter-transformation']['after']['rainee']['form'] == PETER
        assert ledger['haley-line']['frozen'] and ledger['haley-line']['speakers'][0]['form'] == 'haley'
        assert {turn['id']: [rule['scent'] for rule in turn['rules']] for turn in plan['turns'] if turn['rules']} == {
            'group-release': ['tuberose', 'orange', 'sandalwood']}
        assert len(ledger['group-roast']['relationships']) == 6
        assert all(edge['kind'] == 'spouse' and {edge['from']['character'], edge['to']['character']} ==
                   {'francine', 'rainee'} for edge in ledger['group-roast']['relationships'])
        assert all(turn['relationships'] for turn in plan['turns'])
        tactics = {card['form']: card for card in package['minds']}
        for turn in plan['turns']:
            for speaker in turn['speakers']:
                if card := tactics.get(speaker['form']):
                    assert speaker['mind']['tendencies'] == card['tendencies']
                    assert speaker['mind']['constraint'] == card['constraint']
                    assert speaker['mind']['port'] == card['port']
                    assert speaker['actor'] in turn[turn['phase']]
        for beat in ('haley-line', 'reunion', 'peter-transformation', 'peter-release'):
            assert not any(speaker['mind'] for speaker in ledger[beat]['speakers'])
        inspected = api('mind.inspect', request | {'turn': 'haley-line', 'character': 'rainee', 'form': PETER})
        peter = inspected['selected']
        assert peter['status'] == 'planning_only' and not peter['speaker_allowed'] and peter['card'] is None
        assert open_plan(episode) == plan
        prompt_sha, prompt = preview(api, store, plan)
        assert prompt.count('[Cutaway shape only') == 3
        assert prompt.count('[Timing and reaction only') == 3
        assert '[Spouses in this beat:' in prompt
        for item in package['timing_library']:
            assert item['content_sha256'] not in prompt
            if item['category'] not in ('direct_emitter', 'dialogue_report'):
                assert item['note'] not in prompt and item['source'] not in prompt
        assert all(name not in prompt for name in ('Regina George', 'Gretchen Wieners', 'Karen Smith'))
        assert all(move['when'] in prompt and move['try'] in prompt
                   for card in tactics.values() for move in card['tendencies'])

        pin = plan['inputs']['pins']['group-roast']
        toggle = request | {'scene_plan': plan['id'], 'pin': pin['id'], 'enabled': False}
        detached = api('scene.plan.inputs.timing', toggle)['plan']
        assert [row for row, other in zip(plan['turns'], detached['turns']) if row != other] == [ledger['group-roast']]
        assert turns(detached)['group-roast'] == {key: value for key, value in ledger['group-roast'].items() if key != 'timing'}
        assert all(open_plan(other) == saved for other, saved in originals.items() if other != episode)
        _, without = preview(api, store, detached)
        assert prompt.replace(f'[Timing and reaction only · {pin["direction"]}]\n', '') == without
        stale = rejected(api, 'scene.plan.inputs.timing', toggle, 'scene plan changed')
        assert api('scene.plan.inputs.timing', toggle | {'scene_plan': detached['id'], 'enabled': True})['plan'] == plan
        replayed = api('scene.plan.inputs.attach', request | {
            'scene_plan': plan['id'], 'preparation': prepared['id'], 'package': package,
        })
        assert replayed['plan'] == plan
        assert open_plan(episode) == plan
        report['branches'][episode] = {'plan': plan, 'prompt_sha256': prompt_sha,
                                       'prompt_utf8_bytes': len(prompt.encode('utf-8')),
                                       'boundaries': spec['boundaries'], 'early_peter': peter,
                                       'detach': {'beat': pin['beat'], 'pin': pin['id'], 'stale_error': stale}}
    changed = verify_edits(api, open_plan, web, store, originals)
    for episode, rows in changed.items():
        report['branches'][episode]['rainee_2_changed_turns'] = rows
    assert history(store) == staged['history']
    report['preserved_history'] = staged['history']
    write(out / 'ledger-verification.json', report)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', choices=('stage', 'preflight', 'verify'))
    parser.add_argument('--workspace', type=Path, required=True)
    parser.add_argument('--evidence', type=Path, required=True)
    parser.add_argument('--origin', default='http://127.0.0.1:8954')
    args = parser.parse_args()
    db = (args.workspace / 'timeline.sqlite').resolve(strict=True)
    store = TimelineStore(db)
    if args.mode == 'stage':
        stage(store, args.evidence)
    elif args.mode == 'preflight':
        preflight(store, args.evidence, args.origin)
    else:
        verify(store, args.evidence, args.origin)


if __name__ == '__main__':
    main()
