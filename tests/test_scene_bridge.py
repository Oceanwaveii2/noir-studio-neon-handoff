"""Shared bridge constraints and auditable run boundaries."""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from prose_engine.scene_bridges import SLOT, _import_bindings, validate_output
from story_graph.scene_bridge import compile_bridge
from telemetry.scene_bridge_trace import Trace, read_trace


def setup():
    return {'start':['car:parked','at:driver:hall'],
            'required':['car:departed','at:driver:car','at:haley:driveway'],
            'forbidden':['car:parked','at:haley:car'],
            'scenes':[{'id':'departure','heading':'### SCENE 6: THE DEPARTURE','location':'**EXT. DRIVEWAY**',
                       'speakers':['Driver','Haley'],'required_speakers':['Driver']}],
            'actions':[
                {'id':'drive', 'scene':'departure', 'needs':['at:driver:car','car:parked','at:haley:driveway'],
                 'adds':['car:departed'],'drops':['car:parked'],'stage':'The car leaves the driveway.'},
                {'id':'board', 'scene':'departure','needs':['at:driver:hall','car:parked'],
                 'adds':['at:driver:car'],'drops':['at:driver:hall'],'stage':'The driver gets in.'},
                {'id':'stay','scene':'departure','needs':['at:driver:car'],
                 'adds':['at:haley:driveway'],'drops':[],'stage':'Haley waits by the driveway.'},
            ]}


