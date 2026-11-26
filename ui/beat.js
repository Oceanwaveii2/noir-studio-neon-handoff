/* Noir Fiction Studio v2 — M5 Beat Map & Rhythm Direction */

import { escapeHtml, writerOptionsHtml } from './compose.js';

const activeRun = (run) => ['QUEUED', 'RUNNING'].includes(run?.status);
const polling = new WeakMap();

function pollRun(store, api) {
  const s = store.get();
  const run = s.writingRun;
  if (polling.has(store) || !activeRun(run) || s.view !== 'story' || s.storySubtab !== 'rhythm') return;
  const timer = setTimeout(async () => {
    try {
      if (store.get().episodeId !== run.episode || store.get().writingRun?.id !== run.id) return;
      const next = await api.episodeCommand({ action: 'run.status', episode: run.episode, request_id: run.id });
      const latest = store.get();
      if (latest.episodeId === run.episode && latest.writingRun?.id === run.id &&
          JSON.stringify(next) !== JSON.stringify(latest.writingRun)) store.set({ writingRun: next });
    } catch (_) {
      // Retry the read on a reconnect, never the writing request.
    } finally {
      polling.delete(store);
      pollRun(store, api);
    }
  }, 1000);
  polling.set(store, timer);
}

const actLabels = {
  three_act: '3-Act',
  six_act: '6-Act',
  episodic_comedy: 'Episodic Comedy A/B-Plot',
  custom: 'Custom',
};

export function renderActStructure(state, { compact = false } = {}) {
  const structure = state.storyStructure;
  if (!structure || structure.episode !== state.episodeId) return '<p class="v2-hint">Open a saved episode for timing targets.</p>';
  const points = structure.points || [];
  const point = points.find((row) => row.id === structure.selected);
  const view = state.structureViewpoint || '';
  const diff = structure.epistemic;
  const plotted = points.filter((row) => row.tension !== null);
  const x = (row) => 12 + 296 * (row.number - 1) / Math.max(1, points.length - 1);
  const y = (row) => 56 - 9 * row.tension;
  return `<section class="sg-structure ${compact ? 'is-compact' : ''}" data-act-structure>
    ${compact ? '' : '<h3>Act Structure &amp; Event Timing</h3>'}
    <div class="sg-structure-filters">
      <label>Passage <select data-structure-passage ${points.length ? '' : 'disabled'}>
        ${points.map((row) => `<option value="${escapeHtml(row.id)}" ${row === point ? 'selected' : ''}>Passage ${row.number}${row.act ? ` · ${escapeHtml(row.act)}` : ''}</option>`).join('')}
      </select></label>
      <label>Viewpoint <select data-structure-viewpoint>
        <option value="">Choose a character</option>
        ${(state.formGraph?.junctions || []).map((row) => `<option value="${escapeHtml(row.character_id)}" ${row.character_id === view ? 'selected' : ''}>${escapeHtml(row.label || row.character_id)}</option>`).join('')}
      </select></label>
    </div>
    ${compact ? (point ? `<p class="v2-hint">${escapeHtml(actLabels[structure.preset])} · Sight ${point.sight ? 'open' : 'closed'} · Audio ${point.audio ? 'open' : 'closed'}${point.duration_ms === null ? '' : ` · ${point.duration_ms} ms`}</p>` : '') : `
      ${plotted.length ? `<svg viewBox="0 0 320 68" class="sg-tension-curve" role="img" aria-label="Saved tension targets">
        <path d="M 12 56 H 308" stroke="currentColor" opacity=".35"></path>
        <polyline points="${plotted.map((row) => `${x(row)},${y(row)}`).join(' ')}" fill="none" stroke="#ffb07d" stroke-width="2"></polyline>
        ${plotted.map((row) => `<circle cx="${x(row)}" cy="${y(row)}" r="4" fill="#90e9cd"><title>Passage ${row.number}, tension ${row.tension}/5</title></circle>`).join('')}
      </svg>` : ''}
      <form data-structure-edit>
        <label>Structure preset <select name="preset">${Object.entries(actLabels).map(([id, label]) => `<option value="${id}" ${id === structure.preset ? 'selected' : ''}>${label}</option>`).join('')}</select></label>
        ${point ? `<label>Turning point <input name="marker" maxlength="80" value="${escapeHtml(point.marker)}" placeholder="${escapeHtml(point.act || 'Add a turning point')}"></label>
          <label>Tension (0–5) <input name="tension" type="number" min="0" max="5" value="${point.tension ?? ''}"></label>
          <label>Duration (ms) <input name="duration" type="number" min="0" max="3600000" value="${point.duration_ms ?? ''}"></label>
          <label>Pacing <select name="pace">${optionsHtml(['neutral', 'slow', 'measured', 'fast'], point.pace)}</select></label>
          <label>Rhythm direction <textarea name="direction" rows="2" maxlength="500">${escapeHtml(point.direction)}</textarea></label>
          <label class="sg-portal-toggle"><span>Sightline open</span><input name="sight" type="checkbox" ${point.sight ? 'checked' : ''}></label>
          <label class="sg-portal-toggle"><span>Audio open</span><input name="audio" type="checkbox" ${point.audio ? 'checked' : ''}></label>` : ''}
        <button type="submit" class="v2-btn" ${state.episodeState?.episode?.status !== 'draft' ? 'disabled' : ''}>Save timing targets</button>
      </form>`}
    ${diff ? `<details class="sg-epistemic-diff">
      <summary>Epistemic ToM Diff · ${diff.known.length} known · ${diff.withheld.length} withheld</summary>
      ${['known', 'withheld'].map((key) => `<div><strong>${key === 'known' ? 'Available to viewpoint' : 'World events withheld from viewpoint'}</strong>
        <ul>${diff[key].slice(0, 20).map((item) => `<li>${escapeHtml(item.text)}</li>`).join('') || '<li>None at this cutoff</li>'}</ul></div>`).join('')}
    </details>` : ''}
  </section>`;
}

