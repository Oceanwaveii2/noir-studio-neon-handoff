import json
import tempfile
import threading
import unittest
import urllib.request
import urllib.error
from unittest.mock import patch
from pathlib import Path
from http.server import ThreadingHTTPServer
from tools.studio_ui import StudioRequestHandler
from story_graph.episode_timeline import TimelineStore

class RecordingProvider:
    def __init__(self): self.prompts=[]
    def generate_rewrite(self,request,prompt): self.prompts.append(prompt); return 'A quiet room.'

class ScopedHttpTests(unittest.TestCase):
    def test_http_scoping_and_renderer(self):
        with tempfile.TemporaryDirectory() as tmp:
            store=TimelineStore(Path(tmp)/'timeline.sqlite'); store.add_starter_cards()
            store.save('spring-break',0,script='A quiet room.',source_name='fixture')
            store.add_event('future','tapped-out',1,'A glitter prank destroyed the makeup kit.',status='approved',permitted=True,source_id='fixture',reviewer='owner')
            server=ThreadingHTTPServer(('127.0.0.1',0),StudioRequestHandler); server.timeline_path=Path(tmp)/'timeline.sqlite'; server.timeline_only=True
            thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
            base='http://127.0.0.1:'+str(server.server_port); provider=RecordingProvider()
            def post(data):
                request=urllib.request.Request(base+'/api/scoped',data=json.dumps(data).encode(),headers={'Content-Type':'application/json','Origin':base})
                with urllib.request.urlopen(request) as response: return json.load(response)
            req={'episode':'spring-break','beat':4,'revision':1,'start':0,'end':len('A quiet room.')}
            try:
                for path in ('/api/state','/api/form-graph','/foxy_mo2_reader.html','/vendor/../studio_ui.py'):
                    with self.assertRaises(urllib.error.HTTPError) as blocked: urllib.request.urlopen(base+path)
                    self.assertEqual(blocked.exception.code,404)
                with urllib.request.urlopen(base+'/api/state?episode=spring-break') as response:
                    self.assertEqual(json.load(response)['script_text'],'A quiet room.')
                with patch('prose_engine.providers.primary_session.create_scoped_provider',return_value=provider):
                    result=post({**req,'action':'generate','provider':'codex-session'})
                self.assertEqual(result['status'],'PROPOSED')
                self.assertNotIn('glitter prank',provider.prompts[0])
                class ChangingProvider:
                    def generate_rewrite(self,request,prompt):
                        store.add_event('later-change','tapped-out',2,'A new future event.',status='approved',permitted=True,source_id='fixture',reviewer='owner')
                        return 'A quiet room.'
                with patch('prose_engine.providers.primary_session.create_scoped_provider',return_value=ChangingProvider()):
                    with self.assertRaises(urllib.error.HTTPError): post({**req,'action':'generate','provider':'codex-session'})
                self.assertEqual(post({**req,'action':'retrieve','query':'glitter'})['results'],[])
                self.assertNotIn('glitter prank',json.dumps(post({**req,'action':'export'})))
                self.assertTrue(post({**req,'action':'validate','claims':[{'kind':'active_form','subject':'haley','value':'awakened_haley_fox'}]})['issues'])
                with self.assertRaises(urllib.error.HTTPError): post({**req,'action':'export','revision':0})
                with self.assertRaises(urllib.error.HTTPError): post({**req,'action':'generate','provider':'local'})
            finally:
                server.shutdown();server.server_close();thread.join()
