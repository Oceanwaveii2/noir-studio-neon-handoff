import { escapeHtml, writerOptionsHtml } from './compose.js';

const PRESETS = {
  stage: 'Turn the saved stage directions into a readable scene. Keep the existing events, speaker identities and protected lines. Clarify action and give each beat room to land.',
  rhythm: 'Polish the pacing and transitions. Let the existing setup breathe before the payoff. Keep the narrator voice, world rules and story order.',
  dialogue: 'Polish the selected dialogue in the established character voice. Keep the underlying intent and all protected wording. Do not add new story information.',
  spring_three_bitches: 'Alternate Spring Break · Three Little Bitches (Rainee 1 Rainee Sade, Rainee 2 Rainee Becky, Rainee 3 Rainee Clarie) driven by Mean Girls pre-26:35 minds, Rainee Peter Griffen, Nurse Franny, tuberose/orange/sandalwood second blast, clothes + red sedan leaving, and Roger Rutgers takeover.',
  tapped_out: 'Rewrite Tapped Out: reuse existing characters on the graph, introduce Holly (Holly Graham), and trigger Stella transforming into Big Tiddy Steve.',
  custom: '',
};

let pending = null;
let upload = null;
const waiting = new Map();

function recoveryKey(state, slot) {
  const scope = state.timeline?.scope;
  return scope?.project_id && scope?.universe_id
    ? ['noir-creation-v1', scope.project_id, scope.universe_id, slot].join(':') : null;
}

function lastCreation(state, slot) {
  const key = recoveryKey(state, slot);
  if (!key) return null;
  try {
    const value = JSON.parse(localStorage.getItem(key));
    if (typeof value?.id === 'string' && typeof value.fingerprint === 'string') return value;
  } catch (_) { /* memory fallback for an unavailable browser store */ }
  return waiting.get(key) || null;
}

export async function rememberCreation(state, slot, intent) {
  const bytes = new TextEncoder().encode(JSON.stringify(intent));
  const fingerprint = Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256', bytes)),
    byte=>byte.toString(16).padStart(2,'0')).join('');
  const previous = lastCreation(state, slot);
  if (previous?.fingerprint === fingerprint) return previous.id;
  const value = {id:crypto.randomUUID(), fingerprint};
  const key = recoveryKey(state, slot);
  if (key) {
    waiting.set(key,value);
    try { localStorage.setItem(key,JSON.stringify(value)); } catch (_) { /* retain in this window */ }
  }
  return value.id;
}

export function confirmCreation(state, slot, id) {
  const key = recoveryKey(state, slot);
  if (!key || lastCreation(state, slot)?.id !== id) return;
  waiting.delete(key);
  try { localStorage.removeItem(key); } catch (_) { /* no persistent record */ }
}

