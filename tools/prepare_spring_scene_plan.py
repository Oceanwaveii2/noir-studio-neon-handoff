"""Register the authored turn permissions on a restored Spring Break copy."""

import argparse
import json
from pathlib import Path

from prose_engine import scene_plan
from prose_engine.notebook import NotebookStore, digest
from story_graph import scene_branches
from story_graph.episode_timeline import TimelineStore


EPISODES = ('spring-break-three-little-bitches-scene', 'spring-break-three-little-bitches-clothes-scene')
SIBLINGS = ('rainee-split-1', 'rainee-split-2', 'rainee-split-3')
SCENT_SOURCE = (Path(__file__).resolve().parents[1] / 'deliverables' /
                'NOIR_FX06_GAG_COLLECTION_20261116' / 'rainee_split_mind_support.json')


def turn(stage=None, *, speakers=(), listeners=(), required=(), phase='after'):
    return {'stage':stage, 'speakers':list(speakers), 'listeners':list(listeners),
            'required':list(required), 'phase':phase}


def prepare(workspace, *, unlock=False):
    store = TimelineStore(workspace / 'timeline.sqlite')
    rule_source = json.loads(SCENT_SOURCE.read_text(encoding='utf-8'))
    turns = {
        'entry': turn(),
        'first-release': turn(),
        'haley-notices': turn(),
        'haley-line': turn(speakers=('haley',), listeners=('francine',)),
        'split': turn('Behind the bathroom door, Rainee splits into three.'),
        'voice-intervention': turn('On the landing, Francine calls to the three Rainees.',
                                   speakers=('francine',), listeners=SIBLINGS, required=('francine',)),
        'reunion': turn('Francine brings the three Rainees back into one body.'),
        'peter-transformation': turn('Only after the reunion, Rainee transforms into Rainee Peter Griffen.'),
        'francine-laughs': turn('Francine steadies herself on the banister while she laughs.'),
        'francine-asks-nurse': turn('Francine asks her wife to turn her into a nurse.',
                                    speakers=('francine', 'rainee'), listeners=('francine', 'rainee'),
                                    required=('francine',)),
        'nurse-franny': turn('Rainee Peter Griffen changes Francine into Nurse Franny, who turns to Haley.',
                             speakers=('francine',), listeners=('haley',), required=('francine',)),
        'peter-release': turn('Rainee Peter Griffen lets out a blast from the bathroom.'),
        'haley-defeated': turn('The force carries Haley down the hall.'),
        'destabilizes': turn('Rainee Peter Griffen loses her form and the same three Rainees return.'),
        'group-release': turn('The three returning Rainees release a second blast with distinct scents.',
                              speakers=('haley',), listeners=SIBLINGS, required=('haley',), phase='before'),
        'haley-blasted-again': turn('Haley is pushed farther down the hall.'),
        'group-roast': turn('The three Rainees call down the hall to Haley.',
                            speakers=(*SIBLINGS, 'haley'), listeners=(*SIBLINGS, 'haley'), required=SIBLINGS),
    }
    plans = {}
    for episode in EPISODES:
        with store._connect() as connection:
            row = connection.execute('SELECT * FROM scene_bridge_specs WHERE episode=?', (episode,)).fetchone()
            if not row:
                raise ValueError('Restore the Spring Break proposal checkpoint before establishing this plan')
            record = scene_branches._unpack(row)
        scope = record['scope']
        minds = {card['form']:card['mind'] for card in record['cast']}
        scents = {rule['form']:{'trigger':rule['trigger'], 'scent':rule['scent'], 'mind':minds[rule['form']],
                                'source':rule['source_url']} for rule in rule_source['rules']}
        scene_plan.register(store, scope | {'bridge':record['id']},
                            heading='### SCENE 4: THE THREE LITTLE BITCHES', turns=turns, scents=scents)
        head = store.get_episode(episode)['head']
        request = scope | {'timeline_revision':head}
        plan = scene_plan.open_plan(store, request)['plan']
        if unlock:
            # Only the disposable writing region becomes editable. Keep other saved masks.
            notebook = NotebookStore(store)
            book = notebook.existing(episode)
            start, end = (plan['target'][edge] for edge in ('start', 'end'))
            mask_id = 'scene-plan-writable'
            masks = [mask for mask in book['masks'] if mask['id'] not in (record['editable_mask'], mask_id)]
            if any(mask['start'] < end and start < mask['end'] for mask in masks):
                raise ValueError('A pre-existing mask owns part of this scene')
            text = store.get_episode(episode)['script']
            masks.append({'id':mask_id, 'start':start, 'end':end, 'value':25,
                          'sha256':digest(text[start:end])})
            notebook.save(episode, book['revision'], head, book['blocks'], book['default_protection'], masks)
            plan = scene_plan.open_plan(store, request)['plan']
        plans[episode] = plan
    return plans


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--workspace', type=Path, required=True, help='A restored proposal workspace')
    parser.add_argument('--unlock', action='store_true', help='Set this copy’s planned passage to 25%')
    args = parser.parse_args()
    plans = prepare(args.workspace, unlock=args.unlock)
    print(json.dumps({episode:{'id':plan['id'], 'target':plan['target']}
                      for episode, plan in plans.items()}, indent=2))


if __name__ == '__main__':
    main()
