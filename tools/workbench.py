"""
Local workbench: the original text stays visible and untouched; you rewrite paragraph by
paragraph and save a conditioned copy.

    python tools/workbench.py --file scene.md --provider edits --edits edits.json --port 8765
    python tools/workbench.py --file scene.md --provider local

Standard library only. API:
    GET  /                 the page
    GET  /api/state        paragraphs + saved edits
    POST /api/rewrite      {index, strength} -> {text, issues, accepted}
    POST /api/save         preview, apply or undo against a configured revision store
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

if __name__ == '__main__' and any(arg == '--service-ticket' or arg.startswith('--service-ticket=') for arg in sys.argv[1:]):
    from tools.workbench_remote import main as connected_workbench
    raise SystemExit(connected_workbench())

from prose_engine.voice.chunking import chunk_text, label as chunk_label
from prose_engine.voice.references import format_references
from prose_engine.voice.slop import flag
from prose_engine.voice.world_state import WorldState
from prose_engine.voice.luar import LuarDrive, LuarIndex
from prose_engine.voice.spatial import House
from prose_engine.guards import fact_list, personification_issues, preserves_facts, reference_copies, token_overlap
from prose_engine.imagery import mask, retained, vehicles
from prose_engine.models import ProseRewriteRequest, SpanCategory
from prose_engine.providers import create_prose_provider
from prose_engine.strength import get as get_strength
from prose_engine.voice.strength_map import policy
from prose_engine.voice.tics import counts as tic_counts
from prose_engine.voice.variations import TREATMENTS
from prose_engine.providers.deepseek import BudgetExceeded
from prose_engine.editorial_adapter import dispatch
from prose_engine.editorial_revisions import RevisionError, RevisionStore

PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>Workbench</title>
<style>
  :root{color-scheme:dark}
  body{margin:0;background:#0b1120;color:#e2e8f0;font-family:ui-sans-serif,system-ui}
  header{padding:14px 20px;border-bottom:1px solid #1e293b;display:flex;gap:14px;align-items:center;flex-wrap:wrap}
  h1{font-size:15px;color:#fbbf24;margin:0}
  .hint{font-size:12px;color:#94a3b8}
  main{padding:16px 20px;display:grid;gap:14px}
  .para{border:1px solid #1e293b;border-radius:10px;padding:12px;background:#0f172a}
  .para h2{font-size:11px;color:#7dd3fc;text-transform:uppercase;letter-spacing:.06em;margin:0 0 8px}
  .spans-list{display:flex;flex-wrap:wrap;gap:8px;margin:8px 0 10px}
  .span-badge{display:inline-flex;align-items:center;gap:6px;padding:4px 8px;border-radius:6px;font:11px ui-monospace,Consolas;background:#1e293b;border:1px solid #334155}
  .span-rule{font-weight:600;color:#f87171}
  .span-text{color:#cbd5e1;max-width:200px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
  .span-btn{padding:2px 6px;font-size:10px;border-radius:4px;border:none;cursor:pointer;font-weight:600}
  .span-agree{background:#166534;color:#bbf7d0}
  .span-disagree{background:#991b1b;color:#fecaca}
  .span-agree:hover{background:#22c55e;color:#052e16}
  .span-disagree:hover{background:#ef4444;color:#450a0a}
  .orig{white-space:pre-wrap;font:13px/1.6 ui-monospace,Consolas;color:#cbd5e1}
  .passage{width:100%;min-height:140px;font:13px/1.6 ui-monospace,Consolas;color:#e2e8f0;background:#0b1120;
    border:1px solid #253352;border-radius:8px;padding:10px;box-sizing:border-box;resize:vertical}
  .direction{min-height:52px;margin-top:8px;font:12px/1.5 ui-monospace,Consolas;width:100%;background:#0b1120;border:1px solid #253352;border-radius:8px;padding:8px;color:#cbd5e1;box-sizing:border-box}
  .row{display:flex;gap:10px;align-items:center;margin-top:8px;flex-wrap:wrap}
  input[type=range]{flex:1;min-width:120px}
  button{background:#111c33;color:#e2e8f0;border:1px solid #253352;border-radius:7px;padding:6px 10px;cursor:pointer;font-size:12px}
  button:hover{border-color:#38bdf8;color:#7dd3fc}
  select{background:#111c33;color:#e2e8f0;border:1px solid #253352;border-radius:7px;padding:6px 8px;font-size:12px}
  .prop{margin-top:10px;padding:10px;border-left:3px solid #4ade80;background:#0b1726;white-space:pre-wrap;font:13px/1.6 ui-monospace,Consolas}
  .bad{border-left-color:#f87171}
  .issues{font:11px ui-monospace;color:#fca5a5;margin-top:6px}
  .ab-box{margin-top:10px;display:grid;grid-template-columns:1fr 1fr;gap:12px}
  .ab-card{padding:12px;border:1px solid #334155;border-radius:8px;background:#090d16}
  .ab-card h3{margin:0 0 8px;font-size:12px;color:#fbbf24;text-transform:uppercase}
  .ab-card pre{white-space:pre-wrap;font:12px/1.5 ui-monospace,Consolas;margin:0 0 10px;color:#cbd5e1;min-height:80px}
  #status{position:sticky;bottom:0;background:#0b1120;border-top:1px solid #1e293b;padding:10px 20px;font:12px ui-monospace;color:#4ade80}
</style></head><body>
<header>
  <h1>Workbench</h1>
  <strong role="status">Standalone file: episode timeline and universe laws are not connected.</strong>
  <select id="mode" title="mode">
    <option value="correction">Correction</option>
    <option value="variation">Variation</option>
  </select>
  <label class="hint" style="display:inline-flex;align-items:center;gap:6px;cursor:pointer">
    <input type="checkbox" id="blindAb"/> <strong>Blind A/B Mode</strong>
  </label>
  <span class="hint" id="modeHint">correction: keep the passage, remove AI tells</span>
  <span class="hint" id="fileLabel"></span>
  <button id="save">Preview changes</button>
  <input id="reviewer" aria-label="Reviewer name" placeholder="Reviewer name">
  <button id="apply" disabled>Accept and apply</button>
  <button id="undo">Undo revision</button>
  <button id="redo" disabled>Redo revision</button>
</header>
<details id="reference-settings"><summary>Reference sources</summary>
  <p>Choose how each source may be used. Existing influence settings still apply.</p>
  <button type="button" id="reference-load">Load sources</button>
  <div id="reference-message" role="status"></div>
  <div id="reference-list"></div>
</details>
<pre id="review" aria-live="polite" style="white-space:pre-wrap"></pre>
<main id="paras"></main>
<div id="status"></div>
<script>
const state = {paragraphs: [], edits: {}, spans: [], revision: null, review: null, pendingUndo: null, pendingRedo: null};
const $ = (id) => document.getElementById(id);
const esc = (s) => (s || '').replace(/[&<>]/g, (c) => ({'&':'&amp;','<':'&lt;','>':'&gt;'}[c]));

async function loadReferences() {
  const res=await fetch('/api/reference-policy'), data=await res.json();
  if (!res.ok) throw Error(data.error || 'Could not load sources.');
  const list=$('reference-list'); list.replaceChildren();
  for (const source of data.sources) {
    const row=document.createElement('fieldset'), legend=document.createElement('legend');
    legend.textContent=source.id + (source.influence_off ? ' (influence is off)' : '');
    row.append(legend);
    const make=(label,checked)=>{const l=document.createElement('label'), c=document.createElement('input');
      c.type='checkbox'; c.checked=checked; l.append(c, document.createTextNode(' '+label+' ')); row.append(l); return c;};
    const enabled=make('Enabled',source.enabled), choices={};
    for (const [key,label] of [['rank_local','Local ranking'],['inspect_local','Local inspection'],
      ['prompt','Prompt'],['remote_transfer','Remote transfer'],['export','Export']])
      choices[key]=make(label,source.permissions.includes(key));
    const save=document.createElement('button'); save.type='button'; save.textContent='Save source';
    save.onclick=async()=>{save.disabled=true; try {
      const response=await fetch('/api/reference-policy',{method:'POST',headers:{'Content-Type':'application/json'},
        body:JSON.stringify({source:source.id,enabled:enabled.checked,
          permissions:Object.keys(choices).filter(k=>choices[k].checked),revision:data.revision})});
      const result=await response.json(); if (!response.ok) throw Error(result.error || 'Save failed.');
      $('reference-message').textContent='Saved. '+result.retrieval_status;
      await loadReferences();
      $('status').textContent='References: '+result.retrieval_status;
    } catch(error) { $('reference-message').textContent=error.message; }
      finally {save.disabled=false;}};
    row.append(save); list.append(row);
  }
}
$('reference-load').onclick=async()=>{try {await loadReferences();}
  catch(error) {$('reference-message').textContent=error.message;}};

async function loadState() {
  const response = await fetch('/api/state');
  const data = await response.json();
  state.paragraphs = data.paragraphs;
  state.spans = data.spans || [];
  state.revision = data.revision;
  state.review = null;
  state.pendingUndo = null;
  state.pendingRedo = null;
  $('apply').disabled = true;
  $('save').disabled = data.revision === null;
  $('undo').disabled = data.revision === null || data.can_undo === false;
  $('redo').disabled = data.revision === null || !data.can_redo;
  $('status').textContent = (data.revision === null ? 'Review store unavailable. Start Workbench with --review-store.' : 'Revision ' + data.revision + ' (' + (data.scope_status || 'unscoped-standalone') + ': revision store only)') + ' · References: ' + data.retrieval_status;
  $('fileLabel').textContent = data.file;
  const host = $('paras');
  host.innerHTML = '';
  data.paragraphs.forEach((text, index) => {
    const block = document.createElement('section');
    block.className = 'para';

    let spanHtml = '';
    const spans = (data.spans && data.spans[index]) ? data.spans[index] : [];
    if (spans.length) {
      spanHtml = '<div class="spans-list">';
      spans.forEach((s) => {
        spanHtml += `
          <div class="span-badge" title="${esc(s.why)}">
            <span class="span-rule">${esc(s.rule)}</span>:
            <span class="span-text">"${esc(s.text)}"</span>
            <button class="span-btn span-agree" data-label="agree" data-label-index="${index}" data-rule="${esc(s.rule)}" data-span-text="${esc(s.text)}">Agree</button>
            <button class="span-btn span-disagree" data-label="disagree" data-label-index="${index}" data-rule="${esc(s.rule)}" data-span-text="${esc(s.text)}">Disagree</button>
          </div>`;
      });
      spanHtml += '</div>';
    }

    block.innerHTML = `
      <h2>${(data.labels && data.labels[index]) ? data.labels[index] : 'passage ' + (index + 1)}
        <span class="slop" style="float:right;color:${(data.scores && data.scores[index] >= 60) ? '#f87171' : '#64748b'}">slop ${(data.scores && data.scores[index]) ? data.scores[index] : 0}</span></h2>
      ${spanHtml}
      <textarea class="passage" data-passage="${index}" spellcheck="false">${esc(text)}</textarea>
      <textarea class="direction" data-dir="${index}" placeholder="direction: what should this passage do? (empty = keep as is)"></textarea>
      <div class="row">
        <label class="hint">strength</label>
        <input type="range" min="0" max="1" step="0.05" value="0.8" data-index="${index}" class="strength"/>
        <span class="hint" data-value="${index}">0.80</span>
        <button data-rewrite="${index}">Rewrite</button>
        <span class="hint" data-result="${index}"></span>
      </div>
      <div class="prop" data-prop="${index}" style="display:none"></div>`;
    host.appendChild(block);
  });

  host.querySelectorAll('.strength').forEach((slider) => slider.addEventListener('input', (event) => {
    document.querySelector(`[data-value="${event.target.dataset.index}"]`).textContent = Number(event.target.value).toFixed(2);
  }));
  host.querySelectorAll('[data-rewrite]').forEach((button) => button.addEventListener('click', () => rewrite(button.dataset.rewrite)));

  host.querySelectorAll('.span-btn').forEach((btn) => btn.addEventListener('click', async (e) => {
    e.stopPropagation();
    const index = Number(btn.dataset.labelIndex);
    const decision = btn.dataset.label;
    const rule = btn.dataset.rule;
    const spanText = btn.dataset.spanText;
    const passageText = document.querySelector('.passage[data-passage="' + index + '"]').value;
    await fetch('/api/label', {
      method: 'POST',
      headers: {'content-type': 'application/json'},
      body: JSON.stringify({index, decision, rule, text: spanText, passage: passageText})
    });
    const badge = btn.closest('.span-badge');
    badge.style.opacity = '0.5';
    badge.innerHTML = `<span class="span-rule">${esc(rule)}</span>: ${decision === 'agree' ? '✓ Agreed (Slop)' : '✗ Disagreed (Clean)'}`;
  }));
}

async function pickAB(token, index, choice) {
  const label = document.querySelector(`[data-result="${index}"]`);
  label.textContent = 'recording choice...';
  const response = await fetch('/api/blind_ab/choice', {
    method: 'POST',
    headers: {'content-type': 'application/json'},
    body: JSON.stringify({token, choice})
  });
  const data = await response.json();
  const box = document.querySelector(`[data-prop="${index}"]`);
  document.querySelector('.passage[data-passage="' + index + '"]').value = data.text;
  state.edits[index] = data.text;
  label.textContent = `Chose Option ${choice} (${data.winner_provenance}) — recorded to blind_ab.jsonl`;
  box.innerHTML = `<div class="hint" style="color:#4ade80">✓ Revealed: Selected Option ${choice} was <strong>${esc(data.winner_provenance)}</strong> (Other: ${esc(data.loser_provenance)}). Inserted into passage.</div>`;
}

async function rewrite(index) {
  const strength = Number(document.querySelector(`.strength[data-index="${index}"]`).value);
  const direction = document.querySelector(`.direction[data-dir="${index}"]`).value;
  const label = document.querySelector(`[data-result="${index}"]`);
  const box = document.querySelector(`[data-prop="${index}"]`);
  box.style.display = 'block';

  if ($('blindAb').checked) {
    label.textContent = 'generating Blind A/B pair...';
    const response = await fetch('/api/blind_ab', {
      method: 'POST',
      headers: {'content-type': 'application/json'},
      body: JSON.stringify({index, strength, direction})
    });
    const data = await response.json();
    box.classList.remove('bad');
    box.innerHTML = `
      <div class="ab-box">
        <div class="ab-card">
          <h3>Option 1</h3>
          <pre>${esc(data.option1.text)}</pre>
          <button onclick="pickAB('${data.token}', ${index}, '1')">Pick Option 1</button>
        </div>
        <div class="ab-card">
          <h3>Option 2</h3>
          <pre>${esc(data.option2.text)}</pre>
          <button onclick="pickAB('${data.token}', ${index}, '2')">Pick Option 2</button>
        </div>
      </div>`;
    label.textContent = 'Blind A/B ready — select Option 1 or Option 2';
    return;
  }

  const mode = $('mode').value;
  const treatments = mode === 'variation' ? ['nanite_malfunction', 'staged', 'curse'] : [];
  label.textContent = 'working...';
  const response = await fetch('/api/rewrite', {
    method: 'POST',
    headers: {'content-type': 'application/json'},
    body: JSON.stringify({index, strength, direction, mode, treatments})
  });
  const data = await response.json();
  if (data.variants) {
    box.classList.remove('bad');
    box.innerHTML = '';
    data.variants.forEach((variant) => {
      const item = document.createElement('div');
      item.style.marginBottom = '10px';
      item.style.cursor = 'pointer';
      const head = document.createElement('div');
      head.className = 'hint';
      head.textContent = variant.treatment + (variant.accepted ? '' : ' — rejected: ' + (variant.issues || []).join('; '));
      const body = document.createElement('div');
      body.textContent = variant.text;
      item.appendChild(head);
      item.appendChild(body);
      item.onclick = () => {
        document.querySelector('.passage[data-passage="' + index + '"]').value = variant.text;
        label.textContent = 'inserted ' + variant.treatment;
      };
      box.appendChild(item);
    });
    label.textContent = data.variants.filter((v) => v.accepted).length + ' variants — click one to insert';
    return;
  }
  box.classList.toggle('bad', !data.accepted);
  box.textContent = data.text + (data.issues && data.issues.length ? '\\n\\n' + data.issues.join('; ') : '');
  box.title = 'click to put this into the passage box';
  box.onclick = () => {
    document.querySelector('.passage[data-passage="' + index + '"]').value = data.text;
    label.textContent = 'inserted into passage';
  };
  if (data.accepted) { state.edits[index] = data.text; label.textContent = 'accepted (click result to insert)'; }
  else { label.textContent = 'rejected'; }
}

async function reviewRequest(payload) {
  const response = await fetch('/api/save', {method: 'POST', headers: {'content-type': 'application/json'}, body: JSON.stringify(payload)});
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || 'Review request failed');
  return data;
}
function reviewError(error) { $('status').textContent = error.message; }
$('save').addEventListener('click', async () => {
  state.review = null;
  $('apply').disabled = true;
  const edits = {};
  document.querySelectorAll('.passage').forEach((box) => {
    if (box.value !== state.paragraphs[Number(box.dataset.passage)]) edits[box.dataset.passage] = box.value;
  });
  try {
    const payload = {action:'preview',base:state.revision,edits};
    const result = await reviewRequest(payload);
    $('review').textContent = [result.status, ...result.baseline_issues.map(x => 'Existing: ' + x.reason),
      ...result.new_issues.map(x => 'New: ' + x.reason), result.diff].join(String.fromCharCode(10));
    if (result.status === 'ELIGIBLE_FOR_REVIEW') {
      state.review = {...payload,action:'apply',operation_id:crypto.randomUUID(),
        candidate_hash:result.candidate_hash,world_hash:result.world_hash};
      $('apply').disabled = false;
    }
  } catch (error) { reviewError(error); }
});
$('paras').addEventListener('input', () => {
  state.review = null;
  $('apply').disabled = true;
});
$('apply').addEventListener('click', async () => {
  if (!state.review) return;
  try {
    const reviewer = $('reviewer').value;
    if (!reviewer.trim()) throw new Error('Enter a reviewer name before applying.');
    state.review.reviewer ??= reviewer;
    const result = await reviewRequest(state.review);
    await loadState();
    $('review').textContent = 'Applied revision ' + result.revision;
  } catch (error) { reviewError(error); }
});
async function stepHistory(kind, key, label) {
  try {
    const reviewer = $('reviewer').value;
    if (!reviewer.trim()) throw new Error('Enter a reviewer name before ' + label + '.');
    state[key] ??= {action:kind,base:state.revision,operation_id:crypto.randomUUID(),reviewer};
    const result = await reviewRequest(state[key]);
    await loadState();
    $('review').textContent = (kind === 'undo' ? 'Undo' : 'Redo') + ' saved as revision ' + result.revision;
  } catch (error) { reviewError(error); }
}
$('undo').addEventListener('click', () => stepHistory('undo', 'pendingUndo', 'undoing'));
$('redo').addEventListener('click', () => stepHistory('redo', 'pendingRedo', 'redoing'));
window.addEventListener('keydown', (e) => {
  const t = e.target;
  if (!(e.ctrlKey || e.metaKey) || e.altKey || t?.isContentEditable || ['INPUT', 'TEXTAREA', 'SELECT'].includes(t?.tagName)) return;
  const k = e.key.toLowerCase();
  if (k === 'z' || k === 'y') {
    e.preventDefault();
    const btn = $((k === 'y' || e.shiftKey) ? 'redo' : 'undo');
    if (btn && !btn.disabled) btn.click();
  }
});

loadState();
</script></body></html>"""