export function renderIntake(state) {
  const task = state.intake || {};
  const status = task.status || 'idle';
  const ready = task.preview;
  const branches = state.timeline?.branches || [{ id: 'main' }];
  const branch = task.branch || 'main';
  const episodes = (state.timeline?.cards || []).filter(e => e.branch === branch);
  const disabled = status === 'reading' || status === 'saving';
  const defaultWriter = task.provider || (state.writers?.some(w => w.id === 'gemini-session') ? 'gemini-session' : 'codex-session');
  const workflowMode = task.workflow_mode || 'auto';
  const runPipeline = task.run_pipeline !== false;
  const canSubmit = !disabled && !state.dirty && (Boolean(ready) || Boolean((task.title || '').trim()));
  return `
    <div class="v2-intake">
      <header class="v2-intake-hero">
        <small>NOIR STUDIO <span></span> SOURCE DESK</small>
        <h1>Get Started</h1>
        <p>Drop a script or start from a prompt. Noir imports the source, links character minds, and can immediately run Gemini + Noir validation.</p>
      </header>
      <div class="v2-intake-grid">
        <section class="v2-intake-panel" aria-labelledby="v2IntakeSourceLabel">
          <h2 id="v2IntakeSourceLabel"><span>01</span> Source (optional for prompt-only)</h2>
          <div id="v2IntakeDrop" class="v2-intake-drop" data-ready="${!!ready}">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" aria-hidden="true"><path d="M6 3h8l4 4v14H6zM14 3v5h5M9 12h6m-6 4h6"/></svg>
            <strong>${escapeHtml(ready?.source.name || task.name || 'Drop a script or manuscript')}</strong>
            <small>${ready ? `${ready.source.format} · ${ready.source.characters.toLocaleString()} text characters` : 'Markdown, TXT, Fountain, PDF or DOCX · up to 32 MB'}</small>
            <button type="button" class="v2-btn" id="v2IntakeBrowse" ${disabled ? 'disabled' : ''}>${ready ? 'Choose another file' : 'Browse files'}</button>
            <input type="file" id="v2IntakeFile" accept=".md,.txt,.fountain,.pdf,.docx" hidden>
          </div>
          ${status === 'reading' ? '<button type="button" class="v2-btn" id="v2IntakeCancel">Cancel reading</button>' : ''}
          ${lastCreation(state,'document') ? `<button type="button" class="v2-btn" id="v2IntakeResume" ${disabled || state.dirty ? 'disabled' : ''}>Recover last import</button>` : ''}
          <p role="status" class="v2-intake-status" data-error="${status === 'error'}">${escapeHtml(task.message || 'Reading a dropped file stays local until you click launch.')}</p>
          ${ready ? `<details class="v2-intake-preview" open><summary>Extracted text${ready.preview_truncated ? ' (beginning)' : ''}</summary>
            <pre tabindex="0">${escapeHtml(ready.text_preview)}</pre></details>` : ''}
        </section>
        <form id="v2IntakeForm" class="v2-intake-panel v2-intake-form" aria-labelledby="v2IntakeBriefLabel">
          <h2 id="v2IntakeBriefLabel"><span>02</span> Episode brief &amp; launch</h2>
          <fieldset ${disabled ? 'disabled' : ''}>
            <label>Episode title<input name="title" required maxlength="200" value="${escapeHtml(task.title || '')}" placeholder="e.g. Spring Break Three Little Bitches"></label>
            <div class="v2-intake-placement">
              <label>Branch<select name="branch">${branches.map(b => `<option value="${escapeHtml(b.id)}" ${b.id === branch ? 'selected' : ''}>${b.id === 'main' ? 'Main timeline' : escapeHtml(b.id)}</option>`).join('')}</select></label>
              <label>Placement<select name="after"><option value="end">At the end</option><option value="start" ${task.after === 'start' ? 'selected' : ''}>At the beginning</option>${episodes.map(e=>`<option value="${escapeHtml(e.id)}" ${task.after === e.id ? 'selected' : ''}>After ${escapeHtml(e.title)}</option>`).join('')}</select></label>
            </div>
            <label>Workflow system<select name="workflow_mode" id="v2IntakeWorkflow">
              <option value="auto" ${workflowMode === 'auto' ? 'selected' : ''}>Auto-detect from file + prompt</option>
              <option value="spring-alternate" ${workflowMode === 'spring-alternate' ? 'selected' : ''}>Spring Break · Three Little Bitches (Rainee Sade/Becky/Clarie + Mean Girls Minds)</option>
              <option value="tapped-out" ${workflowMode === 'tapped-out' ? 'selected' : ''}>Tapped Out · Smart Graph Reuse + Holly + Big Tiddy Steve</option>
              <option value="rewrite" ${workflowMode === 'rewrite' ? 'selected' : ''}>General Noir + Gemini Rewrite &amp; Cook</option>
            </select></label>
            <label>Starting prompt<select id="v2IntakePreset">
              <option value="stage" ${(!task.preset || task.preset === 'stage') ? 'selected' : ''}>From stage directions</option>
              <option value="rhythm" ${task.preset === 'rhythm' ? 'selected' : ''}>Pacing and timing</option>
              <option value="dialogue" ${task.preset === 'dialogue' ? 'selected' : ''}>Dialogue polish</option>
              <option value="spring_three_bitches" ${task.preset === 'spring_three_bitches' ? 'selected' : ''}>Three Little Bitches (Rainee Sade, Becky, Clarie)</option>
              <option value="tapped_out" ${task.preset === 'tapped_out' ? 'selected' : ''}>Tapped Out (Holly + Big Tiddy Steve)</option>
              <option value="custom" ${task.preset === 'custom' ? 'selected' : ''}>Write my own</option>
            </select></label>
            <textarea aria-label="Writing prompt" name="prompt" rows="4" maxlength="500">${escapeHtml(task.prompt ?? PRESETS.stage)}</textarea>
            <label>Writing session<select name="provider">${writerOptionsHtml(state.writers, defaultWriter)}</select></label>
            <label class="v2-intake-run-check"><input type="checkbox" id="v2IntakeRunPipeline" name="run_pipeline" ${runPipeline ? 'checked' : ''}> Run Noir + Gemini pipeline after create (Graph + SlopCritic + Canon + Cook)</label>
            ${ready?.source.pages_requiring_ocr?.length ? `<label><input type="checkbox" name="accept_partial" ${task.accept_partial ? 'checked' : ''}>
              Import the available text and keep the full PDF</label>` : ''}
          </fieldset>
          <p class="v2-stage-sub">Drop a file or write a title + prompt to create the episode and launch Gemini under Noir controls.</p>
          <button type="submit" id="v2IntakeSubmitBtn" class="v2-btn v2-btn-accent" ${canSubmit ? '' : 'disabled'}>${status === 'saving' ? 'Running Noir + Gemini…' : (runPipeline ? 'Create episode &amp; run pipeline' : 'Create episode and open notebook')}</button>
          ${state.dirty ? '<small>Save the current notebook before opening a new episode.</small>' : ''}
        </form>
      </div>
    </div>`;
}

