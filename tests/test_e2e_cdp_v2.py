"""Exercise the served six-tab Studio over a fresh headless Edge CDP session."""
from __future__ import annotations

from http.server import ThreadingHTTPServer
import os
from pathlib import Path
import shutil
import subprocess
from tempfile import TemporaryDirectory
from threading import Thread
import time
import unittest

from prose_engine.providers.deepseek_session import DeepSeekSessionProvider
from prose_engine.notebook import NotebookStore
from story_graph.beat_rhythm import BeatRhythmStore
from story_graph.episode_timeline import TimelineStore
from story_graph.form_graph_store import FormGraphStore
from tools.studio_ui import StudioRequestHandler


class StudioCdpTests(unittest.TestCase):
    def test_six_tabs_and_saved_workflow(self):
        try:
            from playwright.sync_api import expect, sync_playwright
        except ImportError:
            detail = 'The Edge CDP test requires the Python playwright package.'
            if os.environ.get('NOIR_REQUIRE_STUDIO_E2E'):
                self.fail(detail)
            self.skipTest(detail)
        locations = (Path(parent) / 'Microsoft/Edge/Application/msedge.exe'
                     for key in ('ProgramFiles(x86)', 'ProgramFiles') if (parent := os.environ.get(key)))
        edge = shutil.which('msedge') or next((path for path in locations if path.is_file()), None)
        if not edge:
            if os.environ.get('NOIR_REQUIRE_STUDIO_E2E'):
                self.fail('Microsoft Edge is unavailable for the CDP verification.')
            self.skipTest('Microsoft Edge is unavailable.')

        temp = TemporaryDirectory(prefix='noir-studio-cdp-')
        self.addCleanup(temp.cleanup)
        root = Path(temp.name)
        timeline = TimelineStore(root / 'timeline.sqlite', project_id='cdp', universe_id='fixture')
        timeline.create_episode('clock', 'The station', 'main', 10)
        timeline.create_episode('platform', 'The platform', 'main', 20)
        source = 'INT. STATION - DAY\n\n[Missing detail: Show the station clock.]\n'
        timeline.save('clock', 0, script=source, source_name='cdp-fixture')
        notebook = NotebookStore(timeline)
        opened = notebook.open('clock')
        notebook.save('clock', opened['revision'], 1, opened['blocks'], 25, opened['masks'])
        forms = FormGraphStore(timeline.form_graph_path)
        forms.change({'action': 'add_character', 'revision': 0, 'character_id': 'mara', 'label': 'Mara'})
        draft_prompts = []

        def fixture_writer(prompt):
            draft_prompts.append(prompt)
            return 'The station clock stopped at six. A paper ticket skimmed across the empty platform.'

        provider = DeepSeekSessionProvider(session_handler=fixture_writer, max_calls=1, ledger=root / 'writer.jsonl')
        provider.name = provider.model_name = 'codex-session'
        server = ThreadingHTTPServer(('127.0.0.1', 0), StudioRequestHandler)
        server.daemon_threads = False
        server.timeline_path = root / 'timeline.sqlite'
        server.timeline_only = True
        server.books_dir = root / 'books'
        server.initial_episode = 'clock'
        server.form_graph = forms
        server.test_writer_factory = lambda: provider
        server_thread = Thread(target=server.serve_forever, kwargs={'poll_interval': .05}, daemon=True)
        server_thread.start()
        self.addCleanup(server_thread.join)
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        base = f'http://127.0.0.1:{server.server_port}'

        profile = root / 'edge-cdp'
        process = subprocess.Popen([
            str(edge), '--headless=new', '--no-first-run', '--disable-background-networking',
            '--disable-gpu', '--remote-debugging-port=0', '--remote-debugging-address=127.0.0.1',
            '--user-data-dir=' + str(profile), 'about:blank',
        ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))

        def stop_edge():
            if process.poll() is None:
                process.terminate()
                process.wait(timeout=10)
        self.addCleanup(stop_edge)

        port_file = profile / 'DevToolsActivePort'
        deadline = time.monotonic() + 15
        while not port_file.is_file() and time.monotonic() < deadline and process.poll() is None:
            time.sleep(.05)
        self.assertTrue(port_file.is_file(), 'Edge did not publish a CDP port')
        port = int(port_file.read_text(encoding='utf-8').splitlines()[0])
        errors = []
        missing_assets = []
        with sync_playwright() as playwright:
            browser = playwright.chromium.connect_over_cdp(f'http://127.0.0.1:{port}')
            try:
                context = browser.contexts[0]
                page = context.new_page()
                page.set_viewport_size({'width': 1700, 'height': 1090})
                page.emulate_media(reduced_motion='reduce')
                page.set_default_timeout(20_000)
                page.on('pageerror', lambda error: errors.append(str(error)))
                page.on('response', lambda response: missing_assets.append(response.url)
                        if response.status == 404 and '/assets/' in response.url else None)
                page.goto(f'{base}/v2?episode=clock&view=start', wait_until='domcontentloaded')

                def tab(key):
                    page.locator(f'button[data-view="{key}"]').click()
                    expect(page.locator(f'.v2-body[data-view="{key}"]')).to_be_visible()

                def fill_and_save(field, button, value):
                    expect(page.locator(field)).to_be_visible()
                    expect(page.locator(button)).to_be_enabled()
                    page.evaluate("""([field, button, value]) => {
                        const input = document.querySelector(field);
                        input.value = value;
                        input.dispatchEvent(new Event('input', { bubbles: true }));
                        document.querySelector(button).click();
                    }""", [field, button, value])

                expect(page.locator('.v2-body[data-view="start"]')).to_be_visible()
                expect(page.locator('#v2SaveBtn')).to_contain_text('Saved r1')
                self.assertEqual(page.locator('nav button[data-view]').count(), 6)
                tab('prep')
                page.locator('[data-prep-mode="raw"]').click()
                quote = '“Keep the clock still.”'
                fill_and_save('#v2PrepEditorText', '#v2PrepSendComposeBtn', f'[DIALOGUE: Mara] {quote}')
                expect(page.locator('.v2-body[data-view="compose"]')).to_be_visible()
                self.assertTrue(timeline.get_episode('clock')['script'].endswith(quote))
                self.assertEqual(notebook.open('clock')['blocks'][-1]['speaker'], 'mara')
                page.locator('[data-set-canon-mode="time_travel_canon"]').click()
                page.locator('#v2TtCarrierSelect').select_option('mara')
                expect(page.locator('[data-set-canon-mode="time_travel_canon"]')).to_have_attribute('aria-pressed', 'true')
                page.wait_for_function("window.__noirStore.get().episodeState.episode.canon_tag.tt_carrier === 'mara'")
                self.assertEqual(timeline.get_episode('clock')['canon_tag']['tt_carrier'], 'mara')

                tab('graph')
                page.get_by_role('button', name='Global Master Vault').click()
                page.locator('[data-sw-char="mara"]').click()
                page.get_by_role('button', name='Open Form Interior').click()
                expect(page.get_by_role('heading', name='Physical Identity & Wardrobe')).to_be_visible()
                expect(page.get_by_role('heading', name='Behavioral Mind Graph')).to_be_visible()
                page.get_by_role('button', name='Back to Character Graph').click()
                drop = page.evaluate_handle("""() => {
                  const data = new DataTransfer();
                  data.items.add(new File(['A handwritten cue.'], 'wardrobe.txt', {type:'text/plain'}));
                  return data;
                }""")
                with page.expect_response(lambda response: '/api/beat-media/upload?' in response.url and response.status == 201):
                    page.locator('[data-node-kind="form"][data-char-id="mara"]').dispatch_event('drop', {'dataTransfer': drop})
                expect(page.locator('#swToast')).to_contain_text('Saved 1 media pin', timeout=15_000)
                vault_button = page.locator('#swMediaVaultBtn')
                expect(vault_button).to_be_visible()
                vault_button.click()
                try:
                    expect(page.get_by_role('dialog', name='Multimodal Media Vault')).to_be_visible()
                    expect(page.locator('.v2-mv-pin-card')).to_contain_text('wardrobe.txt')
                except AssertionError:
                    print('Media Vault state:', page.evaluate("""() => {
                        const s = window.__noirStore.get();
                        return {modal: s.popModal, target: s.mediaVaultTarget, pins: s.mediaVault?.pins.length,
                            error: s.mediaVault?.error};
                    }"""), 'Browser errors:', errors)
                    raise
                page.locator('#v2PopCloseBtn').click()
                expect(page.locator('#v2PopCloseBtn')).to_have_count(0)

                page.get_by_role('tab', name='Story DAG').click()
                prior_nodes = timeline.get_episode('clock')['graph']['nodes']
                page.locator('#v2GraphAddNodeBtn').click()
                page.locator('#v2GraphSaveBtn').click()
                page.wait_for_function("window.__noirStore.get().projectHistory?.next_undo?.domain === 'graph'")
                page.wait_for_function("window.__noirStore.get().notice?.text.startsWith('Saved story graph')")
                graph_nodes = timeline.get_episode('clock')['graph']['nodes']
                self.assertEqual(len(graph_nodes), len(prior_nodes) + 1)

                page.get_by_role('tab', name='Form Switchyard').click()
                page.get_by_role('button', name='Global Master Vault').click()
                page.locator('[data-sw-char="mara"]').click()
                page.get_by_role('button', name='Open Form Interior').click()
                def appearance():
                    mara = next(char for char in forms.read()['junctions'] if char['character_id'] == 'mara')
                    return next((data['appearance'] for data in mara['node_data'].values() if data.get('appearance')), '')
                previous_appearance = appearance()
                with page.expect_response(lambda response: response.url.endswith('/api/form-graph')
                                          and response.request.method == 'POST') as appearance_response:
                    fill_and_save('#swAppearance', '#swSavePhysical', 'Charcoal coat')
                response = appearance_response.value
                self.assertEqual(response.status, 200)
                self.assertEqual(response.request.post_data_json['content']['appearance'], 'Charcoal coat')
                self.assertEqual(response.request.post_data_json['character'], 'mara')
                page.wait_for_function("window.__noirStore.get().projectHistory?.next_undo?.domain === 'forms'")
                self.assertEqual(appearance(), 'Charcoal coat')
                page.get_by_role('button', name='Back to Character Graph').click()

                tab('story')
                page.get_by_role('tab', name='Rhythm & Timing').click()
                editor = page.locator('[data-structure-edit]')
                editor.locator('[name="preset"]').select_option('six_act')
                editor.locator('[name="tension"]').fill('3')
                editor.locator('[name="audio"]').uncheck()
                with page.expect_response(lambda response: '/api/beat-rhythm' in response.url
                                          and 'structure_save' in (response.request.post_data or '')) as saved:
                    page.get_by_role('button', name='Save timing targets').click()
                self.assertEqual(saved.value.status, 200)
                expect(page.get_by_role('img', name='Saved tension targets')).to_be_visible()
                page.wait_for_function("window.__noirStore.get().projectHistory?.next_undo?.domain === 'timing'")
                page.evaluate("document.activeElement?.blur()")
                page.keyboard.press('Control+z')
                page.wait_for_function("!window.__noirStore.get().busy && window.__noirStore.get().projectHistory?.next_redo?.domain === 'timing'")
                page.keyboard.press('Control+z')
                page.wait_for_function("!window.__noirStore.get().busy && window.__noirStore.get().projectHistory?.next_redo?.domain === 'forms'")
                page.reload(wait_until='domcontentloaded')
                page.wait_for_function("!window.__noirStore.get().busy && window.__noirStore.get().episodeState?.episode?.id === 'clock' && window.__noirStore.get().projectHistory?.next_redo?.domain === 'forms'")
                self.assertEqual(appearance(), previous_appearance)
                self.assertEqual(timeline.get_episode('clock')['graph']['nodes'], graph_nodes)
                self.assertIsNone(BeatRhythmStore(timeline).open_structure('clock', timeline.get_episode('clock')['head'])['points'][0]['tension'])
                page.keyboard.press('Control+Shift+z')
                page.wait_for_function("!window.__noirStore.get().busy && window.__noirStore.get().projectHistory?.next_redo?.domain === 'timing'")
                self.assertEqual(appearance(), 'Charcoal coat')
                page.keyboard.press('Control+Shift+z')
                page.wait_for_function("!window.__noirStore.get().busy && !window.__noirStore.get().projectHistory?.next_redo")
                tab('story')
                page.get_by_role('tab', name='Beat DAG').click()
                expect(page.locator('.sg-node [title="Saved tension"]')).to_have_text('3/5')
                page.get_by_role('tab', name='Story Beats').click()
                expect(page.get_by_role('button', name='Beat media')).to_be_visible()

                tab('timeline')
                page.locator('.v2-tl-card[data-episode="clock"] .v2-tl-card-body').click()
                page.locator('#v2InspMoveLater').click()
                expect(page.get_by_role('heading', name='Preview episode move')).to_be_visible()
                page.locator('[data-impact-cancel]').click()
                self.assertEqual(timeline.cards()[0]['id'], 'clock')
                page.locator('#v2InspMoveLater').click()
                page.locator('[data-impact-proceed]').click()
                page.wait_for_function("window.__noirStore.get().timeline.cards[0].id === 'platform'")
                expect(page.locator('#v2TlUndoBtn')).to_be_enabled()
                page.keyboard.press('Control+z')
                page.wait_for_function("window.__noirStore.get().timeline.cards[0].id === 'clock'")
                expect(page.locator('#v2TlRedoBtn')).to_be_enabled()
                page.keyboard.press('Control+Shift+z')
                page.wait_for_function("window.__noirStore.get().timeline.cards[0].id === 'platform'")
                expect(page.locator('#v2TlUndoBtn')).to_be_enabled()
                page.keyboard.press('Control+z')
                page.wait_for_function("window.__noirStore.get().timeline.cards[0].id === 'clock'")

                tab('compose')
                expect(page.locator('.sg-structure.is-compact')).to_contain_text('Audio closed')
                page.get_by_role('button', name='Prepare structure', exact=True).click()
                expect(page.get_by_role('button', name='Render passage')).to_be_enabled()
                with page.expect_response(lambda response: response.url.endswith('/api/episode-command') and
                                          'run.selection' in (response.request.post_data or '')) as writing:
                    page.get_by_role('button', name='Render passage').click()
                selected = writing.value.request.post_data_json
                self.assertEqual(selected['notebook_revision'], notebook.open('clock')['revision'])
                self.assertEqual(selected['revision'], timeline.get_episode('clock')['head'])
                expect(page.get_by_role('button', name='Open saved draft')).to_be_visible(timeout=20_000)
                expect(page.locator('.v2-cook-stages')).to_contain_text('CACHE_HIT')
                expect(page.locator('.v2-cook-stages')).to_contain_text('Composite Slop Score')
                self.assertEqual(len(draft_prompts), 1)
                self.assertIn('SAVED COOK DIRECTION', draft_prompts[0])
                self.assertIn('wardrobe_reference', draft_prompts[0])
                self.assertIn('"audio": false', draft_prompts[0])
                self.assertIn(quote, timeline.get_episode('clock')['script'])
                self.assertEqual(errors, [])
                self.assertEqual(missing_assets, [])
            finally:
                browser.close()