class Workbench:
    def __init__(self, file: Path, out: Path, provider, *, review_store=None,
                 use_retrieval=True, telemetry_dir=Path("telemetry/eval"),
                 law_timeline=None, project_id=None, universe_id=None,
                 episode=None, branch: str = "main", beat: int = 0):
        self.file = file
        self.out = out
        self.provider = provider
        self.text = file.read_bytes().decode("utf-8")
        self.review_store = review_store
        self.telemetry_dir = telemetry_dir
        self.use_retrieval = use_retrieval
        self.law_timeline = law_timeline
        self.project_id = project_id
        self.universe_id = universe_id
        self.episode = episode
        self.branch = branch
        self.beat = int(beat or 0)
        if review_store is not None and review_store.at(0)[0] != self.text:
            raise RevisionError("source file does not match the revision store's original text")
        self.refresh_retrieval()
        try:
            self.house = House.load("books/ling_house")
        except Exception:
            self.house = None
        try:
            self.world = WorldState.load("books/world_state.json")
        except Exception:
            self.world = None
        self.set_passages(self.review_store.current()[1] if self.review_store else self.text)
        self.lens = "irby"
        self.edits = {}
        self._blind_sessions = {}

    def refresh_retrieval(self):
        self.drive = None
        self.retrieval_status = "disabled"
        self.retrieval_state = "disabled"
        if self.use_retrieval:
            from prose_engine.reference_service import prepare_retrieval
            setup = prepare_retrieval("books", "luar", getattr(self.provider, "name", None))
            self.drive, self.influence = setup.drive, setup.influence
            self.retrieval_state, self.retrieval_status = setup.state, setup.message

    def reference_snapshot(self):
        from prose_engine.influence import load_influence
        from prose_engine.reference_policy import PolicyEditor
        root = Path("books")
        from prose_engine.library_indexes import index_path, validate_index
        path = index_path(root, "luar")
        if not path.is_file():
            raise ValueError("LUAR reference index is missing.")
        index = LuarIndex.load(path)
        validate_index(root, "luar", index)
        return PolicyEditor(root).snapshot(index.meta, load_influence(root))

    def set_passages(self, text):
        from prose_engine.conditioner import is_dialogue

        self.paragraphs = chunk_text(text.replace("\r\n", "\n"))
        self.labels = [chunk_label(part) for part in self.paragraphs]
        self.scores = [0 if is_dialogue(part) else len(flag(part)) for part in self.paragraphs]
        self.spans = [
            [] if is_dialogue(part) else [
                {"rule": s.rule, "start": s.start, "end": s.end, "text": s.text, "why": s.why}
                for s in flag(part)
            ]
            for part in self.paragraphs
        ]

    def _gate(self, original: str, text: str, mode: str = "correction", strength: float = 0.5):
        issues = []
        from prose_engine.voice.tics import blacklisted_cliches
        cliches = blacklisted_cliches(text)
        if cliches:
            issues.append("blacklisted cliché: " + ", ".join(cliches[:2]))
        ok, missing = preserves_facts(original, text)
        if not ok:
            issues.append("drops facts: " + ", ".join(missing[:3]))
        overlap = token_overlap(original, text)
        preset = policy(strength)
        max_overlap = get_strength(preset.preset).max_overlap if mode == "correction" else 0.40
        if overlap > max_overlap:
            issues.append(f"overlap {overlap:.2f} > {max_overlap:.2f}")
        kept = sorted(retained(original, text))
        if mode != "correction" and kept:
            issues.append("retained imagery: " + ", ".join(kept[:3]))
        if self.world is not None:
            for phrase, why in self.world.violations(text) + self.world.plausibility(text):
                issues.append(f"canon: '{phrase}' — {why}")
        if self.house is not None:
            for issue in self.house.check_scene([text]):
                issues.append("staging: " + issue)
        from prose_engine.scoped_service import enforce_standalone_world_laws, resolve_default_timeline
        tl = resolve_default_timeline(self.law_timeline)
        if tl:
            law_check = enforce_standalone_world_laws(
                text,
                timeline_path=tl,
                project_id=self.project_id,
                universe_id=self.universe_id,
                episode=self.episode,
                branch=self.branch,
                beat=self.beat,
            )
            for violation in law_check["violations"]:
                issues.append("world law: " + violation)
        return issues, overlap

    def rewrite(self, index: int, strength: float, direction: str = "", mode: str = "correction", treatments=()) -> dict:
        if self.retrieval_state not in ("ready", "disabled"):
            return {"text": "", "accepted": False, "issues": [self.retrieval_status]}
        if index < 0 or index >= len(self.paragraphs):
            return {"text": "", "accepted": False, "issues": ["bad index"]}
        original = self.paragraphs[index]
        preset = policy(strength)
        directive = get_strength(preset.preset).directive
        facts = fact_list(original)
        images = sorted(vehicles(original))
        reference_texts = []
        if self.drive is not None:
            try:
                reference_texts = [
                    hit.text for hit in self.drive.retrieve_passages("workbench", original, max_results=4,
                                                                    influence=self.influence)
                ]
            except Exception as exc:
                self.retrieval_state = "unavailable"
                self.retrieval_status = f"Reference retrieval failed ({type(exc).__name__}): {exc}"
                return {"text": "", "accepted": False, "issues": [self.retrieval_status]}
        from prose_engine.voice.injection import format_injection_prompt
        lens_id = getattr(self, "lens", "irby") or "irby"
        injection = format_injection_prompt(lens_id)
        prompt = (
            "MUST KEEP EXACTLY: " + ", ".join(facts) + "\n\n"
            + directive + "\n\n"
            + (("DIRECTION FOR THIS PASSAGE: " + direction.strip() + "\n\n") if direction.strip() else "")
            + ((self.world.prompt_block() + "\n\n") if self.world is not None else "")
            + ((self.house.prompt_block(original, cad=False) + "\n\n") if self.house is not None else "")
            + ((format_references(reference_texts) + "\n\n") if reference_texts else "")
            + ((injection + "\n\n") if injection else "")
            + "FORBIDDEN IMAGES: " + ", ".join(images) + "\n\n"
            + "ORIGINAL (comparisons removed):\n" + mask(original)
        )
        request = ProseRewriteRequest(
            request_id=f"wb-{index}", project_id="workbench", document_id=self.file.name,
            base_revision=1, target_span_id=f"p{index}", original_text=original,
            category=SpanCategory.GENERAL,
        )

        if mode == "variation":
            variants = []
            for treatment in list(treatments)[:3] or ["nanite_malfunction", "staged", "curse"]:
                prompt_treatment = (
                    f"DIRECTION FROM THE AUTHOR: {direction.strip()}\n\n" if direction.strip() else ""
                ) + "TREATMENT: " + TREATMENTS.get(treatment, treatment) + "\n\n" + directive + "\n\n" \
                    + ((format_references(reference_texts) + "\n\n") if reference_texts else "") \
                    + "STAGE, DO NOT ENUMERATE. Keep every name, number and quoted line.\n\n" \
                    + "PASSAGE:\n" + mask(original)
                try:
                    text = self.provider.generate_rewrite(request, prompt_treatment).strip()
                except BudgetExceeded:
                    raise
                except Exception as exc:
                    variants.append({"treatment": treatment, "text": "", "accepted": False, "issues": [str(exc)]})
                    continue
                issues, overlap = self._gate(original, text, mode=mode, strength=strength)
                issues += personification_issues(text)
                variants.append(
                    {"treatment": treatment, "text": text, "accepted": not issues,
                     "issues": issues, "overlap": round(overlap, 3)}
                )
            return {"variants": variants}
        try:
            text = self.provider.generate_rewrite(request, prompt).strip()
        except BudgetExceeded:
            raise
        except Exception as exc:
            return {"text": "", "accepted": False, "issues": [f"provider error: {exc}"]}

        issues, overlap = self._gate(original, text, mode=mode, strength=strength)
        issues += personification_issues(text)
        tics = tic_counts(text)
        from prose_engine.scoped_service import record_standalone_draft
        record_standalone_draft(
            text,
            original_text=original,
            source_path=self.file,
            route=f"workbench.{mode}",
            provider_name=getattr(self.provider, "name", "unknown"),
            timeline_path=self.law_timeline,
            project_id=self.project_id,
            universe_id=self.universe_id,
            episode=self.episode,
            branch=self.branch,
            beat=self.beat,
            out_dir=self.telemetry_dir,
            issues=issues,
        )
        return {"text": text, "accepted": not issues, "issues": issues, "tics": tics, "overlap": round(overlap, 3)}

    def blind_ab(self, index: int, strength: float = 0.8, direction: str = "") -> dict:
        import random
        import uuid

        if index < 0 or index >= len(self.paragraphs):
            return {"error": "bad index"}
        original = self.paragraphs[index]
        res_cut = self.rewrite(index, strength, direction=direction, mode="correction")
        text_cut = res_cut.get("text") or original

        res_var = self.rewrite(
            index, strength, direction=direction, mode="variation",
            treatments=["nanite_malfunction", "staged", "curse"],
        )
        var_list = res_var.get("variants") or []
        var_text = ""
        var_treatment = "variation"
        for v in var_list:
            if v.get("accepted") and v.get("text"):
                var_text = v["text"]
                var_treatment = f"variation:{v['treatment']}"
                break
        if not var_text and var_list:
            var_text = var_list[0].get("text") or original
            var_treatment = f"variation:{var_list[0].get('treatment', 'variant')}"
        elif not var_text:
            var_text = text_cut

        cand_a = {"id": "cut", "text": text_cut, "provenance": "cut_first"}
        cand_b = {"id": "var", "text": var_text, "provenance": var_treatment}
        shuffled = [cand_a, cand_b]
        random.shuffle(shuffled)

        token = uuid.uuid4().hex[:12]
        self._blind_sessions[token] = {
            "index": index,
            "original": original,
            "option1": shuffled[0],
            "option2": shuffled[1],
        }
        return {
            "token": token,
            "index": index,
            "option1": {"text": shuffled[0]["text"]},
            "option2": {"text": shuffled[1]["text"]},
        }

    def choose_blind_ab(self, token: str, choice: str) -> dict:
        import datetime
        session = self._blind_sessions.get(token)
        if not session:
            return {"error": "invalid or expired token"}
        winner = session["option1"] if choice == "1" else session["option2"]
        loser = session["option2"] if choice == "1" else session["option1"]
        orig = session["original"]

        from prose_engine.guards import token_overlap
        overlap = token_overlap(orig, winner["text"])
        edit_approx = abs(len(winner["text"]) - len(orig)) + round((1.0 - overlap) * max(len(orig.split()), 1))

        record = {
            "ts": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "token": token,
            "index": session["index"],
            "choice": f"option{choice}",
            "winner_provenance": winner["provenance"],
            "loser_provenance": loser["provenance"],
            "overlap_vs_original": round(overlap, 3),
            "edit_distance": edit_approx,
            "original_len": len(orig),
            "winner_len": len(winner["text"]),
        }
        target = self.telemetry_dir / "blind_ab.jsonl"
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")

        return {
            "winner_provenance": winner["provenance"],
            "loser_provenance": loser["provenance"],
            "text": winner["text"],
            "choice": choice,
        }

    def save(self, request: dict) -> dict:
        if self.review_store is None or self.world is None:
            raise RevisionError("configure a revision store and canon before saving")
        action = request.get("action")
        if action in ("undo", "redo"):
            return dispatch(self.review_store, self.world, request)
        base = request.get("base")
        if action not in ("preview", "apply") or type(base) is not int:
            raise RevisionError("preview an edit against a loaded revision")
        text, _ = self.review_store.at(base)
        chunks = chunk_text(text.replace("\r\n", "\n"))
        changes = request.get("edits")
        if not isinstance(changes, dict) or not changes:
            raise RevisionError("there are no changes to preview")
        batch = []
        for index, replacement in sorted(changes.items()):
            if not index.isdecimal() or str(int(index)) != index or int(index) >= len(chunks) or not isinstance(replacement, str):
                raise RevisionError("invalid passage change")
            expected = chunks[int(index)]
            if "\r\n" in text and "\n" not in text.replace("\r\n", ""):
                expected = expected.replace("\n", "\r\n")
                replacement = replacement.replace("\r\n", "\n").replace("\n", "\r\n")
            batch.append({"expected": expected, "replacement": replacement})
        return dispatch(
            self.review_store, self.world, {**request, "edits": batch},
            timeline_path=self.law_timeline, project_id=self.project_id,
            universe_id=self.universe_id, episode=self.episode,
            branch=self.branch, beat=self.beat,
        )