function dataFor(file) {
  return new Promise((resolve,reject) => {
    const fr = new FileReader();
    fr.onload = () => resolve({ name: file.name, base64: String(fr.result).split(',')[1] });
    fr.onerror = () => reject(new Error('Could not read that file.'));
    fr.readAsDataURL(file);
  });
}

export function bindIntake({ store, api, onCreated }) {
  const file = document.getElementById('v2IntakeFile');
  const zone = document.getElementById('v2IntakeDrop');
  const form = document.getElementById('v2IntakeForm');
  const update = (changes, quiet = false) => {
    const state = { intake: { ...store.get().intake, ...changes } };
    return quiet ? store.setQuiet(state) : store.set(state);
  };
  document.getElementById('v2IntakeBrowse')?.addEventListener('click', () => file.click());
  const read = async (selected) => {
    if (!selected || store.get().intake?.status === 'saving') return;
    pending?.abort();
    const controller = new AbortController();
    pending = controller;
    upload = null;
    update({ status: 'reading', name: selected.name, preview: null, accept_partial:false, message: 'Reading the document…' });
    try {
      if (!/\.(md|txt|fountain|pdf|docx)$/i.test(selected.name) || !selected.size || selected.size > 32*1024*1024) {
        throw new Error('Choose a nonempty Markdown, TXT, Fountain, PDF or DOCX file up to 32 MB.');
      }
      const data = await dataFor(selected);
      if (controller.signal.aborted) return;
      const preview = await api.intake({ action: 'intake.preview', document: data }, controller.signal);
      if (controller.signal.aborted) return;
      upload = data;
      const skipped = preview.source.pages_requiring_ocr || [];
      update({ status: 'ready', preview, title: store.get().intake?.title || selected.name.replace(/\.[^.]+$/, '').slice(0,200),
        message: skipped.length ? `Read the available text. Pages ${skipped.join(', ')} contain no selectable text and may need OCR.` : 'Ready. Check the extracted text and choose where the episode goes.' });
    } catch (error) {
      if (!controller.signal.aborted) update({ status: 'error', message: error.message });
    }
  };
  file?.addEventListener('change', () => read(file.files[0]));
  zone?.addEventListener('dragover', (e) => { e.preventDefault(); zone.classList.add('is-over'); });
  zone?.addEventListener('dragleave', () => zone.classList.remove('is-over'));
  zone?.addEventListener('drop', (e) => {
    e.preventDefault();
    zone.classList.remove('is-over');
    const droppedFile = e.dataTransfer?.files?.[0];
    if (droppedFile) {
      read(droppedFile);
      return;
    }
    const droppedText = e.dataTransfer?.getData('text/plain');
    if (droppedText && droppedText.trim()) {
      read(new File([droppedText], 'dropped-script.txt', { type: 'text/plain' }));
    }
  });
  document.getElementById('v2IntakeCancel')?.addEventListener('click', () => {
    pending?.abort();
    update({ status: 'idle', name: '', message: 'Reading cancelled. Choose a file to try again.' });
  });
  form?.addEventListener('input', (e) => {
    if (e.target.name === 'title') {
      const btn = document.getElementById('v2IntakeSubmitBtn');
      const cur = store.get();
      if (btn) btn.disabled = cur.dirty || cur.intake?.status === 'reading' || cur.intake?.status === 'saving'
        || !(cur.intake?.preview || e.target.value.trim());
    }
    if (e.target.name && e.target.name !== 'branch') update({
      [e.target.name]:e.target.type === 'checkbox' ? e.target.checked : e.target.value,
    }, true);
  });
  form?.elements.branch?.addEventListener('change', (e) => update({ branch: e.target.value, after: 'end' }));
  document.getElementById('v2IntakePreset')?.addEventListener('change', (e) => {
    const val = e.target.value;
    form.elements.prompt.value = PRESETS[val] ?? '';
    const wf = form.elements.workflow_mode;
    if (wf && val === 'spring_three_bitches') wf.value = 'spring-alternate';
    else if (wf && val === 'tapped_out') wf.value = 'tapped-out';
    update({ preset: val, prompt: form.elements.prompt.value, workflow_mode: wf?.value || 'auto' }, true);
  });
  form?.addEventListener('submit', async (e) => {
    e.preventDefault();
    const state = store.get();
    const info = state.intake?.preview?.source;
    const hasFile = Boolean(upload && info);
    const brief = Object.fromEntries(new FormData(form));
    brief.accept_partial = brief.accept_partial === 'on';
    brief.run_pipeline = Boolean(form.elements.run_pipeline?.checked);
    if (state.dirty || state.intake?.status === 'saving' || (!hasFile && !(brief.title || '').trim())) return;
    if (hasFile && info.pages_requiring_ocr?.length && !brief.accept_partial) {
      update({ status:'error', message:'Choose whether to import the available text, or run OCR on the PDF first.' });
      return;
    }
    const document = upload;
    const action = hasFile ? 'intake.create' : 'episode.create';
    const slotKey = hasFile ? 'document' : 'episode';
    update({ ...brief, status: 'saving', message: hasFile ? 'Saving the original and preparing the notebook…' : 'Creating episode notebook…' });
    try {
      const fingerprintParts = hasFile
        ? [brief.title.trim(),brief.branch,brief.after,brief.prompt,brief.provider,info.name,info.sha256,info.text_sha256]
        : [brief.title.trim(),brief.branch,brief.after,brief.prompt,brief.provider];
      const id = await rememberCreation(state, slotKey, fingerprintParts);
      const createPayload = {
        action,
        title: brief.title,
        branch: brief.branch,
        after: brief.after,
        prompt: brief.prompt,
        provider: brief.provider,
        ...intakeScope(state),
        request_id: id,
        ...(hasFile ? { document, file_sha256: info.sha256, text_sha256: info.text_sha256, accept_partial: brief.accept_partial } : {}),
      };
      const result = await api.intake(createPayload);
      if (result.state?.episodes && !result.state.episodes.some(episode=>episode.id === result.episode)) {
        update({ status:'error', message:'This import was saved and later removed. Restore it from Timeline.' });
        return;
      }
      let launchResult = null;
      if (brief.run_pipeline) {
        update({ status: 'saving', message: `Episode saved. Running ${brief.provider} + Noir graph/canon/Cook pipeline…` });
        launchResult = await api.intake({
          action: 'intake.launch',
          episode: result.episode,
          prompt: brief.prompt,
          provider: brief.provider,
          workflow_mode: brief.workflow_mode || 'auto',
          max_calls: 2,
          ...intakeScope(store.get()),
        });
      }
      if (!await onCreated({ ...result, launchResult })) throw new Error('The episode was saved. Recover the import to open it.');
      confirmCreation(state, slotKey, id);
      upload = null;
      const doneMsg = launchResult?.notice
        || (result.status === 'REPLAYED' ? `Opened the saved import: ${result.title}.`
          : (hasFile ? `Created ${result.title} · ${result.passages} passages from the source.` : `Created ${result.title}.`));
      update({ status: 'idle', name: '', title: '', preview: null, message: doneMsg });
    } catch (error) {
      update({ status: 'error', message: error.message });
    }
  });
  document.getElementById('v2IntakeResume')?.addEventListener('click', async () => {
    const state = store.get();
    const saved = lastCreation(state,'document');
    if (!saved || state.dirty || state.intake?.status === 'saving') return;
    update({ status:'saving', message:'Looking for the saved import…' });
    try {
      const result = await api.intake({ action:'intake.receipt', request_id:saved.id, ...intakeScope(state) });
      if (result.status !== 'COMMITTED') {
        update({ status:'error', message:'The import hasn’t saved yet. Choose the same file to retry.' });
        return;
      }
      if (result.current.status === 'archived') {
        update({ status:'error', message:'This import was saved and later removed. Restore it from Timeline.' });
        return;
      }
      if (!await onCreated(result.receipt)) throw new Error('The import is saved. Refresh and try opening it again.');
      confirmCreation(state,'document',saved.id);
      upload = null;
      update({ status:'idle', name:'', title:'', preview:null, message:`Opened the saved import: ${result.receipt.title}.` });
    } catch (error) {
      update({ status:'error', message:error.message });
    }
  });
}