const structureRequests = new WeakMap();

export async function refreshActStructure(store, api, fields = {}) {
  const s = store.get();
  const ep = s.episodeState?.episode;
  if (!ep || ep.id !== s.episodeId) return;
  const request = {};
  structureRequests.set(store, request);
  try {
    const structure = await api.beatRhythmAction({
      action: 'structure_open', episode: ep.id, timeline_revision: ep.head,
      passage: s.storyStructure?.selected, viewpoint: s.structureViewpoint || null, ...fields,
    });
    const latest = store.get();
    if (structureRequests.get(store) === request && latest.episodeId === ep.id
        && latest.episodeState?.episode?.head === ep.head) store.set({ storyStructure: structure });
  } catch (error) {
    if (structureRequests.get(store) === request && store.get().episodeId === ep.id) {
      store.set({ notice: { text: error.message, tone: 'err' } });
    }
  }
}

export function bindActStructure(store, api, root = document) {
  root.querySelectorAll('[data-act-structure]').forEach((section) => {
    section.querySelector('[data-structure-passage]')?.addEventListener('change', (event) => {
      void refreshActStructure(store, api, { passage: event.target.value });
    });
    section.querySelector('[data-structure-viewpoint]')?.addEventListener('change', (event) => {
      store.setQuiet({ structureViewpoint: event.target.value });
      void refreshActStructure(store, api);
    });
    section.querySelector('[data-structure-edit]')?.addEventListener('submit', (event) => {
      event.preventDefault();
      const structure = store.get().storyStructure;
      if (!structure) return;
      const values = new FormData(event.target);
      const number = (key) => values.get(key) === '' ? null : Number(values.get(key));
      const point = structure.selected ? {
        marker: values.get('marker'), tension: number('tension'), duration_ms: number('duration'),
        pace: values.get('pace'), direction: values.get('direction'),
        sight: values.has('sight'), audio: values.has('audio'),
      } : null;
      void refreshActStructure(store, api, { action: 'structure_save', revision: structure.revision,
        preset: values.get('preset'), point });
    });
  });
}

