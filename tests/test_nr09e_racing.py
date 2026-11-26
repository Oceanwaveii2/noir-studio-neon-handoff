import tempfile
import threading
import unittest
import urllib.request
import subprocess
import re
from http.server import ThreadingHTTPServer
from pathlib import Path
from PIL import Image, ImageChops

from tools.studio_ui import HTML_TEMPLATE, REPO_ROOT, StudioRequestHandler


class RacingAssetTests(unittest.TestCase):
    def test_each_finite_animation_stops_on_its_target_frame(self):
        sequence = [27,28,29,30,31,32,33,34,35,0,1,2,3,4,5,6,7,8,9]
        targets = {25:6, 50:9, 75:12, 100:18}
        with Image.open(REPO_ROOT / 'tools/assets/noir-track-loader.gif') as source:
            for weight, end in targets.items():
                with self.subTest(weight=weight), Image.open(REPO_ROOT / f'tools/assets/noir-track-dial-{weight}-once.gif') as result:
                    self.assertNotIn('loop', result.info)
                    self.assertEqual(result.n_frames, end + 1)
                    for index, number in enumerate(sequence[:end + 1]):
                        source.seek(number); result.seek(index)
                        expected = source.convert('RGB').crop((175, 115, 335, 295))
                        self.assertIsNone(ImageChops.difference(expected, result.convert('RGB')).getbbox(), f'{weight}% frame {index}')

    def test_dial_faces_are_original_loader_frames(self):
        frames = [int(n) for n in re.search(r'const dialFrames=\[([^]]+)\]', HTML_TEMPLATE).group(1).split(',')]
        positions = {25:6, 50:9, 75:12, 100:18}
        self.assertEqual([frames[positions[weight]] for weight in positions], [33, 0, 3, 9])
        with Image.open(REPO_ROOT / 'tools/assets/noir-track-loader.gif') as source, Image.open(REPO_ROOT / 'tools/assets/noir-track-dial-frames.png') as sprite:
            self.assertEqual(source.n_frames, 36)
            for number in frames:
                source.seek(number)
                original = source.convert('RGB').crop((175, 115, 335, 295))
                x, y = (number % 6) * 160, (number // 6) * 180
                tile = sprite.crop((x, y, x + 160, y + 180)).convert('RGB')
                self.assertIsNone(ImageChops.difference(original, tile).getbbox(), f'frame {number}')

    def test_selection_dial_reports_uniform_and_mixed_effective_values(self):
        function = 'function selectionProtection(' + HTML_TEMPLATE.split('function selectionProtection(', 1)[1].split('\nfunction updateNoirSummary()', 1)[0]
        js = function + '''
const assert = require('assert');
const state = {default_protection:25,masks:[{start:4,end:11,value:50},{start:7,end:9,value:75}]};
assert.strictEqual(selectionProtection({start:0,end:4},state),25);
assert.strictEqual(selectionProtection({start:4,end:7},state),50);
assert.strictEqual(selectionProtection({start:7,end:9},state),75);
assert.strictEqual(selectionProtection({start:0,end:11},state),null);
assert.strictEqual(selectionProtection({start:0,end:1},{...state,stale:true}),null);
'''
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / 'dial.js'; source.write_text(js, encoding='utf-8')
            result = subprocess.run(['node', str(source)], capture_output=True, text=True, timeout=15)
            self.assertEqual(result.returncode, 0, result.stderr)

    def test_real_animation_and_comparison_assets_are_served(self):
        with tempfile.TemporaryDirectory() as tmp:
            server = ThreadingHTTPServer(('127.0.0.1', 0), StudioRequestHandler)
            server.timeline_path = Path(tmp) / 'timeline.sqlite'
            thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
            base = 'http://127.0.0.1:' + str(server.server_port)
            try:
                with urllib.request.urlopen(base + '/assets/noir-track-loader.gif') as response:
                    self.assertEqual(response.headers.get_content_type(), 'image/gif')
                    self.assertEqual(response.read(), (REPO_ROOT / 'tools/assets/noir-track-loader.gif').read_bytes())
                with urllib.request.urlopen(base + '/assets/noir-track-dial-frames.png') as response:
                    self.assertEqual(response.headers.get_content_type(), 'image/png')
                    self.assertEqual(response.read(), (REPO_ROOT / 'tools/assets/noir-track-dial-frames.png').read_bytes())
                for weight in (25, 50, 75, 100):
                    with urllib.request.urlopen(base + f'/assets/noir-track-dial-{weight}-once.gif') as response:
                        self.assertEqual(response.headers.get_content_type(), 'image/gif')
                        self.assertEqual(response.read(), (REPO_ROOT / f'tools/assets/noir-track-dial-{weight}-once.gif').read_bytes())
                with urllib.request.urlopen(base + '/assets/noir-racing-reference.png') as response:
                    self.assertEqual(response.headers.get_content_type(), 'image/png')
                    self.assertEqual(response.read(), (REPO_ROOT / 'docs/noir-ui-gap-report-assets-2026-11-09/racing-user-reference.png').read_bytes())
                with urllib.request.urlopen(base + '/racing-comparison') as response:
                    self.assertIn(b'Running sample editor', response.read())
            finally:
                server.shutdown(); server.server_close(); thread.join()


if __name__ == '__main__': unittest.main()
