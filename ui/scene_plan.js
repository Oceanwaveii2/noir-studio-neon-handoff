import { escapeHtml } from './compose.js';

export function currentScenePlan(state) {
  const plan = state.formGraph?.scene_plan;
  const { episode, notebook } = state.episodeState || {};
  return plan && plan.scope.episode === episode?.id && plan.scope.branch === episode.branch
    && plan.timeline_revision === episode.head && plan.notebook_revision === notebook?.revision ? plan : null;
}

export function selectedSceneTurn(state) {
  const plan = currentScenePlan(state);
  if (!plan) return null;
  return plan.turns.find(turn => turn.id === state.bridgeBeatId)
    || plan.turns.find(turn => turn.stage && turn.speakers.length)
    || plan.turns[0];
}

function mediaLink(plan, clip, start, end, label) {
  const query = new URLSearchParams({ ...plan.scope, id: clip });
  const href = `/api/scene-clips/media?${query}#t=${start / 1000},${end / 1000}`;
  return `<a href="${escapeHtml(href)}" target="_blank" rel="noopener">${escapeHtml(label)}</a>`;
}

function renderInputs(plan, turn, state) {
  const disabled = state.dirty || state.busy ? ' disabled' : '';
  if (!plan.inputs) {
    return state.preparation?.turn_sockets
      ? `<label>Attach scene input package <input type="file" accept=".json,application/json" data-attach-scene-inputs${disabled}></label>`
      : '<p>Prepare structure before attaching a scene input package.</p>';
  }
  const pin = plan.inputs.pins[turn.id];
  const structure = turn.structure;
  const library = plan.inputs.library;
  const endpoint = item => plan.form_labels[item.form] || item.form.replaceAll('-', ' ');
  return `<p data-scene-inputs>${escapeHtml(plan.inputs.donor.title)} · ${escapeHtml(library.title)}
    · ${library.eligible} timing sources · ${library.audition_only} audition only</p>
    ${structure?.kind === 'cutaway' ? `<p data-scene-cutaway>${mediaLink(plan, structure.clip,
      structure.evidence.selector.start, structure.evidence.selector.end, 'Complete Cutaway')}
      · ${structure.operator === 'invert_merge' ? 'Reverse convergence' : 'Forward convergence'} · shape only</p>` : ''}
    ${structure?.kind === 'authored_replay' ? `<p data-scene-cutaway>Authored replay · follows
      ${escapeHtml(structure.after.replaceAll('-', ' '))}</p>` : ''}
    ${turn.relationships.length ? `<details><summary>Spouse relationships</summary><ul>
      ${turn.relationships.map(edge => `<li>${escapeHtml(endpoint(edge.from))} → ${escapeHtml(endpoint(edge.to))}
        ${edge.override ? ' · local override' : ''}</li>`).join('')}</ul></details>` : ''}
    ${pin ? `<div data-scene-timing><p>${pin.enabled ? 'Timing and reaction' : 'Detached cue'} ·
      ${mediaLink(plan, pin.clip, ...pin.selection_ms, pin.title)}</p>
      ${pin.enabled ? `<p>${escapeHtml(pin.direction)}</p>` : ''}
      <button type="button" class="v2-tl-btn" data-scene-timing-pin="${escapeHtml(pin.id)}"
        data-enable="${!pin.enabled}"${disabled}>${pin.enabled ? 'Detach timing cue' : 'Reattach timing cue'}</button></div>` : ''}`;
}

export function renderScenePlan(state) {
  const plan = currentScenePlan(state);
  const turn = selectedSceneTurn(state);
  if (!plan || !turn) {
    const error = state.formGraph?.scene_plan_error;
    if (!error && !state.formGraph?.scene_plan) return '';
    return `<section class="v2-inspector-card"><h2>Scene plan</h2>
      <p>${escapeHtml(error || 'Reload the plan for the saved notebook.')}</p>
      <button class="v2-tl-btn" type="button" data-reload-scene-plan>Reload plan</button>
    </section>`;
  }
  const status = turn.frozen ? 'Frozen dialogue' : turn.speakers.length ? 'Eligible speakers' : 'Silent beat';
  return `<section class="v2-inspector-card">
    <h2>Turn Ledger</h2>
    <label>Beat <select data-scene-plan-beat>
      ${plan.turns.map(item => `<option value="${escapeHtml(item.id)}"${item.id === turn.id ? ' selected' : ''}>${escapeHtml(item.id.replaceAll('-', ' '))}</option>`).join('')}
    </select></label>
    <p data-scene-speakers><strong>${status}</strong>${turn.speakers.length ? ' · ' : ''}${turn.speakers.map(item => escapeHtml(item.label)).join(', ')}</p>
    ${turn.speakers.filter(item => item.mind).map(item => `<details><summary>${escapeHtml(item.label)}’s Mind</summary>
      ${item.mind.guidance ? `<ul>${item.mind.guidance.map(line => `<li>${escapeHtml(line)}</li>`).join('')}</ul>`
        : '<p>Guidance withheld for this beat.</p>'}</details>`).join('')}
    ${renderInputs(plan, turn, state)}
    ${turn.rules.length ? `<p>${turn.rules.map(item => escapeHtml(item.label + ' · ' + item.scent)).join(' / ')}</p>` : ''}
    <button type="button" class="v2-tl-btn" data-use-scene-plan ${state.dirty || state.busy ? 'disabled' : ''}>Use planned passage</button>
  </section>`;
}