def main() -> int:
    parser = argparse.ArgumentParser()
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--file", help="Standalone file mode")
    source.add_argument("--timeline", help="Open a timeline in the shared composing workspace")
    parser.add_argument("--episode", help="Open an episode when using --timeline")
    parser.add_argument("--books-dir", help="Book library directory for timeline mode")
    parser.add_argument("--out", default="out/workbench")
    parser.add_argument("--provider", default="edits")
    parser.add_argument("--edits", default=None)
    parser.add_argument("--model", default=None)
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--review-store")
    parser.add_argument("--no-retrieval", action="store_true")
    parser.add_argument("--law-timeline", default=None, help="Optional timeline SQLite for standalone world-law enforcement")
    parser.add_argument("--project", default=None, help="Expected project ID for standalone world laws")
    parser.add_argument("--universe", default=None, help="Expected universe ID for standalone world laws")
    parser.add_argument("--branch", default="main", help="Episode branch for standalone world laws")
    parser.add_argument("--beat", type=int, default=0, help="Beat index for standalone world laws")
    args = parser.parse_args()

    if args.timeline:
        from tools.studio_ui import run_server
        options={'books_dir':args.books_dir} if args.books_dir else {}
        run_server(port=args.port, timeline_path=args.timeline, timeline_only=True, initial_episode=args.episode,**options)
        return 0
    if args.episode and not args.law_timeline:
        parser.error("--episode requires --timeline or --law-timeline")
    print('Standalone Workbench: universe world laws active.' if args.law_timeline else 'Standalone Workbench: timeline and universe laws are not connected.',file=sys.stderr)
    provider_options = {"edits_path": args.edits} if args.provider == "edits" else {}
    provider = create_prose_provider(args.provider, model_name=args.model, **provider_options)
    bench = Workbench(Path(args.file), Path(args.out), provider,
                      review_store=RevisionStore(args.review_store) if args.review_store else None,
                      use_retrieval=not args.no_retrieval,
                      law_timeline=args.law_timeline, project_id=args.project,
                      universe_id=args.universe, episode=args.episode,
                      branch=args.branch, beat=args.beat)

    class Handler(BaseHTTPRequestHandler):
        def _send(self, status: int, body: bytes, content_type: str) -> None:
            self.send_response(status)
            self.send_header("content-type", content_type)
            self.send_header("content-length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            if urlparse(self.path).path == "/api/reference-policy":
                try:
                    payload = bench.reference_snapshot()
                    self._send(200, json.dumps(payload).encode("utf-8"), "application/json")
                except Exception as exc:
                    self._send(400, json.dumps({"error": f"Reference settings unavailable: {type(exc).__name__}: {exc}"}).encode("utf-8"), "application/json")
            elif urlparse(self.path).path == "/api/state":
                revision = None
                can_undo = False
                can_redo = False
                if bench.review_store is not None:
                    revision, text, _ = bench.review_store.current()
                    hist = bench.review_store.history_status()
                    can_undo = hist["can_undo"]
                    can_redo = hist["can_redo"]
                    bench.set_passages(text)
                payload = {
                    "scope_status": "unscoped-standalone",
                    "scope_warning": "Timeline, universe laws and episode masks are not connected. Open Workbench with --timeline for scoped work.",
                    "revision": revision,
                    "can_undo": can_undo,
                    "can_redo": can_redo,
                    "retrieval_status": bench.retrieval_status,
                    "retrieval_state": bench.retrieval_state,
                    "file": str(bench.file),
                    "paragraphs": bench.paragraphs,
                    "labels": bench.labels,
                    "scores": bench.scores,
                    "spans": bench.spans,
                    "edits": bench.edits,
                }
                self._send(200, json.dumps(payload).encode("utf-8"), "application/json")
            else:
                self._send(200, PAGE.encode("utf-8"), "text/html; charset=utf-8")

        def do_POST(self):
            length = int(self.headers.get("content-length", 0))
            path = urlparse(self.path).path
            if path == "/api/reference-policy" and (
                self.headers.get("Origin") != f"http://127.0.0.1:{self.server.server_port}" or
                self.headers.get_content_type() != "application/json" or not 0 < length <= 65536
            ):
                self._send(403, b'{"error":"Open reference settings in this Workbench window."}', "application/json")
                return
            data = json.loads(self.rfile.read(length) or b"{}")
            if path == "/api/reference-policy":
                try:
                    from prose_engine.reference_policy import PolicyEditor
                    snapshot = bench.reference_snapshot()
                    PolicyEditor("books").update(data.get("source"), data.get("enabled"), data.get("permissions"),
                        data.get("revision"), {row["id"] for row in snapshot["sources"]})
                    bench.refresh_retrieval()
                    self._send(200, json.dumps({"retrieval_state": bench.retrieval_state,
                        "retrieval_status": bench.retrieval_status}).encode("utf-8"), "application/json")
                except Exception as exc:
                    self._send(400, json.dumps({"error": f"Reference settings were not saved: {type(exc).__name__}: {exc}"}).encode("utf-8"), "application/json")
            elif path == "/api/rewrite":
                result = bench.rewrite(
                    int(data.get("index", 0)),
                    float(data.get("strength", 0.8)),
                    str(data.get("direction", "")),
                    str(data.get("mode", "correction")),
                    data.get("treatments") or (),
                )
                result['scope_status'] = 'unscoped-standalone'
                self._send(200, json.dumps(result).encode("utf-8"), "application/json")
            elif path == "/api/blind_ab":
                result = bench.blind_ab(
                    int(data.get("index", 0)),
                    float(data.get("strength", 0.8)),
                    str(data.get("direction", "")),
                )
                result['scope_status'] = 'unscoped-standalone'
                self._send(200, json.dumps(result).encode("utf-8"), "application/json")
            elif path == "/api/blind_ab/choice":
                result = bench.choose_blind_ab(
                    str(data.get("token", "")),
                    str(data.get("choice", "1")),
                )
                self._send(200, json.dumps(result).encode("utf-8"), "application/json")
            elif path == "/api/label":
                import datetime
                row = {
                    "ts": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                    "index": int(data.get("index", 0)),
                    "decision": str(data.get("decision", "")),
                    "rule": str(data.get("rule", "")),
                    "text": str(data.get("text", ""))[:4000],
                    "passage": str(data.get("passage", ""))[:4000],
                }
                target = bench.telemetry_dir / "labels.jsonl"
                target.parent.mkdir(parents=True, exist_ok=True)
                with target.open("a", encoding="utf-8") as handle:
                    handle.write(json.dumps(row, ensure_ascii=False) + "\n")
                self._send(200, json.dumps({"saved": True}).encode("utf-8"), "application/json")
            elif path == "/api/save":
                try:
                    if self.headers.get("Origin") != f"http://127.0.0.1:{self.server.server_port}":
                        raise RevisionError("invalid request origin")
                    result = bench.save(data)
                    status = 200
                except (ValueError, TypeError, AttributeError, OSError, sqlite3.Error) as exc:
                    result, status = {"error": str(exc)}, 400
                result['scope_status'] = 'unscoped-standalone'
                self._send(status, json.dumps(result).encode("utf-8"), "application/json")
            else:
                self._send(404, b"{}", "application/json")

        def log_message(self, *args):  # quiet
            return

    server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    print(f"workbench: http://127.0.0.1:{args.port}  file={bench.file}  provider={args.provider}")
    server.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
