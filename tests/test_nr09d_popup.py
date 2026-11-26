"""Focused guards for the rebuilt Studio and timeline interfaces."""
from collections import Counter
from html.parser import HTMLParser
import json
from pathlib import Path
import subprocess
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

from prose_engine.notebook import NotebookStore
from story_graph.episode_timeline import TimelineStore
from tools.studio_ui import HTML_TEMPLATE, StudioRequestHandler


class Page(HTMLParser):
    def __init__(self):
        super().__init__()
        self.ids = []
        self.scripts = []
        self.in_script = False

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if 'id' in attrs:
            self.ids.append(attrs['id'])
        if tag == 'script' and not attrs.get('src'):
            self.in_script = True

    def handle_endtag(self, tag):
        if tag == 'script':
            self.in_script = False

    def handle_data(self, data):
        if self.in_script:
            self.scripts.append(data)


class AuthoringUiTests(unittest.TestCase):
    def test_pages_have_unique_controls_and_valid_scripts(self):
        timeline = Path('tools/timeline_page.html').read_text(encoding='utf-8')
        for name, source, required in (
            ('studio', HTML_TEMPLATE, {'maskPopover', 'documentProtection', 'noirCompose', 'episodeSave'}),
            ('timeline', timeline, {'cards', 'draftPanel', 'draftComposer', 'timelineWires'}),
        ):
            with self.subTest(page=name), tempfile.TemporaryDirectory() as tmp:
                page = Page()
                page.feed(source)
                self.assertTrue(required.issubset(page.ids))
                self.assertEqual([key for key, count in Counter(page.ids).items() if count > 1], [])
                script = Path(tmp) / 'page.js'
                script.write_text('\n'.join(page.scripts), encoding='utf-8')
                result = subprocess.run(['node', '--check', str(script)], capture_output=True, text=True, timeout=15)
                self.assertEqual(result.returncode, 0, result.stderr)

    def test_draft_drawer_endpoint_is_episode_and_branch_scoped(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'timeline.sqlite'
            store = TimelineStore(path)
            store.add_starter_cards()
            store.save('spring-break', 0, script='Fixture.', source_name='fixture')
            NotebookStore(store)
            with store._connect() as connection:
                payload = json.dumps({'id': 'synthetic-draft', 'text': 'Sample draft.'})
                connection.execute('INSERT INTO episode_drafts VALUES(?,?,?,?,?,?)',
                                   ('synthetic-draft', 'spring-break', 'main', 'complete', payload, 0))
            server = ThreadingHTTPServer(('127.0.0.1', 0), StudioRequestHandler)
            server.timeline_path = path
            server.timeline_only = True
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            base = f'http://127.0.0.1:{server.server_port}'
            def query(episode, branch):
                data = json.dumps({'action': 'list', 'episode': episode, 'branch': branch}).encode()
                request = urllib.request.Request(base + '/api/drafts', data=data,
                    headers={'Content-Type': 'application/json', 'Origin': base})
                with urllib.request.urlopen(request) as response:
                    return json.load(response)['drafts']
            try:
                self.assertEqual(query('spring-break', 'main')[0]['text'], 'Sample draft.')
                self.assertEqual(query('tapped-out', 'main'), [])
                with self.assertRaises(urllib.error.HTTPError):
                    query('spring-break', 'other')
            finally:
                server.shutdown()
                server.server_close()
                thread.join()


if __name__ == '__main__':
    unittest.main()
