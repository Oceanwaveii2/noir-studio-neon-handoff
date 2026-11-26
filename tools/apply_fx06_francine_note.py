"""Save and verify the corrected Francine beats as two new authored branch results."""
from __future__ import annotations

import argparse
from copy import deepcopy
import json
from pathlib import Path
import shutil

from prose_engine.branch_continuations import NURSE
from prose_engine.episode_commands import EpisodeCommands
from story_graph import fx06_scene as fx
from story_graph.episode_timeline import TimelineStore
from tools.register_fx06_exchange import sha
from tools.verify_fx06_branches import _graph_plan, _scene, install_forks, rejected
from tools.verify_fx06_exchange import POINTER, RELAPSE, RESULT, SIBLING, _story_frame
from tools.verify_fx06_mind_drafts import DBS, backup, load, put, studio

FORKS = (('fx06-francine-peter', 'Francine’s Reunion · Peter Holds', False),
         ('fx06-francine-relapse', 'Francine’s Reunion · The Three Return', True))
COMMON = (
    ('francine-reunion', 'Regular Francine calls all three Rainees back together using her voice. The three converge into one Rainee.'),
    ('peter-arrives', 'Only after the reunion does Rainee swell into her enormous Peter form, big as a house.'),
    ('francine-laughs', 'Francine laughs at the sight of Rainee as Peter.'),
    ('francine-asks-nurse', 'Francine asks Rainee to use her power to make her a sexy nurse.'),
    ('nurse-arrives', 'While Rainee is still Peter, her power turns Francine into Nurse Franny.'),
    ('peter-payoff', 'A blast from Rainee Peter sends Haley to the far end of the hall.'),
)
RELAPSE_ENDING = (
    ('relapse', 'After the first blast, Peter destabilizes into the same three Rainees.'),
    ('group-blast', 'The three Rainees let loose together. Their blast sends Haley farther down the hall.'),
    ('group-roast', 'Only after the second blast do the three roast Haley, taking distinct turns. The three stay separate.'),
)
FARTHER = 'farther-down-hall'


def corrected_scene(*args):
    return _scene(*args, beats=COMMON, ending=RELAPSE_ENDING, rejoin='francine-reunion')


def corrected_plan(nodes, registered, relapse):
    policy, recipe = _graph_plan(nodes | {'nurse-reunion': nodes['francine-reunion']}, registered, relapse)
    policy['id'] = 'fx06-francine-reunion-v2'
    rules = policy['branch_rules']
    rules['intervention_forms'] = {'francine': 'francine'}
    nurse = next(row for row in rules['transforms'] if row['id'] == NURSE)
    nurse['requires_actor_form'] = {'actor': 'rainee', 'form': fx.PETER}

    def event(ident, node, op, actor, args=None, after=()):
        return {'id': ident, 'node': nodes[node], 'op': op, 'actor': actor,
                'args': args or {}, 'after': list(after)}

    events = {row['id']: row for row in recipe['events']}
    events['nurse-franny']['after'] = ['francine-asks-nurse']
    events['peter-release']['after'] = ['nurse-franny']
    before = ('first-release', 'haley-notices', 'haley-line', 'split', 'voice-intervention', 'reunion',
              'peter-transformation')
    recipe['events'] = [events[k] for k in before] + [
        event('francine-laughs', 'francine-laughs', 'beat', 'francine', after=('peter-transformation',)),
        event('francine-asks-nurse', 'francine-asks-nurse', 'beat', 'francine', after=('francine-laughs',)),
        events['nurse-franny'], events['peter-release'], events['haley-defeated'],
    ]
    if relapse:
        policy['locations'].append(FARTHER)
        rules['reactivated_group_force'] = {'node': nodes['group-blast'],
                                           'visible_from': [policy['force']['destination']], 'destination': FARTHER}
        recipe['events'].extend([
            events['destabilizes'],
            event('group-release', 'group-blast', 'group_release', 'rainee', {'after_reactivation': 'destabilizes'}),
            event('haley-blasted-again', 'group-blast', 'force', 'haley', {'release': 'group-release'}),
            event('group-roast', 'group-roast', 'beat', 'rainee', after=('haley-blasted-again',)),
        ])
    return policy, recipe


def check(cases):
    left, right = [[{k: v for k, v in frame.items() if k != 'node'} for frame in case['replay']['frames']]
                   for case in cases]
    assert left == right[:-4]
    frames = {frame['event']: frame for frame in right}
    assert list(frames)[5:] == [
        'voice-intervention', 'reunion', 'peter-transformation', 'francine-laughs', 'francine-asks-nurse',
        'nurse-franny', 'peter-release', 'haley-defeated', 'destabilizes', 'group-release',
        'haley-blasted-again', 'group-roast',
    ]
    for key in ('voice-intervention', 'reunion', 'peter-transformation', 'francine-laughs', 'francine-asks-nurse'):
        assert frames[key]['state']['actors']['francine']['form'] == 'francine'
    assert frames['voice-intervention']['effects'] == [{'intervention': 'francine'}]
    assert frames['reunion']['state']['root_form'] == 'rainee' and not frames['reunion']['state']['manifestations']
    assert frames['nurse-franny']['state']['actors']['francine']['form'] == NURSE
    assert frames['nurse-franny']['state']['root_form'] == fx.PETER
    assert left[-1]['state']['root_form'] == fx.PETER and not left[-1]['state']['manifestations']
    assert right[-1]['state']['root_form'] == 'split'
    assert frames['split']['state']['manifestations'] == right[-1]['state']['manifestations']
    assert frames['group-release']['effects'][0]['release']['emitters'] == list(fx.CAST)
    assert [r['release'] for r in right[-1]['state']['reactions']] == ['peter-release', 'group-release']
    assert right[-1]['state']['actors']['haley']['location'] == FARTHER
    assert len(left[-1]['state']['reactions']) == 1
    assert left[-1]['state']['actors']['haley']['location'] == 'far-hall'
    assert cases[0]['result']['exact_dialogue'] == cases[1]['result']['exact_dialogue']
    assert cases[0]['result']['exact_dialogue']['sha256'] == fx.fingerprint(fx.PERFUME_LINE)