function optionsHtml(list, current) {
  return list
    .map((item) => `<option value="${escapeHtml(item)}" ${current === item ? 'selected' : ''}>${escapeHtml(item)}</option>`)
    .join('');
}

export function renderBeatStage(state) {
  const ep = state.episodeState?.episode;
  const beatMap = state.beatMap;
  const scenes = beatMap?.scenes || [];
  const allBeats = beatMap?.beats || [];
  const activeSceneId = state.beatSceneFilter || '';
  const visibleBeats = activeSceneId
    ? allBeats.filter((b) => b.scene_id === activeSceneId)
    : allBeats;
  const selectedIds = new Set(state.selectedBeatIds || []);
  const outline = state.directorOutline;
  const run = state.writingRun;

  if (!ep) {
    return `
      <section class="v2-graph-empty">
        <h2>Select an episode</h2>
        <p>Choose an episode from the left rail to inspect its beat map and rhythm direction.</p>
      </section>
    `;
  }

  return `
    <div class="v2-beat-shell">
      <section class="v2-beat-toolbar">
        <div class="v2-beat-title-group">
          <h1>Beat Map & Rhythm</h1>
          <span>${escapeHtml(ep.title)} · ${scenes.length} ${scenes.length === 1 ? 'scene' : 'scenes'} · ${allBeats.length} ${allBeats.length === 1 ? 'beat' : 'beats'}</span>
        </div>
        <div class="v2-graph-controls">
          <button type="button" class="v2-tl-btn" id="v2BeatReloadBtn" ${state.busy ? 'disabled' : ''}>Reload Beat Map</button>
          ${selectedIds.size ? `<button type="button" class="v2-tl-btn" id="v2BeatClearSelBtn">Clear (${selectedIds.size})</button>` : ''}
        </div>
      </section>

      ${outline ? `
        <details class="v2-beat-group-bar">
          <summary>Episode plan</summary>
          ${outline.acts.map(act => `<div><strong>${escapeHtml(act.title)}</strong>
            <ul>${act.scenes.map(scene => `<li>${escapeHtml(scene.title)} · ${scene.beats.length} passages</li>`).join('')}</ul>
          </div>`).join('')}
        </details>
      ` : ''}

      ${scenes.length ? `
        <section class="v2-beat-scenes" aria-label="Scene filter">
          <button type="button" class="v2-scene-chip" data-beat-scene="" aria-pressed="${!activeSceneId ? 'true' : 'false'}">
            All scenes (${allBeats.length})
          </button>
          ${scenes.map((sc) => `
            <button
              type="button"
              class="v2-scene-chip"
              data-beat-scene="${escapeHtml(sc.id)}"
              aria-pressed="${activeSceneId === sc.id ? 'true' : 'false'}"
              title="${escapeHtml(sc.title)}"
            >${escapeHtml(sc.title)} (${sc.beats?.length ?? 0})</button>
          `).join('')}
        </section>
      ` : ''}

      ${selectedIds.size ? `
        <section class="v2-beat-group-bar" aria-label="Beat-group preview and adjust">
          <strong>${selectedIds.size} ${selectedIds.size === 1 ? 'beat' : 'beats'} selected for the director</strong>
          <div class="v2-beat-group-row">
            <input
              type="text"
              id="v2BeatGroupInstruction"
              class="v2-beat-group-input"
              placeholder="Direction for selected beats (e.g. tighten pacing, heighten tension)…"
              value="${escapeHtml(state.beatGroupInstruction || '')}"
            >
            <label>Writer <select id="v2BeatWriter">
              ${writerOptionsHtml(state.writers, state.beatWriter || 'codex-session')}
            </select></label>
            <label>Book craft <select id="v2BeatBooks">${[['none','No books'],['topic','Topic'],['luar','LUAR'],['style','Style']].map(([key,label])=>`<option value="${key}" ${(state.proseRefMode || 'none')===key?'selected':''}>${label}</option>`).join('')}</select></label>
            <button type="button" class="v2-tl-btn" id="v2BeatGroupPreviewBtn" ${state.busy ? 'disabled' : ''}>Preview direction</button>
            <button type="button" class="v2-tl-btn v2-tl-btn-primary" id="v2BeatGroupAdjustBtn" ${state.busy || activeRun(run) ? 'disabled' : ''}>Cook to draft</button>
          </div>
          ${state.beatPreparing ? '<p role="status">Preparing the selected passages and checking eligible references…</p>' : ''}
          ${state.beatGroupPreview ? `<pre class="v2-beat-proposal">${escapeHtml(state.beatGroupPreview)}</pre>` : ''}
        </section>
      ` : ''}

      ${run ? `<section class="v2-beat-group-bar" aria-label="Writing run" aria-live="polite">
        <strong>${run.status === 'COMPLETED' ? (run.generation_receipt ? 'Generated draft saved' : 'Saved result with unverified generation') : run.cancel_requested && activeRun(run) ? 'Stopping after the current passage' :
          {QUEUED:'Waiting to write',RUNNING:'Writing the scene',PARTIAL:'Stopped with partial results',
           PRESERVED:'Selected passages are fully protected',
           CANCELLED:'Run stopped',STALE:'Saved episode changed',UNKNOWN:'Previous writer outcome unknown'}[run.status] || 'Writing run'}</strong>
        <div>${run.completed} of ${run.total} passages ready · ${run.parts.filter(p => p.locked).length} frozen</div>
        ${run.reason ? `<div>${escapeHtml(run.reason)}</div>` : ''}
        <div class="v2-beat-group-row">
          ${activeRun(run) && !run.cancel_requested ? '<button class="v2-tl-btn" id="v2RunCancel">Stop run</button>' : ''}
          ${run.resume_available ? '<button class="v2-tl-btn" id="v2RunResume">Resume saved run</button>' : ''}
          ${run.draft_id ? '<button class="v2-tl-btn v2-tl-btn-primary" id="v2RunOpenDraft">Open saved draft</button>' : ''}
        </div>
      </section>` : ''}

      ${!visibleBeats.length ? `
        <section class="v2-graph-empty">
          <h2>No beat passages found</h2>
          <p>This episode has no mapped beat passages yet. Edit or split the script in Compose first.</p>
        </section>
      ` : `
        <section class="v2-beat-list" aria-label="Beat passages">
          ${visibleBeats.slice(0, 150).map((b) => {
            const isSelected = selectedIds.has(b.id);
            const raw = (b.text || '').trim();
            const excerpt = raw.length > 260 ? `${raw.slice(0, 260)}…` : raw;
            const status = b.anchor?.status || b.timing || 'unverified';
            const pillCls = ['reviewed', 'pinned', 'source-verified'].includes(status) ? 'v2-pill-finished' : 'v2-pill-draft';
            const beatNoise = b.noise_mode || (state.director?.noise_mode || '50');
            const noiseLabel = beatNoise === '0' ? '0% LOCK' : beatNoise === '25' ? '25% TIGHT' : beatNoise === '100' ? '100% WILD' : '50% BAL';
            return `
              <article class="v2-beat-card ${isSelected ? 'is-selected' : ''}" data-beat-id="${escapeHtml(b.id)}">
                <div class="v2-beat-card-head">
                  <label class="v2-beat-card-meta">
                    <input type="checkbox" data-beat-check="${escapeHtml(b.id)}" ${isSelected ? 'checked' : ''}>
                    <span>Beat #${b.number} · scope ${b.scope_beat}</span>
                  </label>
                  <div style="display:flex;gap:6px;align-items:center">
                    <span class="v2-pill v2-pill-draft" title="Discrete Diffusion Noise Mode">${noiseLabel}</span>
                    <span class="v2-pill ${pillCls}">${escapeHtml(status === 'source-verified' ? 'Verified from script' : status)}</span>
                  </div>
                </div>
                <p class="v2-beat-card-excerpt">${escapeHtml(excerpt)}</p>
              </article>
            `;
          }).join('')}
          ${visibleBeats.length > 150 ? `<p class="v2-muted">Showing first 150 of ${visibleBeats.length} beats. Select a scene above to narrow.</p>` : ''}
        </section>
      `}
    </div>
  `;
}

