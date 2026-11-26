import json
import subprocess
import tempfile
import threading
import unittest
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

from prose_engine.notebook import DraftStore, NotebookStore, digest, joined, resolve
from prose_engine.scoped_service import execute_scoped
from story_graph.episode_timeline import TimelineStore


class FakeProvider:
    def __init__(self,text):self.text=text;self.calls=0
    def generate_rewrite(self,request,prompt):self.calls+=1;return self.text


class NotebookUiTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.path=Path(self.tmp.name)/'timeline.sqlite';self.timeline=TimelineStore(self.path);self.timeline.add_starter_cards()
        self.text='🕯 Rainee pauses e\u0301.\r\n\r\nFRANCINE: Did you hear that?'
        self.timeline.save('spring-break',0,script=self.text,source_name='fixture')
        self.book=NotebookStore(self.timeline);state=self.book.open('spring-break');blocks=state['blocks']
        blocks[0]['kind']='narrator';blocks[1].update(kind='character',speaker='francine')
        self.state=self.book.save('spring-break',0,1,blocks,25,[])
        self.ids=[b['id'] for b in self.state['blocks']]

    def test_saved_writing_undo_redo_survives_reload_and_new_edit_clears_redo(self):
        first=self.text.replace('pauses','waits')
        graph={'nodes':[{'id':'example','title':'Example'}],'edges':[]}
        state=self.book.save_document('spring-break',self.state['revision'],self.state['timeline_revision'],first,graph)
        second=first.replace('hear','notice')
        state=self.book.save_document('spring-break',state['revision'],state['timeline_revision'],second,graph)
        state=NotebookStore(TimelineStore(self.path)).undo('spring-break',state['revision'],state['timeline_revision'])
        self.assertEqual(joined(state['blocks']),first)
        state=self.book.undo('spring-break',state['revision'],state['timeline_revision'])
        self.assertEqual(joined(state['blocks']),self.text)
        self.assertEqual(self.timeline.get_episode('spring-break')['graph'],{'nodes':[],'edges':[]})
        state=self.book.redo('spring-break',state['revision'],state['timeline_revision'])
        self.assertEqual(joined(state['blocks']),first);self.assertEqual(self.timeline.get_episode('spring-break')['graph'],graph)
        state=self.book.redo('spring-break',state['revision'],state['timeline_revision'])
        self.assertEqual(joined(state['blocks']),second)
        state=self.book.undo('spring-break',state['revision'],state['timeline_revision'])
        new=first.replace('hear','listen')
        state=self.book.save_document('spring-break',state['revision'],state['timeline_revision'],new,graph)
        with self.assertRaisesRegex(ValueError,'redo'):self.book.redo('spring-break',state['revision'],state['timeline_revision'])

    def test_author_can_undo_a_saved_edit_at_default_full_protection(self):
        self.timeline.create_episode('empty','Empty','main',40)
        book=NotebookStore(self.timeline);state=book.open('empty')
        state=book.append_block('empty',state['revision'],state['timeline_revision'],'narrator')
        state=book.save_document('empty',state['revision'],state['timeline_revision'],'New text',{'nodes':[],'edges':[]})
        state=book.undo('empty',state['revision'],state['timeline_revision'])
        self.assertEqual(joined(state['blocks']),'')
        state=book.redo('empty',state['revision'],state['timeline_revision'])
        self.assertEqual(joined(state['blocks']),'New text')

    def test_unicode_crlf_and_grapheme_boundaries(self):
        code=r'''const c=require('./tools/compose_blocks.js');
const text='🕯 Rainee e\u0301.\r\n\r\nFRANCINE: Hi';const blocks=c.split(text);
if(c.join(blocks)!==text||blocks.length!==2)throw Error('lossy split');
if(c.offset(blocks,1,0)!==Array.from('🕯 Rainee e\u0301.\r\n\r\n').length)throw Error('wrong CRLF or emoji offset');
let rejected=false;try{c.offset(blocks,0,1)}catch(e){rejected=true}if(!rejected)throw Error('split surrogate accepted');
if(c.graphemeBoundary('e\u0301',1)||c.graphemeBoundary('\r\n',1)||!c.graphemeBoundary('🕯',1))throw Error('bad grapheme boundary');'''
        result=subprocess.run(['node','-e',code],capture_output=True,text=True,encoding='utf-8',timeout=15)
        self.assertEqual(result.returncode,0,result.stderr)

    def test_unchanged_mixed_line_endings_survive_edit(self):
        code=r'''const c=require('./tools/compose_blocks.js');
const source='one\r\ntwo\nthree\rfour';
const result=c.applyNormalizedEdit(source,'one\ntwo!\nthree\nfour','\r\n');
if(result!=='one\r\ntwo!\nthree\rfour')throw Error(JSON.stringify(result));'''
        result=subprocess.run(['node','-e',code],capture_output=True,text=True,encoding='utf-8',timeout=15)
        self.assertEqual(result.returncode,0,result.stderr)

    def test_cross_block_masks_overlap_reload_and_no_zero(self):
        end=self.text.index('Did')+3;start=self.text.index('Rainee')
        masks=[{'id':'cross','start':start,'end':end,'value':75,'hard':False,'sha256':digest(self.text[start:end])},
               {'id':'exact','start':self.text.index('FRANCINE'),'end':end,'value':100,'hard':False,'sha256':digest(self.text[self.text.index('FRANCINE'):end])}]
        saved=self.book.save('spring-break',1,1,self.state['blocks'],25,masks)
        reopened=NotebookStore(TimelineStore(self.path)).open('spring-break')
        self.assertEqual(reopened['masks'],masks);effective=resolve(self.text,25,masks)
        self.assertTrue(any(x['value']==100 and x['start']==self.text.index('FRANCINE') for x in effective))
        self.assertTrue(any(x['value']==75 for x in effective))
        with self.assertRaisesRegex(ValueError,'zero'):self.book.save('spring-break',saved['revision'],1,saved['blocks'],0,masks)

    def test_api_rejects_splitting_combining_character_or_crlf(self):
        for pos in (self.text.index('\u0301'),self.text.index('\r\n')+1):
            mask={'id':'split','start':0,'end':pos,'value':75,'hard':False,'sha256':digest(self.text[:pos])}
            with self.subTest(pos=pos),self.assertRaisesRegex(ValueError,'complete characters'):
                self.book.save('spring-break',1,1,self.state['blocks'],25,[mask])

    def test_ambiguous_repeated_block_boundary_is_rejected(self):
        from prose_engine.notebook import _replace_blocks
        blocks=[{'text':'A\n\n'},{'text':'B\n\n'},{'text':'C'}]
        with self.assertRaisesRegex(ValueError,'block identities'):
            _replace_blocks(blocks,0,len(joined(blocks)),'X\n\nY\n\nZ')
        overlapping=[{'text':'aa'},{'text':'aa'}]
        with self.assertRaisesRegex(ValueError,'block identities'):
            _replace_blocks(overlapping,0,4,'baaa')

    def test_cross_block_draft_and_undo_preserve_identities(self):
        start=self.text.index('Rainee');end=self.text.index('hear')+4
        mask={'id':'cross','start':start,'end':end,'value':100,'hard':False,'sha256':digest(self.text[start:end])}
        state=self.book.save('spring-break',1,1,self.state['blocks'],25,[mask])
        provider=FakeProvider(self.text[start:end])
        req={'episode':'spring-break','beat':0,'revision':1,'start':start,'end':end,'provider':'codex-session'}
        result=execute_scoped(self.timeline,'generate',req,provider_factory=lambda:provider)
        applied=DraftStore(self.book).use('spring-break','main',result['draft_id'],state['revision'],1)
        self.assertEqual(joined(applied['blocks']),self.text);self.assertEqual([b['id'] for b in applied['blocks']],self.ids)
        self.assertEqual(applied['blocks'][0]['kind'],'narrator');self.assertEqual(applied['blocks'][1]['speaker'],'francine')
        restored=self.book.undo('spring-break',applied['revision'],applied['timeline_revision'])
        self.assertEqual([b['id'] for b in restored['blocks']],self.ids);self.assertEqual(restored['blocks'][1]['speaker'],'francine')
        self.assertEqual(provider.calls,0)

    def test_changed_fake_draft_preserves_cross_block_freeze_and_identity(self):
        start=self.text.index('e\u0301');end=self.text.index('FRANCINE')+len('FRANCINE')
        mask={'id':'bridge','start':start,'end':end,'value':100,'hard':False,'sha256':digest(self.text[start:end])}
        state=self.book.save('spring-break',1,1,self.state['blocks'],25,[mask])
        replacement=self.text.replace('pauses','waits').replace('hear that','notice that')
        provider=FakeProvider(replacement)
        req={'episode':'spring-break','beat':0,'revision':1,'start':0,'end':len(self.text),'provider':'codex-session'}
        result=execute_scoped(self.timeline,'generate',req,provider_factory=lambda:provider)
        self.assertEqual(result['status'],'PROPOSED')
        applied=DraftStore(self.book).use('spring-break','main',result['draft_id'],state['revision'],1)
        self.assertEqual(joined(applied['blocks']),replacement);self.assertEqual([b['id'] for b in applied['blocks']],self.ids)
        self.assertEqual(applied['blocks'][1]['speaker'],'francine');self.assertEqual(applied['masks'][0]['sha256'],mask['sha256'])
        restored=self.book.undo('spring-break',applied['revision'],applied['timeline_revision'])
        self.assertEqual(joined(restored['blocks']),self.text);self.assertEqual(restored['blocks'][1]['speaker'],'francine')

    def test_cross_block_rewrite_preserves_boundaries_or_fails_safely(self):
        replacement=self.text.replace('pauses','waits').replace('hear','notice')
        updated=self.book.edit_text('spring-break',1,1,0,len(self.text),replacement)
        self.assertEqual(joined(updated['blocks']),replacement)
        self.assertEqual([b['id'] for b in updated['blocks']],self.ids);self.assertEqual(updated['blocks'][1]['speaker'],'francine')
        self.book.undo('spring-break',updated['revision'],updated['timeline_revision'])
        before=self.book.open('spring-break')
        with self.assertRaisesRegex(ValueError,'block identities'):
            self.book.edit_text('spring-break',before['revision'],before['timeline_revision'],0,len(self.text),'Entirely different replacement.')
        self.assertEqual(joined(self.book.open('spring-break')['blocks']),self.text)

    def test_hard_lock_cannot_be_removed_or_softened(self):
        start=self.text.index('FRANCINE');mask={'id':'hard','start':start,'end':len(self.text),'value':100,'hard':True,'sha256':digest(self.text[start:])}
        saved=self.book.save('spring-break',1,1,self.state['blocks'],25,[mask])
        with self.assertRaisesRegex(ValueError,'hard lock'):
            self.book.save('spring-break',saved['revision'],1,saved['blocks'],25,[])
        with self.assertRaises(ValueError):
            self.book.edit_text('spring-break',saved['revision'],1,start,len(self.text),'Changed dialogue')

    def test_inactive_mask_can_be_cleared_and_undo_restores_it(self):
        start=self.text.index('pauses');end=start+len('pauses')
        mask={'id':'soft','start':start,'end':end,'value':75,'hard':False,'sha256':digest(self.text[start:end])}
        saved=self.book.save('spring-break',1,1,self.state['blocks'],25,[mask])
        edited=self.book.edit_text('spring-break',saved['revision'],1,start,end,'waits')
        self.assertEqual(edited['stale_masks'][0]['id'],'soft');self.assertEqual(edited['masks'],[])
        cleared=self.book.dismiss_stale_mask('spring-break',edited['revision'],edited['timeline_revision'],'soft')
        self.assertEqual(cleared['stale_masks'],[])
        restored=self.book.undo('spring-break',cleared['revision'],cleared['timeline_revision'])
        self.assertEqual(restored['stale_masks'][0]['id'],'soft')

    def test_studio_endpoint_clears_only_the_selected_inactive_mask(self):
        from tools.studio_ui import StudioRequestHandler
        start=self.text.index('pauses');end=start+len('pauses')
        mask={'id':'soft','start':start,'end':end,'value':75,'hard':False,'sha256':digest(self.text[start:end])}
        saved=self.book.save('spring-break',1,1,self.state['blocks'],25,[mask])
        edited=self.book.edit_text('spring-break',saved['revision'],1,start,end,'waits')
        server=ThreadingHTTPServer(('127.0.0.1',0),StudioRequestHandler);server.timeline_path=self.path;server.timeline_only=True
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start();base='http://127.0.0.1:'+str(server.server_port)
        body={'action':'dismiss-stale','episode':'spring-break','revision':edited['revision'],'timeline_revision':edited['timeline_revision'],'mask':'soft'}
        request=urllib.request.Request(base+'/api/notebook',data=json.dumps(body).encode(),headers={'Content-Type':'application/json','Origin':base})
        try:
            with urllib.request.urlopen(request) as response:result=json.load(response)
            self.assertEqual(result['stale_masks'],[]);self.assertEqual(result['revision'],edited['revision']+1)
        finally:server.shutdown();server.server_close();thread.join()

    def test_checked_theme_assets_and_cross_block_controls_present(self):
        from tools.studio_ui import HTML_TEMPLATE
        self.assertIn('value="racing"',HTML_TEMPLATE);self.assertIn('value="classic"',HTML_TEMPLATE)
        self.assertIn('id="selectionStart"',HTML_TEMPLATE);self.assertIn('id="selectionEnd"',HTML_TEMPLATE)
        self.assertIn('id="crossSelectionPage"',HTML_TEMPLATE);self.assertIn('id="selectionCapture"',HTML_TEMPLATE)
        self.assertIn('id="maskUpdate"',HTML_TEMPLATE);self.assertIn('id="maskRemove"',HTML_TEMPLATE)

    def test_compose_blocks_groups_consecutive_narrator_and_same_speaker_without_loss(self):
        code=r'''const assert=require('assert');const c=require('./tools/compose_blocks.js');
const text=[
  '🕯 First narrator e\u0301.',
  'Second narrator line.',
  '***',
  '# SCENE 2: HALLWAY',
  'RAINEE: Base form one.',
  'RAINEE: Changed form two.',
  'ROGER: Line one.',
  'ROGER: Line two.',
  '"Unattributed quote one."',
  '"Unattributed quote two."'
].join('\r\n\r\n');
const nb=[
  {id:'n1',kind:'narrator',speaker:null,form:null,text:'🕯 First narrator e\u0301.\r\n\r\n'},
  {id:'n2',kind:'narrator',speaker:null,form:null,text:'Second narrator line.\r\n\r\n'},
  {id:'sep',kind:'narrator',speaker:null,form:null,text:'***\r\n\r\n'},
  {id:'scn',kind:'scene-heading',speaker:null,form:null,text:'# SCENE 2: HALLWAY\r\n\r\n'},
  {id:'r1',kind:'character',speaker:'rainee',form:'rainee',text:'RAINEE: Base form one.\r\n\r\n'},
  {id:'r2',kind:'character',speaker:'rainee',form:'rainee_alt',text:'RAINEE: Changed form two.\r\n\r\n'},
  {id:'g1',kind:'character',speaker:'roger',form:'roger',text:'ROGER: Line one.\r\n\r\n'},
  {id:'g2',kind:'character',speaker:'roger',form:'roger',text:'ROGER: Line two.\r\n\r\n'},
  {id:'q1',kind:'unresolved',speaker:null,form:null,text:'"Unattributed quote one."\r\n\r\n'},
  {id:'q2',kind:'unresolved',speaker:null,form:null,text:'"Unattributed quote two."'}
];
const groups=c.group(text,nb);
assert.strictEqual(c.join(groups),text);
assert.deepStrictEqual(groups.map(g=>[g.kind,g.parts.length]),[
  ['narrator',2],
  ['separator',1],
  ['scene-heading',1],
  ['character',1],
  ['character',1],
  ['character',2],
  ['character',1],
  ['character',1]
]);
assert.strictEqual(c.blockAtOffset(groups[0],0).item.id,'n1');
const secondStart=Array.from('🕯 First narrator e\u0301.\r\n\r\n').length;
assert.strictEqual(c.blockAtOffset(groups[0],secondStart).item.id,'n2');
assert.strictEqual(c.blockAtOffset(groups[5],0).item.id,'g1');
const g2Start=Array.from('ROGER: Line one.\r\n\r\n').length;
assert.strictEqual(c.blockAtOffset(groups[5],g2Start).item.id,'g2');
const appendedText='Alpha.\r\n\r\n';
const appendedNb=[
  {id:'a1',kind:'narrator',speaker:null,form:null,text:'Alpha.\r\n\r\n'},
  {id:'a2',kind:'narrator',speaker:null,form:null,text:''}
];
const appendedGroups=c.group(appendedText,appendedNb);
assert.strictEqual(appendedGroups.length,1);
assert.strictEqual(c.blockAtOffset(appendedGroups[0],0).item.id,'a1');
assert.strictEqual(c.blockAtOffset(appendedGroups[0],Array.from(appendedText).length).item.id,'a2');
'''
        subprocess.run(['node','-e',code],check=True)

    def test_grouped_narrator_edit_split_merge_and_cross_speaker_rejection_with_undo(self):
        self.timeline.create_episode('grouped','Grouped','main',15)
        initial='One.\r\n\r\nTwo.\r\n\r\nFRANCINE: Hold on.\r\n\r\nThree.'
        self.timeline.save('grouped',0,script=initial,source_name='fixture')
        book=NotebookStore(self.timeline);state=book.open('grouped');blocks=state['blocks']
        blocks[0]['kind']='narrator';blocks[1]['kind']='narrator'
        blocks[2].update(kind='character',speaker='francine')
        blocks[3]['kind']='narrator'
        b0_source=blocks[0]['source'];b1_source=blocks[1]['source'];b2_id=blocks[2]['id'];b3_id=blocks[3]['id']
        mask_start=initial.index('Three.');mask_end=mask_start+len('Three.')
        freeze={'id':'three-lock','start':mask_start,'end':mask_end,'value':100,'hard':False,'sha256':digest(initial[mask_start:mask_end])}
        state=book.save('grouped',state['revision'],state['timeline_revision'],blocks,25,[freeze])
        graph={'nodes':[],'edges':[]}
        # 1. Word edit in paragraph 1 preserves all block IDs and sources
        edited_text=initial.replace('One.','One updated.')
        rev1=book.save_document('grouped',state['revision'],state['timeline_revision'],edited_text,graph)
        self.assertEqual([b['id'] for b in rev1['blocks']],[b['id'] for b in state['blocks']])
        self.assertEqual(rev1['blocks'][0]['source'],b0_source)
        # 2. Split inside grouped Narrator creates derived block with split_from provenance
        split_text=edited_text.replace('One updated.','One part A.\r\n\r\nOne part B.')
        rev2=book.save_document('grouped',rev1['revision'],rev1['timeline_revision'],split_text,graph)
        self.assertEqual(len(rev2['blocks']),5)
        self.assertEqual(rev2['blocks'][0]['id'],blocks[0]['id'])
        self.assertEqual(rev2['blocks'][1]['source'],{'split_from':b0_source})
        self.assertEqual(rev2['blocks'][2]['id'],blocks[1]['id'])
        self.assertEqual(rev2['blocks'][3]['id'],b2_id)
        self.assertEqual(rev2['blocks'][4]['id'],b3_id)
        # 3. Merge within grouped Narrator records merged_sources
        merged_text='Merged A and Two.\r\n\r\nFRANCINE: Hold on.\r\n\r\nThree.'
        rev3=book.save_document('grouped',rev2['revision'],rev2['timeline_revision'],merged_text,graph)
        self.assertEqual(len(rev3['blocks']),3)
        self.assertEqual(rev3['blocks'][0]['source'],{'merged_sources':[b0_source,{'split_from':b0_source},b1_source]})
        self.assertEqual(rev3['blocks'][1]['id'],b2_id)
        self.assertEqual(rev3['blocks'][2]['id'],b3_id)
        # 4. Heterogeneous boundary loss across Narrator -> Francine still fails closed
        with self.assertRaisesRegex(ValueError,'block identities'):
            book.save_document('grouped',rev3['revision'],rev3['timeline_revision'],'Merged A and Two.FRANCINE: Hold on.\r\n\r\nThree.',graph)
        # 5. Multi-step undo/redo across database reload
        reloaded=NotebookStore(TimelineStore(self.path))
        u1=reloaded.undo('grouped',rev3['revision'],rev3['timeline_revision'])
        self.assertEqual(joined(u1['blocks']),split_text);self.assertEqual(len(u1['blocks']),5)
        u2=reloaded.undo('grouped',u1['revision'],u1['timeline_revision'])
        self.assertEqual(joined(u2['blocks']),edited_text);self.assertEqual(len(u2['blocks']),4)
        r1=reloaded.redo('grouped',u2['revision'],u2['timeline_revision'])
        self.assertEqual(joined(r1['blocks']),split_text);self.assertEqual(len(r1['blocks']),5)

    def test_studio_grouped_composer_css_and_inline_js_valid(self):
        import re
        from tools.studio_ui import HTML_TEMPLATE
        self.assertIn('ComposeBlocks.group(',HTML_TEMPLATE)
        self.assertIn('ComposeBlocks.blockAtOffset(',HTML_TEMPLATE)
        self.assertIn('overflow-y:hidden;resize:none',HTML_TEMPLATE)
        self.assertNotIn('Math.min(14,',HTML_TEMPLATE)
        self.assertNotIn('Math.min(600,',HTML_TEMPLATE)
        scripts=re.findall(r'<script[^>]*>([\s\S]*?)</script>',HTML_TEMPLATE)
        self.assertGreaterEqual(len(scripts),1)
        script_path=Path(self.tmp.name)/'studio_inline.js'
        script_path.write_text('\n'.join(scripts),encoding='utf-8')
        subprocess.run(['node','--check',str(script_path)],check=True)

    def test_extracted_studio_assets_and_stale_mask_popover_controls(self):
        from http.server import ThreadingHTTPServer
        import threading
        import urllib.request
        from tools.studio_ui import HTML_TEMPLATE, REPO_ROOT, StudioRequestHandler

        studio_ui_path=REPO_ROOT/'tools'/'studio_ui.py'
        self.assertLess(len(studio_ui_path.read_text(encoding='utf-8').splitlines()),1200)
        for asset_name in ('studio_styles.css','studio_body.html','studio_client.js','studio_default_graph.json'):
            asset_path=REPO_ROOT/'tools'/'assets'/asset_name
            self.assertTrue(asset_path.is_file(),asset_name)
            self.assertGreater(len(asset_path.read_text(encoding='utf-8').strip()),0,asset_name)
        for token in ('id="highlighterStale"','id="maskStaleSection"','id="maskStaleList"','dismissStaleMaskById',"new URLSearchParams(location.search).get('theme')"):
            self.assertIn(token,HTML_TEMPLATE)

        server=ThreadingHTTPServer(('127.0.0.1',0),StudioRequestHandler)
        server.timeline_path=Path(self.tmp.name)/'timeline.sqlite'
        thread=threading.Thread(target=server.serve_forever,daemon=True)
        thread.start()
        try:
            base=f'http://127.0.0.1:{server.server_address[1]}'
            css=urllib.request.urlopen(f'{base}/assets/studio_styles.css').read().decode('utf-8')
            self.assertIn('.mask-stale',css)
            js=urllib.request.urlopen(f'{base}/assets/studio_client.js').read().decode('utf-8')
            self.assertIn('dismissStaleMaskById',js)
            graph=json.loads(urllib.request.urlopen(f'{base}/assets/studio_default_graph.json').read().decode('utf-8'))
            self.assertIn('nodes',graph);self.assertIn('connections',graph)
            ref_html=urllib.request.urlopen(f'{base}/racing-comparison').read().decode('utf-8')
            self.assertIn('Running sample editor',ref_html)
            themes_html=urllib.request.urlopen(f'{base}/racing-comparison?mode=themes').read().decode('utf-8')
            self.assertIn('/?episode=spring-break&theme=racing',themes_html);self.assertIn('/?episode=spring-break&theme=classic',themes_html)
            laws_html=urllib.request.urlopen(f'{base}/world-laws?theme=classic').read().decode('utf-8')
            self.assertIn('URLSearchParams',laws_html)
        finally:
            server.shutdown();server.server_close();thread.join()


if __name__=='__main__':unittest.main()
