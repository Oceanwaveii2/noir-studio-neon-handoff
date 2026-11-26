"""Verify Noir RB-02/03 on copies of a saved project; never select a workspace."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from prose_engine.beat_workflow import preview_group
from prose_engine.cook import run_cook_pipeline
from prose_engine.notebook import NotebookStore, digest, joined
from prose_engine.scoped_pipeline import build_packet, prompt_for
from prose_engine.scoped_service import execute_scoped
from story_graph import source_timing as timing
from story_graph.beat_map import map_episode
from story_graph.episode_timeline import TimelineStore
from story_graph.form_graph_store import FormGraphStore
from story_graph.source_imports import binding
from tools.u8_recovery import copy_database


def require(condition, reason):
    if not condition:
        raise ValueError(reason)


def rejected(operation, reason):
    try:
        operation()
    except ValueError:
        return
    raise ValueError(reason)


def manuscript_roundtrip(candidate, forms, out):
    episode = 'tapped-out'
    db = out / (candidate.name + '.sqlite')
    copy_database(candidate / 'timeline.sqlite', db)
    timeline = TimelineStore(db)
    notebook = NotebookStore(timeline)
    initial = timeline.get_episode(episode)
    text = initial['script']
    prior = notebook.existing(episode)
    require(text.encode('utf-8') == (candidate / 'selected-script.txt').read_bytes(), 'candidate bytes differ')
    phrase = 'Mom... I know I mutated'
    require(text.count(phrase) == 1, 'the test passage is not unique')
    start, end = text.index(phrase), text.index(phrase) + len(phrase)
    lock = dict(id='verify-only', start=start, end=end, value=100, hard=True, sha256=digest(phrase))
    locked = notebook.save(episode, prior['revision'], initial['head'], prior['blocks'], 50, [lock])
    prepare = lambda: run_cook_pipeline(timeline, forms, episode, expected_timeline_revision=initial['head'])
    with patch('story_graph.beat_map.map_episode', side_effect=ValueError('Injected map failure')):
        rejected(prepare, 'preparation unexpectedly succeeded with a failed map')
    require(notebook.existing(episode) == locked, 'failed preparation changed the notebook')
    prepared = prepare()
    require(prepare()['revision'] == prepared['revision'], 'identical preparation added a revision')
    reopened = NotebookStore(TimelineStore(db)).existing(episode)
    require(not reopened['stale'] and joined(reopened['blocks']) == text, 'reopen changed manuscript bytes')
    require(reopened['masks'] == [lock], 'preparation changed the exact lock')
    rejected(lambda: notebook.edit_text(episode, reopened['revision'], initial['head'], start, end, 'changed'),
             'an exact lock was editable through this route')
    commit = notebook.save_document(episode, reopened['revision'], initial['head'], text, initial['graph'])
    rolled_back = notebook.undo(episode, commit['revision'], commit['timeline_revision'])
    require(rolled_back['masks'] == [lock] and joined(rolled_back['blocks']) == text, 'undo changed text or its lock')
    saved = NotebookStore(TimelineStore(db)).existing(episode)
    full_export = out / (candidate.name + '-roundtrip.txt')
    full_export.write_bytes(joined(saved['blocks']).encode('utf-8'))
    require(full_export.read_bytes() == (candidate / 'selected-script.txt').read_bytes(), 'export bytes changed')
    scoped = execute_scoped(timeline, 'export', {'episode': episode, 'revision': saved['timeline_revision'],
                            'beat': 0, 'start': start, 'end': end})['scope']
    require(scoped['target'] == phrase and [start, end] in scoped['protected_ranges'], 'export omitted the exact span')
    with timeline._connect() as c:
        old_episode = c.execute('SELECT script FROM revisions WHERE episode=? AND revision=2', (episode,)).fetchone()
        old_notebook = c.execute('SELECT payload FROM notebook_revisions WHERE episode=? AND revision=12', (episode,)).fetchone()
    proposal = json.loads((candidate / 'receipt.json').read_text(encoding='utf-8'))
    require(digest(old_episode['script']) == proposal['episode_sha256'], 'episode r2 was altered')
    require(digest(joined(json.loads(old_notebook['payload'])['blocks'])) == proposal['notebook_sha256'], 'notebook r12 was altered')
    return {'candidate': candidate.name, 'sha256': digest(text), 'bytes': len(full_export.read_bytes()),
            'original_heads_preserved': True, 'failed_prepare_unchanged': True,
            'repeat_added_no_revision': True, 'exact_lock_checked': True, 'save_reopen_undo_export': 'pass'}


def actual_timing(checkpoint, chronology, out):
    db = out / 'actual-timing.sqlite'
    copy_database(checkpoint / 'timeline.sqlite', db)
    timeline = TimelineStore(db)
    hot, spring = (timeline.get_episode(episode) for episode in ('hot-scoomp', 'spring-break'))
    lines = chronology.read_bytes().decode('utf-8').splitlines(keepends=True)
    with timeline._connect() as c:
        link, imported = binding(c, 'hot-scoomp')
    require(''.join(lines) == imported['text'], 'the imported chronology does not match the retained file')
    require(imported['text'][link['start']:link['end']] == hot['script'], 'the episode is not an exact source section')
    for cut in timing.CUTS:
        require(hot['script'][cut.start:cut.end] == ''.join(lines[cut.first_line-1:cut.last_line]),
                'a verified source window does not match the original lines')

    def packet(episode, passage, viewpoint=None, beat=None):
        return build_packet(timeline, episode['id'], passage['scope_beat'] if beat is None else beat,
                            episode['head'], passage['start'], passage['end'], viewpoint)

    hot_map = map_episode(timeline, hot['id'], hot['head'])
    spans = hot_map['beats']
    beginning = spans[0]
    lead, onset, after, back, follow = [
        next(b for b in spans if b['start'] <= pos < b['end'])
        for pos in (26474, 26539, 27286, hot['script'].index('Storm light flashes outside the bay window.'), 34536)]
    checks = ((beginning, None, 0, False), (lead, None, 1, False), (onset, None, 1, False),
              (after, None, 2, True), (follow, None, 3, True), (follow, 'holly', 3, True),
              (follow, 'roger', 3, False))
    observations = []
    for passage, viewpoint, expected_beat, seen in checks:
        scope = packet(hot, passage, viewpoint)
        awakening = next((ev for ev in scope.events if ev['id'] == timing.EVENT), None)
        require(scope.beat == expected_beat and bool(awakening) == seen, 'wrong Hot Scoomp passage cutoff')
        require((timing.EVENT_TEXT in prompt_for(scope)) == seen, 'the prompt has incorrect story history')
        observations.append({'start': passage['start'], 'end': passage['end'], 'beat': scope.beat,
                             'viewpoint': viewpoint, 'awakening': awakening and awakening['perspective']})
    require(not packet(hot, back, beat=99).events, 'a later beat incorrectly advanced the flashback')
    rejected(lambda: packet(hot, lead, beat=99), 'the verified lead-in accepted a later beat')
    pair = [onset, spans[spans.index(onset) + 1]]
    require([p['scope_beat'] for p in pair] == [1, 2], 'the mapped transition does not cross the intended cutoff')
    group = preview_group(timeline, {'episode': hot['id'], 'revision': hot['head'], 'branch': hot['branch'],
                          'project': hot_map['project_id'], 'universe': hot_map['universe_id'],
                          'source_sha256': hot_map['source_sha256'], 'anchor_token': hot_map['anchor_token'],
                          'beats': [b['id'] for b in pair], 'provider': 'codex-session', 'scene_function': 'scene'})
    require(group['status'] == 'PREVIEW' and group['provider_calls'] == 0, 'group preview did not stay offline')

    spring_map = map_episode(timeline, spring['id'], spring['head'])
    spring_lines = spring['script'].splitlines(keepends=True)
    for cut in timing.SPRING_CUTS:
        require(spring['script'][cut.start:cut.end] == ''.join(spring_lines[cut.first_line-1:cut.last_line]),
                'Spring Break timing does not match the saved MO2 lines')
    spring_pair = [next(b for b in spring_map['beats'] if b['start'] == start) for start in (13549, 13560)]
    for passage, cut, expected in zip(spring_pair, (13, 14), (False, True)):
        scope = packet(spring, passage)
        nurse_active = any(f['id'] == 'nurse_pamela_franny_anderson' and f['status'] == 'active'
                           for f in scope.forms['francine']['forms'])
        require(scope.beat == cut and nurse_active == expected, 'Spring Break did not follow the saved MO2 graph')
    for passage in spring_map['beats']:
        scope = packet(spring, passage)
        require(not any(e['id'] == timing.EVENT for e in scope.events), 'Spring Break received the future event')
        require(not any(f['id'] == timing.FORM[1] for f in scope.forms['haley']['forms']), 'Spring Break received the future form')
    for passage in [spring_map['beats'][2], spring_map['beats'][-1]]:
        for viewpoint in (None, 'haley', 'holly'):
            request = {'episode': spring['id'], 'revision': spring['head'], 'beat': 99,
                       'start': passage['start'], 'end': passage['end'], 'viewpoint': viewpoint}
            exported = execute_scoped(timeline, 'export', request)['scope']
            require(timing.EVENT not in json.dumps(exported) and timing.FORM[1] not in json.dumps(exported),
                    'the export contains the future awakening')
            require(not execute_scoped(timeline, 'retrieve', dict(request, query='awakens fox power'))['results'],
                    'retrieval found the future awakening')
            claims = [{'kind': 'event', 'subject': 'haley', 'value': timing.EVENT},
                      {'kind': 'active_form', 'subject': 'haley', 'value': timing.FORM[1]}]
            issues = execute_scoped(timeline, 'validate', dict(request, claims=claims))['issues']
            require({item.get('claim') for item in issues} >= {1, 2},
                    'validation accepted the future claim')
            require(timing.EVENT_TEXT not in prompt_for(packet(spring, passage, viewpoint, beat=99)),
                    'the writing prompt contains the future awakening')

    for branch, beat in [('before-awakening', 1), ('after-awakening', 2)]:
        timeline.fork(branch, 'main', 'hot-scoomp', beat)
        timeline.create_episode(branch+'-ep', 'Copied Spring Break for branch check', branch, 1)
        timeline.save(branch+'-ep', 0, script=spring['script'], source_name=spring['source_name'])
    for branch, expected in [('before-awakening', False), ('after-awakening', True)]:
        scope = build_packet(timeline, branch+'-ep', 99, 1, 0, 130)
        require(any(e['id'] == timing.EVENT for e in scope.events) == expected, 'fork inherited the wrong event')
    require(not timeline.prerequisites('tapped-out'), 'later episode lost its valid prerequisite')
    return {'hot_scoomp_revision': hot['head'], 'hot_scoomp_sha256': hot['script_sha256'],
            'source_sha256': digest(''.join(lines)), 'source_verified_passages': sum(p['timing']=='source-verified' for p in spans),
            'observations': observations, 'flashback_beat_99_withheld': True, 'group_cutoffs': [1, 2],
            'spring_break_revision': spring['head'], 'spring_break_sha256': spring['script_sha256'],
            'spring_break_passages_checked': len(spring_map['beats']), 'spring_break_beat_99_adapters': 'pass',
            'spring_break_verified_graph_beats': [13, 14],
            'before_and_after_forks': 'pass', 'tapped_out_prerequisite': 'pass', 'provider_calls': 0}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('checkpoint', 'chronology', 'candidates', 'out'):
        parser.add_argument('--'+name, type=Path, required=True)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=False)
    forms_path = args.out / 'character-forms.sqlite'
    copy_database(args.checkpoint / 'character-forms.sqlite', forms_path)
    forms = FormGraphStore(forms_path)
    result = {'tapped_out': [manuscript_roundtrip(args.candidates / name, forms, args.out)
                             for name in ('keep-episode', 'keep-notebook')],
              'timing': actual_timing(args.checkpoint, args.chronology, args.out)}
    (args.out / 'receipt.json').write_text(json.dumps(result, indent=2)+'\n', encoding='utf-8')
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