export function renderBeatInspector(state) {
  const ep = state.episodeState?.episode;
  const rhythm = state.beatRhythm;
  const prof = rhythm?.profile || {};
  const selectedIds = state.selectedBeatIds || [];
  const beatMap = state.beatMap;
  const singleBeat = selectedIds.length === 1
    ? (beatMap?.beats || []).find((b) => b.id === selectedIds[0])
    : null;
  const graphEvidence = beatMap?.graph_evidence && !Array.isArray(beatMap.graph_evidence)
    ? beatMap.graph_evidence
    : null;
  const evidence = Array.isArray(beatMap?.graph_evidence)
    ? beatMap.graph_evidence
    : (state.timelineEvents || []).filter((ev) => ev.status === 'approved');

  if (!ep) {
    return `
      <div class="v2-inspector-card">
        <h2>Beat Direction</h2>
        <p class="v2-muted">Select an episode to edit beat rhythm and anchors.</p>
      </div>
    `;
  }

  return `
    <div class="v2-inspector-card">
      <h2>Beat Direction (beat ${state.beat})</h2>
      <div class="v2-tl-insp-grid">
        <div class="v2-muted" style="font-size:12px">
          Status: ${escapeHtml(rhythm?.status || 'unset')} · rev ${rhythm?.revision ?? 0}
        </div>
        <div class="v2-rhythm-two-col">
          <label class="v2-tl-insp-field">
            Scene / Intent
            <select id="v2RhythmIntent">
              ${optionsHtml(['scene', 'setup', 'escalation', 'turn', 'payoff', 'aftermath', 'transition'], prof.intent || 'scene')}
            </select>
          </label>
          <label class="v2-tl-insp-field">
            Pace
            <select id="v2RhythmPace">
              ${optionsHtml(['neutral', 'slow', 'measured', 'brisk', 'urgent'], prof.pace || 'neutral')}
            </select>
          </label>
          <label class="v2-tl-insp-field">
            Tension Start
            <input id="v2RhythmTensionStart" type="number" min="1" max="10" placeholder="1-10" value="${prof.tension_start ?? ''}">
          </label>
          <label class="v2-tl-insp-field">
            Tension End
            <input id="v2RhythmTensionEnd" type="number" min="1" max="10" placeholder="1-10" value="${prof.tension_end ?? ''}">
          </label>
          <label class="v2-tl-insp-field">
            Pause
            <select id="v2RhythmPause">
              ${optionsHtml(['neutral', 'none', 'brief', 'beat', 'long'], prof.pause || 'neutral')}
            </select>
          </label>
          <label class="v2-tl-insp-field">
            Comedy
            <select id="v2RhythmComedy">
              ${optionsHtml(['none', 'dry', 'banter', 'absurd', 'escalation'], prof.comedy || 'none')}
            </select>
          </label>
          <label class="v2-tl-insp-field">
            Cadence
            <select id="v2RhythmCadence">
              ${optionsHtml(['neutral', 'clipped', 'flowing', 'staccato', 'lyrical'], prof.cadence || 'neutral')}
            </select>
          </label>
          <label class="v2-tl-insp-field">
            Transition
            <select id="v2RhythmTransition">
              ${optionsHtml(['neutral', 'hard_cut', 'bridge', 'linger', 'echo'], prof.transition || 'neutral')}
            </select>
          </label>
        </div>
        <label class="v2-tl-insp-field">
          Author note / override
          <textarea id="v2RhythmOverride" rows="2" placeholder="Optional rhythm guidance…">${escapeHtml(prof.author_override || '')}</textarea>
        </label>
        <div class="v2-tl-insp-row">
          <button type="button" class="v2-tl-btn v2-tl-btn-primary" id="v2RhythmSaveBtn" ${state.busy ? 'disabled' : ''}>Save Direction</button>
          <button type="button" class="v2-tl-btn" id="v2RhythmUndoBtn" ${state.busy || !rhythm?.can_undo ? 'disabled' : ''}>Undo</button>
          <button type="button" class="v2-tl-btn" id="v2RhythmRedoBtn" ${state.busy || !rhythm?.can_redo ? 'disabled' : ''}>Redo</button>
        </div>
      </div>
    </div>

    <div class="v2-inspector-card">
      <h2>Beat Anchor</h2>
      ${graphEvidence ? `
        <div class="v2-muted" style="font-size:11px;margin-bottom:8px">
          Graph evidence: ${graphEvidence.matched_passages ?? 0}/${graphEvidence.beat_count ?? 0} matched · ${escapeHtml(graphEvidence.timing || 'unverified')}
        </div>
      ` : ''}
      ${singleBeat ? `
        <div class="v2-tl-insp-grid">
          <div class="v2-graph-kv">
            <strong>Passage #${singleBeat.number}</strong>
            <small>Anchor: ${escapeHtml(singleBeat.anchor?.status || 'unverified')} · beat ${singleBeat.anchor?.beat ?? 0}</small>
          </div>
          <label class="v2-tl-insp-field">
            Bind approved event
            <select id="v2AnchorEventSelect">
              <option value="">Choose approved event…</option>
              ${evidence.map((ev) => `<option value="${escapeHtml(ev.id)}" ${singleBeat.anchor?.id === ev.id ? 'selected' : ''}>${escapeHtml(ev.id)} (beat ${ev.beat})</option>`).join('')}
            </select>
          </label>
          <div class="v2-tl-insp-row">
            <button type="button" class="v2-tl-btn v2-tl-btn-primary" id="v2AnchorBindBtn" ${state.busy || !evidence.length ? 'disabled' : ''}>Bind Anchor</button>
            <button type="button" class="v2-tl-btn" id="v2AnchorUnbindBtn" ${state.busy || !singleBeat.anchor?.id ? 'disabled' : ''}>Unbind</button>
          </div>
        </div>
      ` : `
        <p class="v2-muted">Select exactly one beat passage on the left to bind or unbind a canon event anchor.</p>
      `}
    </div>
  `;
}

