import json
import subprocess
import tempfile
import threading
import unittest
import urllib.request
from html.parser import HTMLParser
from http.server import ThreadingHTTPServer
from pathlib import Path

from story_graph.episode_timeline import TimelineStore
from tests.test_nr09d_popup import Page
from tools.studio_ui import HTML_TEMPLATE, StudioRequestHandler


class Controls(HTMLParser):
    def __init__(self): super().__init__(); self.controls = {}
    def handle_starttag(self, tag, attrs):
        item = dict(attrs)
        if item.get('id'): self.controls[item['id']] = item


class WorkspaceTests(unittest.TestCase):
    def test_writer_sees_highlighter_while_legacy_administration_is_hidden(self):
        page = Controls(); page.feed(HTML_TEMPLATE)
        self.assertEqual(page.controls['highlighterTool']['aria-label'], 'Highlighter')
        self.assertIn('hidden', page.controls['highlighterMenu'])
        for name in ('legacyProtectionControls','legacyWorldLawControls','bookPermissionControls'):
            self.assertIn('hidden', page.controls[name])
        self.assertEqual(page.controls['openWorldLaws']['href'], '/world-laws')

    def test_world_law_page_uses_versioned_store_and_keeps_structured_checks(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'timeline.sqlite'; timeline = TimelineStore(path); timeline.add_starter_cards()
            server = ThreadingHTTPServer(('127.0.0.1', 0), StudioRequestHandler); server.timeline_path = path
            thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
            base = f'http://127.0.0.1:{server.server_port}'
            def post(payload):
                request = urllib.request.Request(base + '/api/world-laws', data=json.dumps(payload).encode(), headers={'Content-Type':'application/json','Origin':base})
                with urllib.request.urlopen(request) as response: return json.load(response)
            try:
                with urllib.request.urlopen(base + '/world-laws?episode=spring-break') as response:
                    page = Page(); page.feed(response.read().decode('utf-8-sig'))
                self.assertTrue({'lawName', 'lawStatement', 'lawForm', 'lawList'}.issubset(page.ids))
                script = Path(tmp) / 'world-laws.js'; script.write_text('\n'.join(page.scripts), encoding='utf-8')
                parsed = subprocess.run(['node','--check',str(script)],capture_output=True,text=True,timeout=15)
                self.assertEqual(parsed.returncode, 0, parsed.stderr)
                original = post({'action':'open'}); law = original['laws'][0]
                edited = dict(law, name='A renamed rule')
                changed = post({'action':'save','project':original['project_id'],'universe':original['universe_id'],'revision':original['revision'],'laws':[edited]})
                self.assertEqual(changed['laws'][0]['constraints'],law['constraints'])
                self.assertEqual(changed['laws'][0]['matcher'],law['matcher'])
                restored = post({'action':'undo','project':original['project_id'],'universe':original['universe_id'],'revision':changed['revision']})
                self.assertEqual(restored['laws'],original['laws'])
            finally:
                server.shutdown(); server.server_close(); thread.join()


if __name__ == '__main__': unittest.main()