class BridgeTests(unittest.TestCase):
    def test_bridge_preview_and_run_share_the_configured_book_library(self):
        from prose_engine.scene_bridges import execute

        scope = {'project': 'project-a', 'universe': 'universe-a', 'episode': 'episode-a', 'branch': 'branch-a',
                 'scope_revision': 1}
        request = scope | {'bridge': 'bridge-a', 'references': 'luar'}
        record = {'id': 'bridge-a', 'scope': scope, 'cutoff': 3, 'slot': {'start': 100, 'end': 145}}
        book_root = Path('configured-library')
        preview = {'scope': scope, 'rhythm_guidance': {'id': 'guided-plan', 'fully_locked': False},
                   'prompt_bytes': 1000}
        proposal = {'status': 'PROPOSED', 'draft_id': 'saved-proposal'}
        with (patch('prose_engine.scene_bridges.f.SceneFragmentStore._scope', return_value=(scope, 2)),
              patch('prose_engine.scene_bridges._read', return_value=(record, 'scope-sha')),
              patch('prose_engine.scene_bridges._resolve'),
              patch('prose_engine.scoped_service.execute_scoped', side_effect=[preview, preview, proposal]) as scoped):
            store = MagicMock()
            plan = execute(store, 'scene.bridge.preview', request, books_root=book_root)
            result = execute(store, 'scene.bridge.run', request | {'plan': plan['plan']}, books_root=book_root)
        self.assertEqual(result['draft_id'], 'saved-proposal')
        self.assertEqual([call.args[1] for call in scoped.call_args_list], ['rhythm-preview', 'rhythm-preview', 'generate'])
        for call in scoped.call_args_list:
            self.assertEqual(call.args[2]['references'], 'luar')
            self.assertEqual(call.args[2]['reference_delivery'], 'excerpt')
            self.assertEqual(call.kwargs['books_root'], book_root)
        self.assertEqual(scoped.call_args.args[2]['rhythm_plan_id'], 'guided-plan')

    def test_plan_respects_preconditions_and_the_destination_entry(self):
        spec=setup()
        program=compile_bridge(spec)
        self.assertEqual([f['id'] for f in program['frames']],['board','stay','drive'])
        self.assertTrue(set(spec['required']) <= set(program['exit']))
        self.assertFalse(set(program['exit']) & set(spec['forbidden']))
        without_handoff=deepcopy(spec)
        without_handoff['actions'].pop()
        with self.assertRaisesRegex(ValueError,'No authorized action sequence'):
            compile_bridge(without_handoff)

    def test_required_silence_survives_search_and_only_wired_offscreen_speech_is_allowed(self):
        from prose_engine.scene_bridges import _turns
        spec = setup()
        spec['actions'].append({'id':'pause', 'scene':'departure', 'needs':['car:parked','at:driver:car'],
                                'adds':[], 'drops':[], 'stage':'A pause.', 'required_silence':True})
        spec['actions'][1]['audible_to_scene'] = ['Driver']
        solved = compile_bridge(spec)
        replay = {'frames':[{'event':'entry','state':{'root':'driver','actors':{},'manifestations':[]}}]}
        turns, _ = _turns({'cast':[], 'program':spec}, replay, solved, {})
        by_id = {t['beat']:t['speakers'] for t in turns}
        self.assertEqual(by_id['pause'], [])
        self.assertEqual(by_id['board'], ['Driver'])
        self.assertNotIn('Driver', by_id['stay'])

    def test_forbidden_facts_cannot_be_exit_conditions(self):
        spec=setup()
        spec['forbidden'].append('at:haley:driveway')
        with self.assertRaisesRegex(ValueError,'consistent preconditions'):
            compile_bridge(spec)

    def test_writer_may_add_speech_but_not_duplicate_destination_or_move_cast(self):
        book={'program':compile_bridge(setup())}
        good=('### SCENE 6: THE DEPARTURE\n**EXT. DRIVEWAY**\nThe driver gets in.\n'
              'Driver: Everyone ready to go?\nHaley waits by the driveway.\nThe car leaves the driveway.')
        self.assertEqual(validate_output(book,good),[])
        self.assertEqual(validate_output(book,good.replace('Everyone ready to go?','Yes.')),[])
        self.assertTrue(validate_output(book,good.replace('Everyone ready to go?','---')))
        self.assertTrue(validate_output(book,good.replace('Driver:','Peter:')))
        self.assertTrue(validate_output(book,good.replace('Haley waits by the driveway.','Haley gets in.')))
        self.assertTrue(validate_output(book,good+'\n### SCENE 7: ROGER'))
        self.assertTrue(validate_output(book,good+'\nDriver: And another thing.'))
        self.assertTrue(validate_output(book,SLOT))

    def test_turn_permissions_reject_early_lines_and_keep_departure_silent(self):
        program = compile_bridge(setup())
        text = ('### SCENE 6: THE DEPARTURE\n**EXT. DRIVEWAY**\nThe driver gets in.\n'
                'Driver: Ready?\nHaley waits by the driveway.\nThe car leaves the driveway.')
        bridge = {'program': program, 'turns': [{'beat':'board','speakers':['Driver']},
                  {'beat':'stay','speakers':['Driver','Haley']}, {'beat':'drive','speakers':[]}]}
        self.assertEqual(validate_output(bridge, text), [])
        self.assertTrue(validate_output(bridge, text.replace('Driver: Ready?', 'Haley: Wait!\nDriver: Ready?')))
        self.assertTrue(validate_output(bridge, text+'\nDriver: Goodbye!'))

    def test_scene_plan_enforces_each_turn_even_for_an_active_actor(self):
        from prose_engine.scene_plan import validate_output as validate_plan_output

        plan = {'form_labels':{'future-form':'Future Form'}, 'scenes':[
            {'id':'scene', 'heading':'### SCENE 1: THE FORK', 'location':None,
             'beats':['step', 'witness'], 'required_speakers':[]},
        ], 'turns':[
            {'id':'step', 'stage':'A pause.', 'speakers':[], 'revealed_forms':[]},
            {'id':'witness', 'stage':'The witness looks up.', 'revealed_forms':[],
             'speakers':[{'label':'Witness', 'required':True}]},
        ]}
        continuation = {'plan':plan}
        text = '### SCENE 1: THE FORK\nA pause.\nThe witness looks up.\nWitness: I am here.'
        self.assertEqual(validate_plan_output(continuation, text), [])
        self.assertEqual(validate_plan_output(continuation, text.replace('A pause.', 'A pause.\nWitness: Wait.')),
                         ['Witness cannot speak at step'])
        self.assertEqual(validate_plan_output(continuation, text.replace('I am here.', 'I know Future Form.')),
                         ['Dialogue reveals an unavailable form at witness'])
        self.assertEqual(validate_plan_output(continuation, text.split('\nWitness')[0]),
                         ['A required speaker is missing at witness'])

    def test_mind_tactics_follow_their_connected_forms_and_visible_knowledge(self):
        from types import SimpleNamespace
        from prose_engine.scene_plan import _tactic

        character = SimpleNamespace(id='character:rainee', mind_behaviors={'second':'Wait for Francine.'})
        actor = {'character':'rainee', 'form':'second', 'mind':'mind:second'}
        seed = {'guidance':['Back the leader.'], 'source_sha256':'1'*64}
        edited = _tactic(actor, seed, {'rainee':character}, (), {'second'}, {'future':'Future Form'})
        base = _tactic(actor, seed, {}, (), {'second'}, {'future':'Future Form'})
        self.assertEqual(edited['guidance'], ['Wait for Francine.'])
        self.assertEqual(base['guidance'], ['Back the leader.'])
        self.assertNotEqual(edited['revision'], base['revision'])
        character.mind_behaviors['second'] = 'Tell them about Future Form.'
        self.assertEqual(_tactic(actor, seed, {'rainee':character}, (), {'second'},
                                 {'future':'Future Form'})['status'], 'withheld')

    def test_imports_must_land_on_a_used_exact_edge_never_the_retained_scene(self):
        graph={'id':'fragment-copy','revision':1,'graph':{
            'nodes':[{'id':'ref','kind':'reference','evidence':['source']},
                     {'id':'split-node','kind':'event','passage':'p1'},
                     {'id':'roger','kind':'event','passage':'p2'}],
            'edges':[{'from':'ref','to':'split-node','kind':'influences'}]}}
        replay={'frames':[{'event':'split','node':'split-node'}], 'overrides':[
                 {'event':'split','transfer':'shape_only','operator':'invert_merge','evidence':{'id':'source'}}]}
        proof=_import_bindings(graph,replay,compile_bridge(setup()),
                [{'mind':'mind-1','form':'person-1','label':'Driver','source_sha256':'1'*64}])
        self.assertEqual(proof['cutaway'][0]['passage'],'p1')
        self.assertEqual(proof['minds'][0]['targets'][0]['beats'],['board','stay','drive'])
        graph['graph']['edges'].append({'from':'ref','to':'roger','kind':'influences'})
        with self.assertRaisesRegex(ValueError,'Unbound or unused influences'):
            _import_bindings(graph,replay,compile_bridge(setup()),[])

    def test_trace_chain_survives_reopen_and_detects_altered_events(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'TRACE.jsonl'
            tr=Trace(path,'run')
            with tr.span('copy') as (ident,proof):
                proof['integrity']='ok'
            child=Trace(path,'run')
            child.emit('retry','REOPENED',parent=ident,attempts=0)
            rows=read_trace(path)
            self.assertEqual([i['sequence'] for i in rows],[1,2,3])
            self.assertEqual(rows[1]['parent_event'],rows[0]['event'])
            self.assertEqual(rows[2]['previous_sha256'],rows[1]['sha256'])
            rows[1]['status']='CHANGED'
            path.write_text(''.join(json.dumps(row)+'\n' for row in rows),'utf-8')
            with self.assertRaisesRegex(ValueError,'sequence or digest check'):
                read_trace(path)


if __name__ == '__main__':
    unittest.main()
