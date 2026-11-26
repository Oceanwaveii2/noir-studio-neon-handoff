"""Verify the author-facing mockup in a fresh Microsoft Edge browser context."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re

from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parent


def verify(screenshot=None):
    source = ROOT / 'index.html'
    html = source.read_text(encoding='utf-8')
    assert not re.search(r'\b(?:fetch|EventSource|WebSocket|XMLHttpRequest)\s*\(', html)
    assert not re.search(r'<(?:script|iframe)\b[^>]*\bsrc\s*=|tools/assets/v2|studio_client\.js', html, re.I)
    results = ['The standalone page declares no HTTP transport, external script, or legacy runtime dependency.']
    errors, requests = [], []
    media = b'Night station fixture: the clock stops after the key is recovered.'
    digest = hashlib.sha256(media).hexdigest()
    original = 'The station clock stopped at six.'
    protected = '“Keep  the clock still.” '
    events = [{'sequence': index * 2 + offset, 'pass': index + 1, 'status': status}
              for index in range(5) for offset, status in ((1, 'running'), (2, 'done'))]

    with sync_playwright() as pw:
        browser = pw.chromium.launch(channel='msedge', headless=True)
        page = browser.new_page(viewport={'width': 1450, 'height': 990})
        page.on('pageerror', lambda error: errors.append(str(error)))
        page.on('console', lambda message: errors.append(message.text) if message.type == 'error' else None)
        page.on('request', lambda request: requests.append(request.url)
                if request.url.startswith(('http:', 'https:', 'ws:', 'wss:')) else None)
        page.clock.install()
        page.goto(source.as_uri())

        def go(view):
            page.locator('#navigation [data-page="' + view + '"]').click()

        def fill(name, value):
            page.locator('#editor [name="' + name + '"]').fill(value)

        def click(name):
            page.get_by_role('button', name=name, exact=True).click()

        def evidence():
            return json.loads(page.locator('#payload').text_content())

        def state():
            return page.evaluate("JSON.parse(localStorage.getItem('noir-s5-fresh-project-20261125-v1'))")

        expect(page.get_by_role('heading', name='Create an empty project')).to_be_visible()
        page.get_by_label('Project name').fill('Night Station')
        click('Create project')
        blank = state()['project']
        assert not any(blank[key] for key in ('assets', 'characters', 'relationships', 'laws'))
        assert len(blank['branches']) == 1 and not blank['branches'][0]['beats']
        results.append('Created a new project with no source, cast, rule, or beat records.')

        page.locator('#file').set_input_files({'name': 'clock-cue.txt', 'mimeType': 'text/plain', 'buffer': media})
        expect(page.locator('#editor')).to_contain_text('Queued')
        page.clock.run_for(270)
        expect(page.locator('#editor')).to_contain_text('Processing')
        page.clock.run_for(670)
        expect(page.locator('#editor')).to_contain_text('Ready')
        click('Bind source')
        assert evidence()['source_sockets'] == [{
            'filename': 'clock-cue.txt', 'sha256': digest, 'socket': 'rhythm_timing'}]
        results.append('The source passed through queued, processing, and ready, then bound by actual SHA-256.')

        go('cast')
        fill('character', 'Mara')
        fill('form', 'Night courier')
        click('Add character')
        fill('character', 'Jules')
        click('Add character')
        page.locator('[name="from"]').select_option(label='Mara')
        page.locator('[name="to"]').select_option(label='Jules')
        fill('label', 'Trusts as a guide')
        click('Add relationship')
        assert [(c['name'], c['form']) for c in evidence()['characters']] == [('Mara', 'Night courier'), ('Jules', '')]
        assert evidence()['relationships'] == [{'from': 'Mara', 'to': 'Jules', 'label': 'Trusts as a guide'}]
        results.append('Created two characters, an alternate form, and a directed relationship.')

        go('laws')
        fill('rule', 'vault-access')
        fill('action', 'Open vault')
        fill('fact', 'Key recovered')
        click('Add law')
        go('branches')
        fill('title', 'Approach vault')
        fill('action', 'Open vault')
        expect(page.locator('#finding')).to_contain_text('vault-access · Blocking · Approach vault')
        expect(page.get_by_role('button', name='Save beat')).to_be_disabled()
        assert not evidence()['beat_titles']
        fill('title', 'Recover key')
        fill('action', '')
        fill('fact', 'Key recovered')
        click('Save beat')
        fill('title', 'Open the main vault')
        fill('action', 'Open vault')
        fill('fact', 'Main vault open')
        click('Save beat')
        main = evidence()
        assert main['world_facts'] == ['Key recovered', 'Main vault open']
        page.locator('[name="point"]').select_option(label='Recover key')
        fill('name', 'Service stair')
        click('Create fork')
        assert evidence()['beat_titles'] == ['Recover key']
        fill('title', 'Open the alternate vault')
        fill('action', 'Open vault')
        fill('fact', 'Alternate vault open')
        click('Save beat')
        alternate = evidence()
        assert alternate['world_facts'] == ['Key recovered', 'Alternate vault open']
        page.locator('#active-branch').select_option(label='Main')
        assert evidence() == main
        page.locator('#active-branch').select_option(label='Service stair')
        assert evidence() == alternate
        results.append('A law blocked an invalid save. A fork inherited only its saved prefix and preserved isolated world facts.')

        go('cook')
        fill('passage', original)
        fill('dialogue', protected)
        click('Simulate Cook')
        expect(page.locator('.pass[data-status=running]')).to_contain_text('Structure and protection')
        page.clock.run_for(900)
        expect(page.locator('.pass[data-status=running]')).to_contain_text('Passage realization')
        expect(page.locator('.pass[data-status=pending]')).to_contain_text('Polish and byte checks')
        page.clock.run_for(950)
        expect(page.locator('.pass[data-status=done]')).to_have_count(5)
        expect(page.locator('#quality')).to_contain_text('exact dialogue preserved')
        click('Apply draft')
        applied = evidence()
        draft = applied['draft']
        assert draft['events'] == events
        assert draft['dialogue'].encode('utf-8') == protected.encode('utf-8')
        assert draft['passage'].startswith(original + '\n') and draft['passage'] != original
        assert draft['receipt']['media'] == [digest]
        assert draft['receipt']['cast'][0] == {'name': 'Mara', 'form': 'Night courier'}
        assert draft['receipt']['laws'] == ['vault-access']
        assert draft['receipt']['facts'] == alternate['world_facts']
        assert draft['receipt']['branch'] == 'Service stair'
        results.append('Observed running states before completion, verified ten ordered pass events and scoped inputs, and checked exact UTF-8 dialogue after apply.')

        go('laws')
        fill('rule', 'field-undo-guard')
        page.locator('#editor [name="rule"]').press('Control+z')
        assert evidence() == applied
        go('cast')
        page.locator('[data-page="cast"]').press('Control+z')
        assert evidence() == alternate
        click('Undo')
        assert evidence()['beat_titles'] == ['Recover key']
        page.reload()
        expect(page.locator('#redo')).to_be_enabled()
        click('Redo')
        assert evidence() == alternate
        click('Redo')
        assert evidence() == applied
        page.reload()
        assert evidence() == applied
        expect(page.locator('#completion')).to_have_text('5 / 5 workflow items complete')
        results.append('Global Undo and Redo crossed tabs and reloads. Text input retained its native shortcut.')

        go('cook')
        expect(page.locator('.pass[data-status=done]')).to_have_count(5)
        if screenshot:
            page.screenshot(path=str(screenshot), full_page=True)
        page.set_viewport_size({'width': 390, 'height': 844})
        assert page.evaluate('document.documentElement.scrollWidth === window.innerWidth')
        assert not errors and not requests, (errors, requests)
        results.append('Edge verified desktop and 390 px layouts, zero browser errors, and zero HTTP or WebSocket requests.')
        version = browser.version
        browser.close()

    return {'browser': 'Microsoft Edge ' + version, 'scope': 'Standalone browser fixture',
            'source_sha256': hashlib.sha256(source.read_bytes()).hexdigest(), 'checks': results,
            'counts': {'passed': len(results), 'failed': 0}, 'final_evidence': applied}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--receipt', type=Path)
    parser.add_argument('--screenshot', type=Path)
    options = parser.parse_args()
    outcome = json.dumps(verify(options.screenshot), indent=2) + '\n'
    if options.receipt:
        options.receipt.write_text(outcome, encoding='utf-8')
    print(outcome)
