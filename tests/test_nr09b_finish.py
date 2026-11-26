import json
import subprocess
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from http.server import ThreadingHTTPServer

from prose_engine.notebook import _blocks, joined, NotebookStore, digest
from story_graph.episode_timeline import TimelineStore


class FinishNotebookTests(unittest.TestCase):
    def test_timeline_library_save_cannot_disable_notebook_guard(self):
        with tempfile.TemporaryDirectory() as tmp:
            store=TimelineStore(Path(tmp)/'timeline.sqlite');store.add_starter_cards()
            store.save('spring-break',0,script='A quiet room.',source_name='fixture')
            book=NotebookStore(store);state=book.open('spring-break')
            for option in ({},{'reject_notebook_script':False},{'reject_notebook_script':True}):
                with self.assertRaisesRegex(ValueError,'notebook protection'):
                    store.save('spring-break',1,script='Changed text.',source_name='fixture',**option)
                self.assertEqual(store.get_episode('spring-break')['head'],1)
                self.assertEqual(store.get_episode('spring-break')['script'],'A quiet room.')
            with self.assertRaisesRegex(ValueError,'notebook protection'):
                store.save('spring-break',1,script='A quiet room.',source_name='different-source')
            self.assertEqual(store.get_episode('spring-break')['source_name'],'fixture')
            graph={'nodes':[{'id':'a'}],'edges':[]}
            self.assertEqual(store.save('spring-break',1,graph=graph),2)
            self.assertTrue(book.open('spring-break')['stale'])
            synced=book.sync('spring-break',state['revision'],2)
            self.assertEqual(synced['timeline_revision'],2)

    def test_crlf_is_not_a_blank_line_and_anchors_are_lossless(self):
        text='Narration one.\r\nStill narration.\nAnother line.\r\n\r\nFRANCINE: hello.'
        blocks=_blocks(text,'fixture',3)
        self.assertEqual(len(blocks),2);self.assertEqual(joined(blocks),text)
        self.assertEqual(blocks[0]['text'],'Narration one.\r\nStill narration.\nAnother line.\r\n\r\n')
        self.assertEqual(blocks[1]['source']['start'],len(blocks[0]['text']))

    def test_individual_edit_preserves_unmodified_mixed_endings(self):
        js=r'''const c=require('./tools/compose_blocks.js');
const source='one\r\ntwo\nthree\rfour';
if(c.applyNormalizedEdit(source,'one\ntwo!\nthree\nfour','\r\n')!=='one\r\ntwo!\nthree\rfour')throw Error('mixed line endings changed');
if(c.applyNormalizedEdit(source,'one\ntwo\nthree\nfour','\r\n')!==source)throw Error('no-op altered source');'''
        result=subprocess.run(['node','-e',js],capture_output=True,text=True,encoding='utf-8',timeout=15)
        self.assertEqual(result.returncode,0,result.stderr)

    def test_atomic_editor_save_guards_exact_masks_and_graph(self):
        with tempfile.TemporaryDirectory() as tmp:
            store=TimelineStore(Path(tmp)/'timeline.sqlite');store.add_starter_cards()
            text='A quiet room.\r\nNext line.\n\r\nFRANCINE: Hello.'
            store.save('spring-break',0,script=text,source_name='fixture')
            book=NotebookStore(store);state=book.open('spring-break');state['blocks'][0]['kind']='narrator';state['blocks'][1].update(kind='character',speaker='francine')
            start=text.index('quiet');mask={'id':'exact','start':start,'end':start+5,'value':100,'hard':True,'sha256':digest('quiet')}
            state=book.save('spring-break',0,1,state['blocks'],25,[mask])
            graph={'nodes':[{'id':'a','type':'beat','data':{'beat':1}}],'edges':[]}
            with self.assertRaises(ValueError):book.save_document('spring-break',state['revision'],1,text.replace('quiet','noisy'),graph)
            self.assertEqual(store.get_episode('spring-break')['head'],1);self.assertEqual(store.get_episode('spring-break')['script'],text)
            self.assertEqual(book.open('spring-break')['revision'],state['revision'])
            revised=text.replace('Next line','New line')
            saved=book.save_document('spring-break',state['revision'],1,revised,graph)
            self.assertEqual(saved['timeline_revision'],2);self.assertEqual(joined(saved['blocks']),revised)
            self.assertEqual(saved['blocks'][1]['speaker'],'francine');self.assertEqual(store.get_episode('spring-break')['graph'],graph)
            self.assertEqual(saved['masks'][0]['sha256'],mask['sha256'])
            with self.assertRaises(ValueError):book.save_document('spring-break',state['revision'],1,text,graph)
            self.assertEqual(store.get_episode('spring-break')['script'],revised)

    def test_timeline_http_cannot_bypass_notebook_protection(self):
        from tools.studio_ui import StudioRequestHandler
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'timeline.sqlite';store=TimelineStore(path);store.add_starter_cards()
            store.save('spring-break',0,script='A quiet room.',source_name='fixture')
            book=NotebookStore(store);state=book.open('spring-break');book.save('spring-break',0,1,state['blocks'],25,[])
            server=ThreadingHTTPServer(('127.0.0.1',0),StudioRequestHandler);server.timeline_path=path;server.timeline_only=True
            thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start();base='http://127.0.0.1:'+str(server.server_port)
            req={'action':'save','id':'spring-break','expected_revision':1,'script':'Changed text.','source_name':'fixture'}
            request=urllib.request.Request(base+'/api/timeline',data=json.dumps(req).encode(),headers={'Content-Type':'application/json','Origin':base})
            try:
                with self.assertRaises(urllib.error.HTTPError) as err:urllib.request.urlopen(request)
                self.assertEqual(err.exception.code,400);self.assertEqual(store.get_episode('spring-break')['head'],1)
                self.assertEqual(store.get_episode('spring-break')['script'],'A quiet room.')
            finally:server.shutdown();server.server_close();thread.join()

    def test_notebook_http_save_is_atomic_for_protected_text(self):
        from tools.studio_ui import StudioRequestHandler
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'timeline.sqlite';store=TimelineStore(path);store.add_starter_cards()
            store.save('spring-break',0,script='A quiet room.',source_name='fixture')
            book=NotebookStore(store);state=book.open('spring-break')
            mask={'id':'exact','start':2,'end':7,'value':100,'hard':True,'sha256':digest('quiet')}
            state=book.save('spring-break',0,1,state['blocks'],25,[mask])
            server=ThreadingHTTPServer(('127.0.0.1',0),StudioRequestHandler);server.timeline_path=path;server.timeline_only=True
            thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start();base='http://127.0.0.1:'+str(server.server_port)
            def send(text):
                payload={'action':'save-document','episode':'spring-break','revision':state['revision'],'timeline_revision':1,'text':text,'graph':{'nodes':[],'edges':[]}}
                request=urllib.request.Request(base+'/api/notebook',data=json.dumps(payload).encode(),headers={'Content-Type':'application/json','Origin':base})
                return urllib.request.urlopen(request)
            try:
                with self.assertRaises(urllib.error.HTTPError) as err:send('A noisy room.')
                self.assertEqual(err.exception.code,400);self.assertEqual(store.get_episode('spring-break')['head'],1)
                self.assertEqual(store.get_episode('spring-break')['script'],'A quiet room.')
                with send('A quiet room!') as response:self.assertEqual(json.load(response)['timeline_revision'],2)
                self.assertEqual(store.get_episode('spring-break')['script'],'A quiet room!')
            finally:server.shutdown();server.server_close();thread.join()

if __name__=='__main__':unittest.main()