export function bindBeatEvents({ store, api, onReloadBeatData, onOpenDraft, onJumpToPassage }) {
  pollRun(store, api);
  document.getElementById('v2BeatReloadBtn')?.addEventListener('click', () => onReloadBeatData());

  document.getElementById('v2BeatClearSelBtn')?.addEventListener('click', () => {
    store.set({ selectedBeatIds: [], beatGroupPreview: '' });
  });

  document.querySelectorAll('[data-beat-scene]').forEach((btn) => {
    btn.addEventListener('click', () => {
      window.NOIR_FX?.trigger('NODE_SELECT', { el: btn, badgeText: 'Scene' });
      store.set({ beatSceneFilter: btn.dataset.beatScene });
    });
  });

  const toggleBeat = (id, multi) => {
    const cur = store.get().selectedBeatIds || [];
    let next;
    if (multi) {
      next = cur.includes(id) ? cur.filter((x) => x !== id) : [...cur, id];
    } else {
      next = cur.length === 1 && cur[0] === id ? [] : [id];
    }
    store.set({ selectedBeatIds: next, beatGroupPreview: '' });
    onJumpToPassage?.(id);
  };

  document.querySelectorAll('[data-beat-check]').forEach((cb) => {
    cb.addEventListener('click', (e) => {
      e.stopPropagation();
      toggleBeat(cb.dataset.beatCheck, true);
    });
  });

  document.querySelectorAll('.v2-beat-card[data-beat-id]').forEach((card) => {
    card.addEventListener('click', (e) => {
      if (e.target.tagName === 'INPUT') return;
      toggleBeat(card.dataset.beatId, e.shiftKey || e.ctrlKey || e.metaKey);
    });
  });

  // Beat Rhythm Save / Undo / Redo
  const readRhythmProfile = () => {
    const ts = document.getElementById('v2RhythmTensionStart')?.value.trim();
    const te = document.getElementById('v2RhythmTensionEnd')?.value.trim();
    const curProf = store.get().beatRhythm?.profile || {};
    return {
      ...curProf,
      intent: document.getElementById('v2RhythmIntent')?.value || 'scene',
      pace: document.getElementById('v2RhythmPace')?.value || 'neutral',
      tension_start: ts ? Number(ts) : null,
      tension_end: te ? Number(te) : null,
      pause: document.getElementById('v2RhythmPause')?.value || 'neutral',
      comedy: document.getElementById('v2RhythmComedy')?.value || 'none',
      cadence: document.getElementById('v2RhythmCadence')?.value || 'neutral',
      transition: document.getElementById('v2RhythmTransition')?.value || 'neutral',
      author_override: document.getElementById('v2RhythmOverride')?.value || '',
      source_id: curProf.source_id || 'author',
    };
  };

  const stepRhythm = async (action, profile) => {
    const s = store.get();
    const ep = s.episodeState?.episode;
    if (!ep) return;
    store.set({ busy: true });
    try {
      const next = await api.beatRhythmAction({
        action,
        episode: ep.id,
        beat: s.beat,
        timeline_revision: ep.head,
        revision: s.beatRhythm?.revision ?? 0,
        ...(profile ? { profile } : {}),
      });
      store.set({
        busy: false,
        beatRhythm: next,
        notice: { text: `Beat direction ${action}d (rev ${next.revision}).`, tone: 'ok' },
      });
    } catch (err) {
      store.set({ busy: false, notice: { text: err.message, tone: 'err' } });
    }
  };

  document.getElementById('v2RhythmSaveBtn')?.addEventListener('click', () => stepRhythm('save', readRhythmProfile()));
  document.getElementById('v2RhythmUndoBtn')?.addEventListener('click', () => stepRhythm('undo'));
  document.getElementById('v2RhythmRedoBtn')?.addEventListener('click', () => stepRhythm('redo'));

  document.getElementById('v2BeatGroupInstruction')?.addEventListener('input', e =>
    store.setQuiet({ beatGroupInstruction: e.target.value, beatGroupPreview: '' }));
  document.getElementById('v2BeatWriter')?.addEventListener('change', e =>
    store.setQuiet({ beatWriter: e.target.value }));
  document.getElementById('v2BeatBooks')?.addEventListener('change', e =>
    store.set({ proseRefMode:e.target.value, beatGroupPreview:'' }));

  const runBeatGroup = async (action) => {
    const s = store.get();
    const ep = s.episodeState?.episode;
    if (!ep || !s.beatMap || !(s.selectedBeatIds || []).length) return;
    if (s.dirty || !s.episodeState?.notebook || s.episodeState.notebook.stale) {
      store.set({ notice: { text: 'Save the current manuscript and protection settings first.', tone: 'warn' } });
      return;
    }
    const request = {
      action, episode: ep.id, revision: ep.head, branch: s.beatMap.branch,
      project: s.beatMap.project_id, universe: s.beatMap.universe_id,
      source_sha256: s.beatMap.source_sha256, anchor_token: s.beatMap.anchor_token,
      notebook_revision: s.episodeState.notebook.revision, viewpoint: s.beatMap.viewpoint || null,
      beats: s.beatMap.beats.filter(b => s.selectedBeatIds.includes(b.id)).map(b => b.id),
      direction: s.beatGroupInstruction || '', provider: s.beatWriter || 'codex-session',
      references: s.proseRefMode || 'none', reference_delivery: 'cadence', scene_function: s.proseSceneFn || 'scene',
    };
    if (action === 'run.start') {
      // Keep the same ID after a lost response; only an explicit new run gets a new one.
      const key = JSON.stringify(request);
      request.request_id = s.pendingWritingRun?.key === key ? s.pendingWritingRun.id : crypto.randomUUID();
      store.setQuiet({ pendingWritingRun: { key, id: request.request_id } });
    }
    store.set({ busy: true, beatPreparing:true });
    try {
      const res = await api.episodeCommand(request);
      if (store.get().episodeId !== ep.id) return;
      if (action === 'director.preview') {
        const lines = res.director.choices.map((item, i) => {
          const name = item.beat.goal || `Passage ${item.beat.number}`;
          const changes = Object.entries(item.changes).map(([k,v]) => `${k.replaceAll('_',' ')}: ${v.before ?? 'unset'} → ${v.after}`);
          return `${name} · cut ${item.beat.cutoff}\n${res.parts[i].locked ? 'Frozen: keep exact text.' :
            changes.join(' · ') || 'Use the direction and existing rhythm.'}`;
        });
        store.set({ busy: false, beatPreparing:false, beatGroupPreview: lines.join('\n\n') +
          `\n\n${res.planned_attempts} writer call(s) planned. Reveal timing and frozen text stay fixed.` });
      } else {
        store.set({ busy: false, beatPreparing:false, writingRun: res, pendingWritingRun: null });
      }
    } catch (err) {
      if (store.get().episodeId === ep.id) store.set({ busy: false, beatPreparing:false, notice: { text: err.message, tone: 'err' } });
    }
  };

  document.getElementById('v2BeatGroupPreviewBtn')?.addEventListener('click', () => runBeatGroup('director.preview'));
  document.getElementById('v2BeatGroupAdjustBtn')?.addEventListener('click', () => runBeatGroup('run.start'));
  const manageRun = async (action) => {
    const run = store.get().writingRun;
    if (!run) return;
    try {
      if (action === 'open') {
        await onOpenDraft?.(run.draft_id);
      } else {
        const result = await api.episodeCommand({ action, episode: run.episode, request_id: run.id });
        if (store.get().episodeId === run.episode) store.set({ writingRun: result });
      }
    } catch (err) { store.set({ notice: { text: err.message, tone: 'err' } }); }
  };
  document.getElementById('v2RunCancel')?.addEventListener('click', () => manageRun('run.cancel'));
  document.getElementById('v2RunResume')?.addEventListener('click', () => manageRun('run.resume'));
  document.getElementById('v2RunOpenDraft')?.addEventListener('click', () => manageRun('open'));

  // Beat Anchors Bind / Unbind
  const runAnchor = async (action) => {
    const s = store.get();
    const ep = s.episodeState?.episode;
    const passage = s.selectedBeatIds?.[0];
    if (!ep || !passage || !s.beatMap) return;
    const event = document.getElementById('v2AnchorEventSelect')?.value || '';
    if (action === 'bind' && !event) {
      store.set({ notice: { text: 'Choose an approved event first.', tone: 'warn' } });
      return;
    }
    store.set({ busy: true });
    try {
      const res = await api.beatAnchorsAction({
        action,
        episode: ep.id,
        revision: ep.head,
        passage,
        event,
        viewpoint: s.viewpoint || null,
        token: s.beatMap.anchor_token,
      });
      store.set({
        busy: false,
        beatMap: res.mapping || s.beatMap,
        notice: { text: action === 'bind' ? `Bound anchor to ${event}.` : 'Unbound beat anchor.', tone: 'ok' },
      });
    } catch (err) {
      store.set({ busy: false, notice: { text: err.message, tone: 'err' } });
    }
  };

  document.getElementById('v2AnchorBindBtn')?.addEventListener('click', () => runAnchor('bind'));
  document.getElementById('v2AnchorUnbindBtn')?.addEventListener('click', () => runAnchor('unbind'));
}