function intakeScope(state) {
  const timeline = state.timeline;
  return { project:timeline?.scope?.project_id, universe:timeline?.scope?.universe_id,
    expected_revision:timeline?.history?.revision };
}

export function renderDirectorInspector(state, ep) {
  if (!ep) return '';
  const dir = state.director || {};
  const entries = Array.isArray(state.directorHistory) ? state.directorHistory : [];
  const defaultWriter = dir.provider || (state.writers?.some(w => w.id === 'gemini-session') ? 'gemini-session' : 'codex-session');
  const workflowMode = dir.workflow_mode || 'auto';
  const busy = Boolean(state.busy || dir.running);
  return `
    <div class="v2-inspector-card v2-director-card" id="v2DirectorCard">
      <div class="v2-director-head">
        <h2>AI System Director</h2>
        <span class="v2-director-badge">${escapeHtml(defaultWriter)}</span>
      </div>
      <p class="v2-director-sub">Talk to the AI running Mean Girls Minds, FormGraph, Canon/Slop gates, and Cook on <strong>${escapeHtml(ep.title || ep.id)}</strong>.</p>
      <div class="v2-director-thread" id="v2DirectorThread" role="log" aria-live="polite">
        ${entries.length ? entries.slice(-6).map(item => `
          <article class="v2-director-turn" data-ok="${item.accepted !== false}">
            <div class="v2-director-msg v2-director-user"><strong>You:</strong> ${escapeHtml(item.user_prompt || '')}${item.attachment ? ` <em>(+ ${escapeHtml(item.attachment)})</em>` : ''}</div>
            ${Array.isArray(item.system_steps) && item.system_steps.length ? `<ul class="v2-director-steps">${item.system_steps.map(s => `<li>${escapeHtml(s)}</li>`).join('')}</ul>` : ''}
            ${item.ai_summary ? `<div class="v2-director-msg v2-director-ai"><strong>AI:</strong> ${escapeHtml(item.ai_summary)}</div>` : ''}
          </article>
        `).join('') : '<p class="v2-muted">No AI turns on this episode yet. Drop a reference file or send a direction below.</p>'}
      </div>
      <div id="v2DirectorDrop" class="v2-director-drop" data-has-file="${Boolean(dir.attachment_name)}">
        <span>${dir.attachment_name ? `Attached: ${escapeHtml(dir.attachment_name)}` : 'Drop a note/script here to pass to AI (optional)'}</span>
        <input type="file" id="v2DirectorFile" accept=".md,.txt,.fountain" hidden>
        <button type="button" class="v2-btn" id="v2DirectorAttachBtn" ${busy ? 'disabled' : ''}>${dir.attachment_name ? 'Clear/Change' : 'Attach'}</button>
      </div>
      <form id="v2DirectorForm" class="v2-director-form">
        <select id="v2DirectorWorkflow" name="workflow_mode" aria-label="Director workflow" ${busy ? 'disabled' : ''}>
          <option value="auto" ${workflowMode === 'auto' ? 'selected' : ''}>Auto-detect systems</option>
          <option value="spring-alternate" ${workflowMode === 'spring-alternate' ? 'selected' : ''}>Spring Break · Three Little Bitches</option>
          <option value="tapped-out" ${workflowMode === 'tapped-out' ? 'selected' : ''}>Tapped Out · Holly &amp; Big Tiddy Steve</option>
          <option value="rewrite" ${workflowMode === 'rewrite' ? 'selected' : ''}>General Rewrite + Graph &amp; Cook</option>
        </select>
        <select id="v2DirectorProvider" name="provider" aria-label="Director AI session" ${busy ? 'disabled' : ''}>${writerOptionsHtml(state.writers, defaultWriter)}</select>
        <select id="v2DirectorRefs" name="references" aria-label="190-book reference blend" ${busy ? 'disabled' : ''}>
          <option value="hybrid" ${(dir.references || 'hybrid') === 'hybrid' ? 'selected' : ''}>190 Books: Hybrid (Style + LUAR + Topic)</option>
          <option value="style" ${dir.references === 'style' ? 'selected' : ''}>190 Books: Style</option>
          <option value="luar" ${dir.references === 'luar' ? 'selected' : ''}>190 Books: LUAR Voice</option>
          <option value="topic" ${dir.references === 'topic' ? 'selected' : ''}>190 Books: Topic</option>
          <option value="none" ${dir.references === 'none' ? 'selected' : ''}>No Book References</option>
        </select>
        <textarea id="v2DirectorPrompt" name="prompt" rows="3" maxlength="500" placeholder="Tell the AI what to plan or expand (e.g. 'Expand Scene 4 with Sade, Becky, Clarie and Mean Girls energy')" ${busy ? 'disabled' : ''}>${escapeHtml(dir.prompt || '')}</textarea>
        <div class="v2-director-actions" style="display:flex;gap:8px;flex-wrap:wrap">
          <button type="button" class="v2-btn" id="v2DirectorPlanBtn" ${busy ? 'disabled' : ''}>Plan / Preview Books</button>
          <button type="submit" class="v2-btn v2-btn-accent" id="v2DirectorSendBtn" ${busy || state.dirty ? 'disabled' : ''}>${dir.running ? 'Running AI + Noir systems…' : 'Run &amp; Expand'}</button>
        </div>
        ${state.dirty ? '<small>Save current notebook edits before launching AI run.</small>' : ''}
      </form>
    </div>
  `;
}

