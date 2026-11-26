import hashlib
import json
import shutil
import subprocess
import unittest
from pathlib import Path
from unittest.mock import patch

from prose_engine.notebook import NotebookStore, joined
from prose_engine.processed_reader import _speaker, publish_processed_workspace
from prose_engine.source_migration import publish_bundle, publish_workspace
from story_graph.beat_map import map_episode
from story_graph.episode_timeline import TimelineStore
from story_graph.source_imports import snapshot as source_snapshot


class ProcessedReaderTests(unittest.TestCase):
    def setUp(self):
        from tests.test_source_migration import SourceMigrationTests
        SourceMigrationTests.setUp(self)
        self.bundle = publish_bundle(self.source, self.root/'bundles')
        self.file = self.root/'processed.md'
        text = '# CHAPTER\r\n\r\n' + ''.join(
            f'### SCENE {i}: TEST\r\n\r\n' +
            ('"Ah, the ancient art of ancestral toot-massage. I am going to go see what Mom 2 is up to."\r\n\r\n' if i==1 else 'Narration here.\r\n\r\n')
            for i in range(1,8))
        self.file.write_bytes(text.encode('utf-8'))
        self.hash = hashlib.sha256(self.file.read_bytes()).hexdigest()

    def test_speaker_requires_explicit_attribution(self):
        self.assertEqual(_speaker('"Hi, Rainee," Francine said.'),'francine')
        self.assertIsNone(_speaker('"Hi, Francine." Rainee looked away.'))
        self.assertIsNone(_speaker('"Hi," Francine said. "Hello," Roger replied.'))

    def test_processed_copy_preserves_prior_and_source_text(self):
        receipt = publish_processed_workspace(self.bundle,self.root/'workspace',self.file,expected_sha256=self.hash)
        store = TimelineStore(self.root/'workspace/timeline.sqlite')
        episode = store.get_episode('spring-break')
        self.assertEqual(episode['script'],self.file.read_bytes().decode('utf-8'))
        self.assertEqual(receipt['processed_scenes'],7)
        self.assertEqual(episode['head'],2)
        state = NotebookStore(store).open('spring-break')
        self.assertEqual(joined(state['blocks']),episode['script'])
        self.assertEqual(state['default_protection'],100)
        with store._connect() as c:
            self.assertIsNotNone(c.execute('SELECT 1 FROM revisions WHERE episode=? AND revision=1',('spring-break',)).fetchone())
            self.assertIsNotNone(c.execute('SELECT 1 FROM superseded_source_bindings WHERE episode=?',('spring-break',)).fetchone())
            self.assertIsNone(c.execute('SELECT 1 FROM imported_episode_sources WHERE episode=?',('spring-break',)).fetchone())
        with self.assertRaisesRegex(ValueError,'new processed-workspace'):
            publish_processed_workspace(self.bundle,self.root/'workspace',self.file,expected_sha256=self.hash)

    def test_mo2_graph_match_preserves_crlf_source(self):
        publish_processed_workspace(self.bundle,self.root/'workspace',self.file,expected_sha256=self.hash)
        root = self.root/'reference'
        target = root/'work/americandad/foxy_mo2_hybrid_novel.md'
        target.parent.mkdir(parents=True);target.write_bytes(self.file.read_bytes())
        graph_source = root/'story_graph/scenarios/foxy_mo2_dag.py'
        graph_source.parent.mkdir(parents=True)
        graph_source.write_text('fixture',encoding='utf-8')
        store = TimelineStore(self.root/'workspace/timeline.sqlite')
        with patch('story_graph.beat_map._REFERENCE_ROOT',root):
            graph = map_episode(store,'spring-break',2)['graph_evidence']
        self.assertEqual(graph['id'],'spring-break-mo2')
        self.assertEqual(graph['beat_count'],20)
        self.assertGreaterEqual(graph['matched_passages'],1)
        normalized = TimelineStore(self.root/'normalized.sqlite')
        normalized.add_starter_cards()
        normalized.save('spring-break',0,script=self.file.read_text(encoding='utf-8'),source_name='fixture')
        with patch('story_graph.beat_map._REFERENCE_ROOT',root):
            self.assertEqual(map_episode(normalized,'spring-break',1)['graph_evidence']['id'],'spring-break-mo2')

    def test_changed_manuscript_is_rejected_before_publication(self):
        self.file.write_bytes(self.file.read_bytes()+b'changed')
        with self.assertRaisesRegex(ValueError,'manuscript changed'):
            publish_processed_workspace(self.bundle,self.root/'workspace',self.file,expected_sha256=self.hash)
        self.assertFalse((self.root/'workspace').exists())

    def test_grouped_narrator_passages_masks_and_undo_on_isolated_workspace_copy(self):
        multi = ('# CHAPTER\r\n\r\n'
                 '### SCENE 1: TEST\r\n\r\n'
                 'Opening narrator beat.\r\n\r\nSecond narrator beat.\r\n\r\nThird narrator beat.\r\n\r\n'
                 '***\r\n\r\n'
                 '"Ah, the ancient art of ancestral toot-massage," Francine said.\r\n\r\n'
                 '### SCENE 2: NEXT\r\n\r\n' +
                 ''.join(f'### SCENE {i}: TEST\r\n\r\nNarration here.\r\n\r\n' for i in range(3,8)))
        self.file.write_bytes(multi.encode('utf-8'))
        self.hash = hashlib.sha256(self.file.read_bytes()).hexdigest()
        publish_processed_workspace(self.bundle,self.root/'workspace',self.file,expected_sha256=self.hash)
        ws_path = self.root/'workspace/timeline.sqlite'
        book = NotebookStore(TimelineStore(ws_path))
        state = book.open('spring-break')
        groups = json.loads(subprocess.check_output([
            'node','-e',
            "const fs=require('fs'),c=require('./tools/compose_blocks.js'),s=JSON.parse(fs.readFileSync(0,'utf8'));process.stdout.write(JSON.stringify(c.group(s.text,s.blocks).map(g=>({kind:g.kind,parts:g.parts.length,text:g.text,gap:g.gap}))));"
        ],input=json.dumps({'text':joined(state['blocks']),'blocks':state['blocks']}),text=True))
        self.assertEqual(''.join(g['text']+g['gap'] for g in groups),multi)
        self.assertEqual(groups[2]['kind'],'narrator')
        self.assertEqual(groups[2]['parts'],3)
        self.assertEqual(groups[3]['kind'],'separator')
        self.assertEqual(groups[4]['kind'],'character')
        # Protect across Second -> Third narrator paragraph boundary while editing Opening
        mask_start = multi.index('narrator beat.\r\n\r\nThird')
        mask_end = multi.index('Third narrator beat.') + len('Third')
        mask = {'id':'cross-para','start':mask_start,'end':mask_end,'value':75,'hard':False,'sha256':hashlib.sha256(multi[mask_start:mask_end].encode()).hexdigest()}
        unlocked = book.save('spring-break',state['revision'],state['timeline_revision'],state['blocks'],25,[mask])
        split_doc = multi.replace('Opening narrator beat.','Opening A.\r\n\r\nOpening B.')
        saved = book.save_document('spring-break',unlocked['revision'],unlocked['timeline_revision'],split_doc,{'nodes':[],'edges':[]})
        self.assertGreater(len(saved['blocks']),len(state['blocks']))
        self.assertEqual(len(saved['masks']),1)
        reloaded = NotebookStore(TimelineStore(ws_path)).open('spring-break')
        self.assertEqual(joined(reloaded['blocks']),split_doc)
        undone = NotebookStore(TimelineStore(ws_path)).undo('spring-break',saved['revision'],saved['timeline_revision'])
        self.assertEqual(joined(undone['blocks']),multi)
        redone = NotebookStore(TimelineStore(ws_path)).redo('spring-break',undone['revision'],undone['timeline_revision'])
        self.assertEqual(joined(redone['blocks']),split_doc)
        real_mo2 = Path('imports/processed-reader-mo2-1e7372cebbcdae52/timeline.sqlite')
        if real_mo2.exists():
            iso = self.root/'real_mo2_isolated.sqlite'
            shutil.copy2(real_mo2,iso)
            mo2_store = TimelineStore(iso)
            mo2_book = NotebookStore(mo2_store)
            mo2_state = mo2_book.open('spring-break')
            mo2_text = joined(mo2_state['blocks'])
            mo2_groups = json.loads(subprocess.check_output([
                'node','-e',
                "const fs=require('fs'),c=require('./tools/compose_blocks.js'),s=JSON.parse(fs.readFileSync(0,'utf8'));const g=c.group(s.text,s.blocks);process.stdout.write(JSON.stringify({joined:c.join(g)===s.text,rawCount:s.blocks.length,groupCount:g.length,multiRuns:g.filter(x=>x.parts.length>1).length,firstMulti:[g.findIndex(x=>x.kind==='narrator' && x.parts.length>1),g.find(x=>x.kind==='narrator' && x.parts.length>1)?.text]}));"
            ],input=json.dumps({'text':mo2_text,'blocks':mo2_state['blocks']}),text=True))
            self.assertTrue(mo2_groups['joined'])
            self.assertLess(mo2_groups['groupCount'],mo2_groups['rawCount'])
            self.assertGreaterEqual(mo2_groups['multiRuns'],1)
            target = mo2_groups['firstMulti'][1]
            self.assertTrue(target)
            pos = mo2_text.index(target)
            eol = '\r\n\r\n' if '\r\n\r\n' in target else '\n\n'
            para_break = target.index(eol)
            # Cross-paragraph mask starting in first paragraph and ending in second paragraph while editing earlier text
            m_a = pos + max(0, para_break - 6)
            m_b = pos + para_break + len(eol) + min(8, len(target) - para_break - len(eol))
            m_obj = {'id':'mo2-cross','start':m_a,'end':m_b,'value':50,'hard':False,'sha256':hashlib.sha256(mo2_text[m_a:m_b].encode()).hexdigest()}
            mo2_unlocked = mo2_book.save('spring-break',mo2_state['revision'],mo2_state['timeline_revision'],mo2_state['blocks'],25,[m_obj])
            mo2_edited = mo2_text[:pos] + '[edited] ' + target[:para_break] + eol + 'Extra beat.' + eol + target[para_break+len(eol):] + mo2_text[pos+len(target):]
            mo2_saved = mo2_book.save_document('spring-break',mo2_unlocked['revision'],mo2_unlocked['timeline_revision'],mo2_edited,{'nodes':[],'edges':[]})
            mo2_reloaded = NotebookStore(TimelineStore(iso)).open('spring-break')
            self.assertEqual(joined(mo2_reloaded['blocks']),mo2_edited)
            mo2_undo = NotebookStore(TimelineStore(iso)).undo('spring-break',mo2_saved['revision'],mo2_saved['timeline_revision'])
            self.assertEqual(joined(mo2_undo['blocks']),mo2_text)

    def test_imported_workspace_keeps_unchanged_source_block_alignment_and_splits_group_on_bind(self):
        ext_source = self.root/'ext_source'
        (ext_source/'out/graphs').mkdir(parents=True)
        (ext_source/'narrative_composer/config/graph/characters').mkdir(parents=True)
        script = '# SPRING BREAK\r\n\r\nFirst narrator.\r\n\r\nSecond narrator.\r\n\r\nRAINEE\r\n\r\n“Hello there.”\r\n'
        (ext_source/'HOT_SCOOMP_COMPLETE_CHRONOLOGY.md').write_bytes(script.encode())
        graph = {'schema_version':1,'state_instances':[{'id':'first','entity':'rainee','state_id':'rainee.state.base','at':{'line':7},'source':'explicit','evidence':'RAINEE'}],
                 'transform_instances':[],'edges':[],'canon_leaks':[],'unresolved_cues':[]}
        chain = {'schema_version':1,'nodes':[{'type':'text_source','params':{'text':script.replace('\r\n','\n')}}]}
        report = {'discoveries':{'entities':[]},'violations':[]}
        definition = {'entity_id':'rainee','display_name':'Rainee','base_state':'base','aliases':['RAINEE'],'states':[],'transforms':[]}
        for rel,data in [('out/graphs/master.graph.json',graph),('out/graphs/master.chain.json',chain),
                         ('out/graphs/master.report.json',report),('narrative_composer/config/graph/characters/rainee.json',definition)]:
            (ext_source/rel).write_text(json.dumps(data),encoding='utf-8')
        bundle = publish_bundle(ext_source,self.root/'ext_bundles')
        publish_workspace(bundle,self.root/'ext_workspace')
        store = TimelineStore(self.root/'ext_workspace/timeline.sqlite')
        book = NotebookStore(store)
        state = book.open('spring-break')
        blocks = state['blocks']
        blocks[1]['kind'] = 'narrator';blocks[2]['kind'] = 'narrator'
        unlocked = book.save('spring-break',state['revision'],state['timeline_revision'],blocks,25,[])
        ep_graph = store.get_episode('spring-break')['graph']
        ep_text = joined(unlocked['blocks'])
        edited = ep_text.replace('First narrator.','First A.\r\n\r\nFirst B.')
        saved = book.save_document('spring-break',unlocked['revision'],unlocked['timeline_revision'],edited,ep_graph)
        self.assertEqual(saved['blocks'][2]['source'],{'split_from':blocks[1]['source']})
        rainee_offset = edited.index('RAINEE')
        with store._connect() as c:
            rev = store.get_episode('spring-break')
            raw_graph = c.execute('SELECT graph FROM revisions WHERE episode=? AND revision=?',('spring-break',rev['head'])).fetchone()['graph']
            snap = source_snapshot(c,'spring-break',rev['head'],rev['script'],hashlib.sha256(raw_graph.encode('utf-8')).hexdigest(),rainee_offset,rainee_offset+6)
        self.assertEqual(snap['alignment'],'unchanged-source-block')
        # Bind second narrator sub-block to Rainee and verify group splits cleanly
        second_narr_id = saved['blocks'][3]['id']
        bound = book.bind_speaker('spring-break',saved['revision'],saved['timeline_revision'],second_narr_id,'rainee','rainee')
        grouped_after = json.loads(subprocess.check_output([
            'node','-e',
            "const fs=require('fs'),c=require('./tools/compose_blocks.js'),s=JSON.parse(fs.readFileSync(0,'utf8'));process.stdout.write(JSON.stringify(c.group(s.text,s.blocks).map(g=>({kind:g.kind,speaker:g.speaker,parts:g.parts.length}))));"
        ],input=json.dumps({'text':joined(bound['blocks']),'blocks':bound['blocks']}),text=True))
        self.assertEqual(grouped_after[1]['kind'],'narrator')
        self.assertEqual(grouped_after[2]['speaker'],'rainee')
        # Merge earlier narrator blocks back together and preserve merged_sources
        merged_saved = book.save_document('spring-break',bound['revision'],bound['timeline_revision'],
                                          edited.replace('First A.\r\n\r\nFirst B.','Merged A.'),ep_graph)
        self.assertEqual(merged_saved['blocks'][1]['source'],{'merged_sources':[blocks[1]['source'],{'split_from':blocks[1]['source']}]})
        # Multi-id bind_speaker across remaining Rainee group
        rainee_ids = [b['id'] for b in merged_saved['blocks'] if b.get('speaker') == 'rainee']
        if len(rainee_ids) > 1:
            rebound = book.bind_speaker('spring-break',merged_saved['revision'],merged_saved['timeline_revision'],rainee_ids,'rainee','rainee')
            self.assertEqual(rebound['revision'],merged_saved['revision']+1)


if __name__ == '__main__': unittest.main()