def apply(source, before, out, evidence):
    source, before, out, evidence = [p.resolve(strict=p != out) for p in (source, before, out, evidence)]
    before_bytes = {name: sha(source/name) for name in DBS} | {'pointer': sha(POINTER)}
    out.mkdir(exist_ok=False)
    graph_path = out/'studio'
    backup(before, graph_path)
    if (source/'timeline.clips').is_dir():
        shutil.copytree(source/'timeline.clips', graph_path/'timeline.clips')
    timeline = TimelineStore(graph_path/'timeline.sqlite')
    base = _story_frame(graph_path)
    original = load(evidence)
    receipt_args = RELAPSE | {'result': RESULT, 'receipt': original['receipt']['id']}
    assert EpisodeCommands(timeline).execute('scene.exchange.receipt', receipt_args)['sha256'] == original['sha256']
    with timeline._connect() as c:
        before_drafts = [tuple(r) for r in c.execute('SELECT * FROM episode_drafts ORDER BY id')]
        row = c.execute('SELECT payload FROM scene_branch_results WHERE id=?', (RESULT,)).fetchone()
        parent = json.loads(row['payload'])['parent']
    cases = install_forks(timeline, parent['scope'], parent['replay'], forks=FORKS, scene_plan=corrected_scene,
                          graph_plan=corrected_plan, source_name='FX06 author correction: Francine’s reunion and nurse request')
    check(cases)
    assert _story_frame(graph_path) == base
    assert {case['result']['id'] for case in cases}.isdisjoint({RESULT, SIBLING})
    with timeline._connect() as c:
        assert [tuple(r) for r in c.execute('SELECT * FROM episode_drafts ORDER BY id')] == before_drafts
    assert EpisodeCommands(timeline).execute('scene.exchange.receipt', receipt_args)['receipt'] == original['receipt']
    right = cases[1]
    with studio(graph_path, parent['scope']['episode']) as (call, _):
        for case in cases:
            opened = call('scene.branches.open', case['scope'] | {'result': case['result']['id']})
            assert any(row['id'] == case['result']['id'] and row['current'] for row in opened['results'])
            preview = call('scene.branches.preview', case['scope'] | {'result': case['result']['id']})
            assert preview['provider_calls'] == 0
            assert 'Francine laughs at the sight of Rainee as Peter.' in preview['scope']['continuation']['prior']
        assert 'Only after the second blast' in preview['scope']['continuation']['prior']
        wrong = deepcopy(right['recipe'])
        next(e for e in wrong['events'] if e['id'] == 'group-release')['args']['after_reactivation'] = 'split'
        rejected(call, 'scene.override.preview', right['args'] | {'recipe': wrong}, 'missing_prerequisite')
        wrong = deepcopy(right['recipe'])
        wrong['events'] = [e for e in wrong['events'] if e['id'] != 'haley-blasted-again']
        rejected(call, 'scene.override.preview', right['args'] | {'recipe': wrong}, 'missing_prerequisite')
    assert {name: sha(source/name) for name in DBS} | {'pointer': sha(POINTER)} == before_bytes
    put(out/'branches.json', cases)
    for case in cases:
        path = out/(case['scope']['branch']+'.txt')
        with path.open('x', encoding='utf-8', newline='') as file:
            file.write(timeline.get_episode(case['scope']['episode'])['script'])
    put(out/'VERIFICATION.json', {
        'status': 'VERIFIED_ON_COPY', 'workspace': str(graph_path), 'provider_calls': 0,
        'new_results': [{'id': case['result']['id'], 'scope': case['scope'], 'events': [
            frame['event'] for frame in case['replay']['frames']],
                         'dialogue_sha256': case['result']['exact_dialogue']['sha256']} for case in cases],
        'historical_drafts_and_exchange_preserved': True, 'older_branch_state_preserved': True,
        'active_pointer_preserved': True, 'rejections': ['group release before repeat split', 'roast without second hit'],
    })
    print(f'Saved and verified two corrected branches in {graph_path}')


def main():
    p = argparse.ArgumentParser(description=__doc__)
    for arg in ('source', 'before', 'out', 'evidence'):
        p.add_argument('--'+arg, required=True, type=Path)
    args = p.parse_args()
    apply(args.source, args.before, args.out, args.evidence)


if __name__ == '__main__':
    main()