export function bindDirectorInspector({ store, api, onAfterRun }) {
  const form = document.getElementById('v2DirectorForm');
  const drop = document.getElementById('v2DirectorDrop');
  const picker = document.getElementById('v2DirectorFile');
  if (!form) return;
  const setDir = (patch, quiet = true) => {
    const next = { director: { ...store.get().director, ...patch } };
    return quiet ? store.setQuiet(next) : store.set(next);
  };
  const readAttach = (file) => {
    if (!file) return;
    const reader = new FileReader();
    reader.onload = () => setDir({ attachment_name: file.name, attachment_text: String(reader.result || '').slice(0, 12000) }, false);
    reader.readAsText(file);
  };
  document.getElementById('v2DirectorAttachBtn')?.addEventListener('click', () => {
    if (store.get().director?.attachment_name) setDir({ attachment_name: '', attachment_text: '' }, false);
    else picker?.click();
  });
  picker?.addEventListener('change', () => readAttach(picker.files[0]));
  drop?.addEventListener('dragover', (e) => { e.preventDefault(); drop.classList.add('is-over'); });
  drop?.addEventListener('dragleave', () => drop.classList.remove('is-over'));
  drop?.addEventListener('drop', (e) => { e.preventDefault(); drop.classList.remove('is-over'); readAttach(e.dataTransfer.files[0]); });
  form.addEventListener('input', (e) => {
    if (e.target.name) setDir({ [e.target.name]: e.target.value }, true);
  });
  document.getElementById('v2DirectorPlanBtn')?.addEventListener('click', async () => {
    const state = store.get();
    const ep = state.episodeState?.episode;
    if (!ep || state.busy || state.director?.running) return;
    const data = Object.fromEntries(new FormData(form));
    const dirState = state.director || {};
    setDir({ ...data, running: true }, false);
    try {
      const result = await api.intake({
        action: 'intake.plan',
        episode: ep.id,
        prompt: String(data.prompt || '').trim(),
        provider: data.provider || 'gemini-session',
        workflow_mode: data.workflow_mode || 'auto',
        references: data.references || 'hybrid',
        craft_mode: 'expand',
        attachment_name: dirState.attachment_name || '',
        attachment_text: dirState.attachment_text || '',
        ...intakeScope(state),
      });
      setDir({ running: false }, true);
      if (Array.isArray(result.director_history)) {
        store.setQuiet({ directorHistory: result.director_history });
      }
      store.set({ notice: { text: result.ai_summary || 'Plan ready (read-only).', tone: 'ok' } });
    } catch (err) {
      setDir({ running: false }, true);
      store.set({ notice: { text: err.message || 'Plan preview failed.', tone: 'err' } });
    }
  });
  form.addEventListener('submit', async (e) => {
    e.preventDefault();
    const state = store.get();
    const ep = state.episodeState?.episode;
    if (!ep || state.dirty || state.busy || state.director?.running) return;
    const data = Object.fromEntries(new FormData(form));
    const dirState = state.director || {};
    setDir({ ...data, running: true }, false);
    try {
      const result = await api.intake({
        action: 'intake.launch',
        episode: ep.id,
        prompt: String(data.prompt || '').trim(),
        provider: data.provider || 'gemini-session',
        workflow_mode: data.workflow_mode || 'auto',
        references: data.references || 'hybrid',
        craft_mode: 'expand',
        attachment_name: dirState.attachment_name || '',
        attachment_text: dirState.attachment_text || '',
        max_calls: 2,
        ...intakeScope(state),
      });
      setDir({ running: false, prompt: '', attachment_name: '', attachment_text: '' }, true);
      if (Array.isArray(result.director_history)) {
        store.setQuiet({ directorHistory: result.director_history });
      }
      await onAfterRun(result);
    } catch (err) {
      setDir({ running: false }, true);
      store.set({ notice: { text: err.message || 'AI pipeline run failed.', tone: 'err' } });
    }
  });
}
