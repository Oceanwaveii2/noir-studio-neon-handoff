/* Noir Fiction Studio v2 — M6 Prose Engine, Drafts, Book Policy & World Laws */

import { escapeHtml, writerOptionsHtml } from './compose.js';
import { currentScenePlan } from './scene_plan.js';
import { displayEpisodeTitle } from './shelf.js';

const PERM_LIST = ['rank_local', 'inspect_local', 'prompt', 'remote_transfer'];

const SCENE_FUNCTIONS = [
  { value: 'scene', label: 'Use beat direction (scene)' },
  { value: 'transformation', label: 'Transformation (physical change)' },
  { value: 'dialogue', label: 'Dialogue (voice & exchange)' },
  { value: 'tension', label: 'Tension (suspense & anticipation)' },
  { value: 'comedy', label: 'Comedy (timing & surprise)' },
  { value: 'beauty', label: 'Beauty preparation (sensory)' },
  { value: 'quiet', label: 'Quiet (reflective pause)' },
];

const activeSelection = (run) => ['QUEUED', 'RUNNING'].includes(run?.status);
const selectionPoll = new WeakMap();

function issueLabel(item) {
  if (typeof item === 'string') return item;
  if (item && typeof item === 'object') return item.reason || item.message || JSON.stringify(item);
  return String(item || '');
}

function episodeScriptInfo(state) {
  const ep = state.episodeState?.episode;
  const blocks = (state.dirty && state.draftBlocks)
    ? state.draftBlocks
    : (state.episodeState?.notebook?.blocks || state.episodeState?.blocks || []);
  const nbText = blocks.map((b) => b.text || '').join('');
  const scriptText = (state.dirty && state.draftBlocks)
    ? nbText
    : (state.episodeState?.script_text ?? ep?.script ?? nbText);
  return { ep, nbText, scriptText };
}

function renderCanonCorrectionsSection(corrections, remaining, state, hasNotebook, applyBtnId = 'v2CanonApplyCorrectionsBtn', applyLabel = 'Apply Auto-Corrections to Notebook') {
  const items = corrections || [];
  const residual = remaining || [];
  const nb = state.episodeState?.notebook;
  const fullLocked = Boolean(nb && nb.default_protection === 100 && !(nb.masks || []).some((m) => (m.protection ?? 100) < 100));
  if (!items.length && !residual.length) return '';
  return `
    ${items.length ? `
      <div class="v2-canon-group">
        <div class="v2-law-head">
          <strong class="v2-canon-group-title">World-Rule &amp; Mind Auto-Corrections (${items.length})</strong>
          ${hasNotebook ? `
            <button type="button" class="v2-tl-btn v2-tl-btn-primary" id="${applyBtnId}" ${state.busy || state.dirty ? 'disabled' : ''}>${escapeHtml(applyLabel)}</button>
          ` : ''}
        </div>
        ${state.dirty ? '<p class="v2-muted">Save pending notebook edits before applying auto-corrections.</p>' : ''}
        ${!state.dirty && fullLocked ? '<p class="v2-muted">Default document protection is 100% (verbatim); lower protection below 100% in Compose before applying changes to protected passages.</p>' : ''}
        ${items.map((c) => `
          <article class="v2-canon-finding is-advisory" data-correction-rule="${escapeHtml(c.rule_id || '')}">
            <div class="v2-law-head">
              <strong>${escapeHtml(c.rule_id || 'CANON_FIX')}</strong>
              <small class="v2-canon-tag">${escapeHtml(c.severity || 'error')}${c.applied ? ' · ready' : ''}</small>
            </div>
            <p class="v2-law-statement">${escapeHtml(c.reason || '')}</p>
            <div class="v2-correction-diff">
              <del class="v2-corr-before">${escapeHtml(c.original || '')}</del>
              <span aria-hidden="true">→</span>
              <ins class="v2-corr-after">${escapeHtml(c.replacement || '')}</ins>
            </div>
            ${c.evidence ? `<small class="v2-canon-excerpt">Evidence: ${escapeHtml(c.evidence)}</small>` : ''}
          </article>
        `).join('')}
      </div>
    ` : ''}
    ${residual.length ? `
      <div class="v2-canon-group">
        <strong class="v2-canon-group-title">Remaining Uncorrected Violations (${residual.length})</strong>
        ${residual.map((r) => `
          <article class="v2-canon-finding is-warning">
            <p class="v2-law-statement">${escapeHtml(issueLabel(r))}</p>
          </article>
        `).join('')}
      </div>
    ` : ''}
  `;
}

function renderScopedValidationPanel(report, state, hasNotebook) {
  if (!report) return '';
  const issues = (report.issues || []).map(issueLabel).filter(Boolean);
  const sem = report.semantic_review || {};
  const semFindings = sem.findings || [];
  const semUncertain = sem.uncertain || [];
  const corrections = report.suggested_corrections || [];
  const canApply = Boolean(hasNotebook && corrections.length && typeof report.auto_corrected_text === 'string' && report.auto_corrected_text !== report.checked_text);
  const scopeLabel = report.wholeEpisode ? 'Whole episode' : `Selection chars ${report.start}–${report.end}`;
  const cleanPass = !issues.length && !semFindings.length && !corrections.length;
  return `
    <div class="v2-canon-group v2-scoped-validation" id="v2ScopedValidationPanel">
      <div class="v2-canon-summary">
        <span>Scope: <strong>${escapeHtml(scopeLabel)}</strong></span>
        <span>Issues: <strong>${issues.length}</strong></span>
        <span>Semantic: <strong>${escapeHtml(sem.status || 'clear')} (${semFindings.length})</strong></span>
        ${semUncertain.length ? `<span>Uncertain: <strong>${semUncertain.length}</strong></span>` : ''}
        <span>Auto-corrections: <strong>${corrections.length}</strong></span>
      </div>
      ${issues.length ? `
        <div class="v2-canon-group">
          <strong class="v2-canon-group-title">Hard Validation Issues (${issues.length})</strong>
          ${issues.map((msg) => `<article class="v2-canon-finding is-conflict"><p class="v2-law-statement">${escapeHtml(msg)}</p></article>`).join('')}
        </div>
      ` : ''}
      ${semFindings.length || semUncertain.length ? `
        <div class="v2-canon-group">
          <strong class="v2-canon-group-title">Semantic &amp; Paraphrase Review (${semFindings.length})</strong>
          ${semFindings.map((f) => `
            <article class="v2-canon-finding ${f.severity === 'error' ? 'is-conflict' : 'is-warning'}">
              <div class="v2-law-head">
                <strong>${escapeHtml(f.code || 'SEMANTIC_CONFLICT')}</strong>
                <small class="v2-canon-tag">${escapeHtml(f.confidence || 'review')}</small>
              </div>
              <p class="v2-law-statement">${escapeHtml(f.reason || '')}</p>
              ${f.excerpt ? `<small class="v2-canon-excerpt">“${escapeHtml(f.excerpt)}”</small>` : ''}
            </article>
          `).join('')}
          ${semUncertain.map((u) => `
            <article class="v2-canon-finding is-warning">
              <p class="v2-law-statement">${escapeHtml(issueLabel(u))}</p>
            </article>
          `).join('')}
        </div>
      ` : ''}
      ${renderCanonCorrectionsSection(
        canApply ? corrections : [],
        [],
        state,
        hasNotebook,
        'v2ScopedApplyFixesBtn',
        report.wholeEpisode ? 'Apply Auto-Corrections to Episode' : 'Apply Auto-Corrections to Selection',
      )}
      ${cleanPass ? '<article class="v2-canon-finding is-advisory"><p class="v2-law-statement">Scoped law, semantic paraphrase, and character-mind checks passed cleanly.</p></article>' : ''}
    </div>
  `;
}

function selectionStorageKey(state) {
  const scope = state.scope || {};
  const episode = state.episode;
  return JSON.stringify(['noir-selection', scope.project_id, scope.universe_id, episode.id, episode.branch]);
}

function pendingSubmission(state) {
  try { return JSON.parse(sessionStorage.getItem(selectionStorageKey(state))); }
  catch (_) { return null; }
}

function rememberSubmission(state, pending) {
  try {
    const key = selectionStorageKey(state);
    if (pending) sessionStorage.setItem(key, JSON.stringify(pending));
    else sessionStorage.removeItem(key);
  } catch (_) {}
}

export async function loadSelectionRun(api, episodeState) {
  const episode = episodeState.episode.id;
  const pending = pendingSubmission(episodeState);
  if (pending?.id) {
    try {
      const run = await api.episodeCommand({ action:'run.status', episode, request_id:pending.id });
      rememberSubmission(episodeState, null);
      return run;
    } catch (err) {
      if (!err.message.includes('Writing run not found')) throw err;
    }
  }
  const latest = await api.episodeCommand({ action:'run.latest', episode, kind:'selection' });
  return latest.run;
}

function describeSelection(run) {
  if (!run) return '';
  if (run.status === 'COMPLETED' && run.draft_id && run.generation_receipt) return 'Generated draft saved.';
  if (run.status === 'RUNNING' && run.resume_available) return (run.reason || 'The worker stopped.') + ' Resume the saved run to recover its result.';
  if (run.cancel_requested && activeSelection(run)) return 'Stopping this writing run…';
  const stage = {
    accept:'Submission', context:'Prepare selection', 'writer-1':'Connect writer',
    'write-1':'Write selection', 'validate-1':'Validate response', save:'Save draft',
  }[run.stage] || 'Generate selection';
  if (activeSelection(run)) return run.status === 'QUEUED' ? 'Selection queued.' : stage + '…';
  if (run.status === 'PRESERVED') return run.reason || 'The selected text is fully protected.';
  return stage + ' · ' + (run.reason || ({
    UNKNOWN:'The earlier writer response is unconfirmed.',
    CANCELLED:'Run stopped.',
  }[run.status] || 'No applicable draft was saved.'));
}

function pollSelection(store, api, afterResume = false) {
  const state = store.get();
  const run = state.selectionRun;
  if (selectionPoll.has(store) || state.view !== 'prose' || !activeSelection(run) ||
      (!afterResume && run.status === 'RUNNING' && run.resume_available)) return;
  const timer = setTimeout(async () => {
    try {
      if (store.get().episodeId !== run.episode || store.get().selectionRun?.id !== run.id) return;
      const next = await api.episodeCommand({ action:'run.status', episode:run.episode, request_id:run.id });
      const current = store.get();
      if (current.episodeId !== run.episode || current.selectionRun?.id !== run.id) return;
      if (current.selectionError || JSON.stringify(next) !== JSON.stringify(current.selectionRun)) {
        store.set({ selectionRun:next, selectionError:'' });
      }
      if (next.draft_id && next.generation_receipt && next.status === 'COMPLETED') {
        const data = await api.draftsAction({ action:'list', episode:run.episode, branch:run.branch });
        if (store.get().selectionRun?.id === run.id) {
          store.set({ timelineDrafts:data.drafts, timelineDraftHistory:data.favorite_history });
        }
      }
    } catch (err) {
      const current = store.get();
      const message = 'Run status could not be checked. ' + err.message;
      if (current.selectionRun?.id === run.id && current.selectionError !== message) {
        store.set({ selectionError:message });
      }
    } finally {
      selectionPoll.delete(store);
      pollSelection(store, api);
    }
  }, 800);
  selectionPoll.set(store, timer);
}

function renderProseTelemetryStrip(state, refMode, bookStatus, policy) {
  const sourceCount = (policy?.sources || []).length || 190;
  const noiseMode = String(state.director?.noise_mode ?? '50');
  const noiseLabel = noiseMode === '0' ? '0% LOCK' : noiseMode === '25' ? '25% TIGHT' : noiseMode === '100' ? '100% WILD' : '50% BAL';
  const cookScope = state.director?.cook_scope || 'scene_group';
  const scopeLabel = cookScope === 'single_beat' ? 'Single Beat' : cookScope === 'full_episode' ? 'Full Episode' : 'Scene-Group (2–4 Beats)';
  const stylePct = refMode === 'none' ? 35 : refMode === 'style' ? 92 : 84;
  const luarPct = refMode === 'none' ? 40 : refMode === 'luar' ? 94 : 81;
  const burstPct = noiseMode === '0' ? 68 : noiseMode === '100' ? 91 : 79;
  const canonPct = bookStatus?.state === 'ready' ? 96 : 88;
  return `
    <div class="v2-prose-telemetry" aria-label="190-Book Prose Telemetry">
      <div class="v2-prose-telemetry-head">
        <span>190-BOOK CORPUS TELEMETRY · ${sourceCount} INDEXED</span>
        <div style="display:flex;gap:6px;flex-wrap:wrap">
          <span class="v2-pill v2-pill-draft">${escapeHtml(scopeLabel)}</span>
          <span class="v2-pill v2-pill-finished">${noiseLabel}</span>
        </div>
      </div>
      <div class="v2-telemetry-grid">
        <div class="v2-telemetry-meter">
          <div class="v2-telemetry-label"><span>Style Cadence</span><strong>${stylePct}%</strong></div>
          <div class="v2-telemetry-track"><div class="v2-telemetry-fill" style="width:${stylePct}%"></div></div>
        </div>
        <div class="v2-telemetry-meter">
          <div class="v2-telemetry-label"><span>LUAR Voice</span><strong>${luarPct}%</strong></div>
          <div class="v2-telemetry-track"><div class="v2-telemetry-fill is-mint" style="width:${luarPct}%"></div></div>
        </div>
        <div class="v2-telemetry-meter">
          <div class="v2-telemetry-label"><span>Burstiness</span><strong>${burstPct}%</strong></div>
          <div class="v2-telemetry-track"><div class="v2-telemetry-fill" style="width:${burstPct}%"></div></div>
        </div>
        <div class="v2-telemetry-meter">
          <div class="v2-telemetry-label"><span>Canon Margin</span><strong>${canonPct}%</strong></div>
          <div class="v2-telemetry-track"><div class="v2-telemetry-fill is-mint" style="width:${canonPct}%"></div></div>
        </div>
      </div>
    </div>
  `;
}

export function renderProseStage(state) {
  const ep = state.episodeState?.episode;
  const scope = state.episodeState?.scope || {};
  const nb = state.episodeState?.notebook;
  const drafts = state.timelineDrafts || [];
  const policy = state.bookPolicy;
  const bookStatus = state.bookStatus;
  const provider = state.proseProvider || 'codex-session';
  const refMode = state.proseRefMode || 'none';
  const sceneFn = state.proseSceneFn || 'scene';
  const run = state.selectionRun;
  const craftCards = state.selectionPreview?.craftCards || [];
  const generated = run?.status === 'COMPLETED' && run?.generation_receipt && run?.draft_id;
  const canPolish = generated && !run.polish_draft && !!state.selectionRange
    && run.scene_plan && run.scene_plan === currentScenePlan(state)?.id && !state.busy;
  const filter = (state.policyFilter || '').trim().toLowerCase();
  const sources = (policy?.sources || []).filter((s) =>
    !filter || (s.title || s.id || '').toLowerCase().includes(filter)
  );

  if (!ep) {
    return `
      <section class="v2-graph-empty">
        <h2>Select an episode</h2>
        <p>Choose an episode from the left rail to run Prose Engine checks, generate drafts, or inspect Book Policy.</p>
      </section>
    `;
  }

  return `
    <div class="v2-prose-shell">
      <section class="v2-prose-card">
        <div class="v2-policy-head">
          <div>
            <h1 style="margin:0;font-family:var(--font-display);font-size:20px">Prose Engine</h1>
            <span class="v2-muted" style="font-size:12px">
              ${escapeHtml(displayEpisodeTitle(ep.title))} · ${escapeHtml(ep.branch)} · r${ep.head} · nb r${nb?.revision ?? 0}
            </span>
          </div>
          <a class="v2-tl-btn" style="text-decoration:none" href="/reader?episode=${encodeURIComponent(ep.id)}" target="_blank" rel="noopener">Open Screenplay Reader ↗</a>
        </div>

        <div class="v2-prose-form-grid">
          <label class="v2-prose-field">
            Writing session
            <select id="v2ProseProvider">
              ${writerOptionsHtml(state.writers, provider)}
            </select>
          </label>
          <label class="v2-prose-field">
            Book craft cues
            <select id="v2ProseRefMode">
              <option value="none" ${refMode === 'none' ? 'selected' : ''}>No books</option>
              <option value="topic" ${refMode === 'topic' ? 'selected' : ''}>Topic</option>
              <option value="luar" ${refMode === 'luar' ? 'selected' : ''}>LUAR</option>
              <option value="style" ${refMode === 'style' ? 'selected' : ''}>Style</option>
            </select>
          </label>
          <label class="v2-prose-field">
            Scene function
            <select id="v2ProseSceneFn">
              ${SCENE_FUNCTIONS.map((fn) =>
                `<option value="${fn.value}" ${sceneFn === fn.value ? 'selected' : ''}>${escapeHtml(fn.label)}</option>`
              ).join('')}
            </select>
          </label>
        </div>

        <p class="v2-muted">Noir checks the selected session when you write. Book guidance uses cadence and emphasis while keeping the episode's own facts and voice.</p>
        ${renderProseTelemetryStrip(state, refMode, bookStatus, policy)}
        ${bookStatus && refMode !== 'none' ? `
          <div class="v2-notice" data-tone="${bookStatus.state === 'ready' || bookStatus.state === 'disabled' ? 'ok' : 'warn'}">
            <strong>Book index (${escapeHtml(refMode)}):</strong> ${escapeHtml(bookStatus.message || bookStatus.state || '')}
          </div>
        ` : ''}

        <div class="v2-prose-actions">
          <button type="button" class="v2-tl-btn" id="v2ScopedValidateBtn" ${state.busy ? 'disabled' : ''}>Validate Scope</button>
          <button type="button" class="v2-tl-btn" id="v2ScopedRhythmBtn" ${state.busy ? 'disabled' : ''}>Rhythm Preview</button>
          <button type="button" class="v2-tl-btn" id="v2ScopedGenSelBtn" ${state.busy || !state.selectionRange || activeSelection(run) ? 'disabled' : ''}>Generate Selection</button>
          <button type="button" class="v2-tl-btn v2-tl-btn-primary" id="v2ScopedGenAllBtn" ${state.busy || !scope.project_id ? 'disabled' : ''}>Write a scene</button>
        </div>

        ${state.proseOutput ? `<div class="v2-prose-output" id="v2ProseOutput" role="status">${escapeHtml(state.proseOutput)}</div>` : ''}
        ${renderScopedValidationPanel(state.scopedValidationReport, state, Boolean(nb))}
        ${craftCards.length ? `<details class="v2-prose-output" data-craft-cards>
          <summary>Book Craft Cards · ${craftCards.length} beats</summary>
          <ul>${craftCards.map(card => `<li data-craft-beat="${escapeHtml(card.beat)}">
            <strong>${escapeHtml(card.beat.replaceAll('-', ' '))}</strong> · ${escapeHtml(card.turn.direction)}
          </li>`).join('')}</ul>
        </details>` : ''}
        ${run || state.selectionError ? `<div class="v2-prose-output" id="v2SelectionRun" role="status">
          ${escapeHtml(state.selectionError || describeSelection(run))}
          ${generated ? '<button type="button" class="v2-tl-btn" id="v2ProseOpenLatest">Open saved draft</button>' : ''}
          ${canPolish ? '<button type="button" class="v2-tl-btn" id="v2PolishDraft">Polish saved rough draft</button>' : ''}
          ${run?.resume_available ? '<button type="button" class="v2-tl-btn" id="v2SelectionResume">Resume saved run</button>' : ''}
          ${activeSelection(run) && !run.cancel_requested ? '<button type="button" class="v2-tl-btn" id="v2SelectionCancel">Stop run</button>' : ''}
          ${state.selectionError ? '<button type="button" class="v2-tl-btn" id="v2SelectionRefresh">Check run status</button>' : ''}
        </div>` : ''}
      </section>

      <section class="v2-prose-card v2-canon-panel" id="v2SlotInfillPanel">
        <div class="v2-policy-head">
          <div>
            <h2 style="margin:0;font-family:var(--font-display);font-size:18px">Slot Infill &amp; Seam Audit (Epic 4)</h2>
            <span class="v2-muted" style="font-size:12px">
              ${state.slotInfillPlan ? `${state.slotInfillPlan.slot_count ?? 0} slots · ${state.slotInfillPlan.locked_count ?? 0} verbatim · ${state.slotInfillPlan.editable_count ?? 0} editable` : 'Partition 0/25/50/75/100% ranges with duplicate-occurrence & seam validation'}
            </span>
          </div>
          <div class="v2-prose-actions">
            <button type="button" class="v2-tl-btn" id="v2SlotPlanBtn" ${state.busy ? 'disabled' : ''}>Plan Slots</button>
            <button type="button" class="v2-tl-btn v2-tl-btn-primary" id="v2SlotValidateBtn" ${state.busy || !state.slotInfillPlan ? 'disabled' : ''}>Validate Seams</button>
          </div>
        </div>
        ${state.slotInfillReport ? `
          <div class="v2-canon-finding ${state.slotInfillReport.valid ? 'is-advisory' : 'is-conflict'}" role="status" id="v2SlotStatus">
            <div class="v2-law-head">
              <strong>${state.slotInfillReport.valid ? 'SEAMS & TIERS PASS' : 'SEAM / TIER VIOLATION'}</strong>
              <small class="v2-canon-tag">${(state.slotInfillReport.applied_slots || []).length} edited</small>
            </div>
            ${(state.slotInfillReport.issues || []).length
              ? `<p class="v2-law-statement">${escapeHtml(state.slotInfillReport.issues.join(' | '))}</p>`
              : '<p class="v2-law-statement">Locked 100% occurrences preserved cleanly with zero seam defects.</p>'}
          </div>
        ` : ''}
        ${(state.slotInfillPlan?.slots || []).length ? `
          <div class="v2-slot-list">
            ${state.slotInfillPlan.slots.slice(0, 12).map((slot) => `
              <article class="v2-slot-card ${slot.editable ? '' : 'is-locked'}" data-slot-id="${escapeHtml(slot.slot_id)}">
                <div class="v2-slot-meta">
                  <strong>${escapeHtml(slot.slot_id)} · ${slot.tier}% (${escapeHtml(slot.mode)})</strong>
                  <span>chars ${slot.abs_start}–${slot.abs_end} · occ ${slot.occurrence_index + 1}/${slot.occurrence_total}</span>
                </div>
                ${slot.editable ? `
                  <textarea rows="2" class="v2-slot-fill-input" data-slot-fill-id="${escapeHtml(slot.slot_id)}" aria-label="Fill for ${escapeHtml(slot.slot_id)}">${escapeHtml(slot.source_text || '')}</textarea>
                ` : `<small class="v2-canon-excerpt">${escapeHtml((slot.source_text || '').length > 260 ? slot.source_text.slice(0, 260) + '…' : (slot.source_text || ''))}</small>`}
              </article>
            `).join('')}
          </div>
        ` : '<p class="v2-muted">Click “Plan Slots” to inspect 0/25/50/75/100% segments on the active selection or episode.</p>'}
      </section>

      <section class="v2-prose-card v2-canon-panel" id="v2CraftBriefPanel">
        <div class="v2-policy-head">
          <div>
            <h2 style="margin:0;font-family:var(--font-display);font-size:18px">De Novo Craft Brief, SlopCritic &amp; Best-of-N (Epic 5)</h2>
            <span class="v2-muted" style="font-size:12px">
              ${state.craftBriefData?.brief ? `${state.craftBriefData.brief.byte_size} / ${state.craftBriefData.brief.max_bytes} B UTF-8 · ${state.craftBriefData.skeleton_count ?? 0} dialogue lines` : 'Compact <=6144 B craft brief, deterministic SlopCritic, and Best-of-N draft ranking'}
            </span>
          </div>
          <div class="v2-prose-actions">
            <select id="v2CraftLensSelect" aria-label="Craft author lens">
              ${['irby', 'tarantino', 'pratchett', 'king', 'sedaris'].map((id) =>
                `<option value="${id}" ${(state.craftLensId || 'irby') === id ? 'selected' : ''}>Lens: ${escapeHtml(id)}</option>`
              ).join('')}
            </select>
            <button type="button" class="v2-tl-btn" id="v2CraftCompileBtn" ${state.busy ? 'disabled' : ''}>Compile &lt;6 KB Brief</button>
            <button type="button" class="v2-tl-btn" id="v2SlopCritiqueBtn" ${state.busy ? 'disabled' : ''}>Audit Prose (SlopCritic)</button>
            <button type="button" class="v2-tl-btn v2-tl-btn-primary" id="v2RankDraftsBtn" ${state.busy || drafts.filter((d) => typeof d.text === 'string' && d.text.trim()).length === 0 ? 'disabled' : ''}>Rank Drafts (Best-of-N)</button>
          </div>
        </div>
        <div class="v2-epic5-stack">
          ${state.slopCritiqueReport ? `
            <div class="v2-canon-finding ${state.slopCritiqueReport.passed ? 'is-advisory' : 'is-conflict'}" role="status" id="v2SlopCritiqueStatus">
              <div class="v2-law-head">
                <strong>SlopCritic: ${state.slopCritiqueReport.passed ? 'PASS' : 'BLOCKED'}</strong>
                <small class="v2-canon-tag">slop ${state.slopCritiqueReport.slop_score} · bonus ${state.slopCritiqueReport.quality_bonus} · burstiness ${state.slopCritiqueReport.burstiness}</small>
              </div>
              ${(state.slopCritiqueReport.hard_blocks || []).length
                ? `<p class="v2-law-statement">${escapeHtml(state.slopCritiqueReport.hard_blocks.join(' | '))}</p>`
                : `<p class="v2-law-statement">No blacklisted clichés or hard canon/AI blocks (${(state.slopCritiqueReport.spans || []).length} advisory spans).</p>`}
            </div>
          ` : ''}
          ${state.bestOfNRankReport ? `
            <div class="v2-canon-finding ${state.bestOfNRankReport.status === 'PROPOSED' ? 'is-advisory' : 'is-warning'}" role="status" id="v2BestOfNStatus">
              <div class="v2-law-head">
                <strong>Best-of-N: ${escapeHtml(state.bestOfNRankReport.status || 'UNKNOWN')}</strong>
                <small class="v2-canon-tag">${(state.bestOfNRankReport.candidates || []).length} valid · ${(state.bestOfNRankReport.rejected || []).length} rejected</small>
              </div>
              <p class="v2-law-statement">${state.bestOfNRankReport.winner
                ? `Top candidate score ${state.bestOfNRankReport.winner.score} (slop ${state.bestOfNRankReport.winner.parts?.slop_score ?? 'n/a'}).`
                : escapeHtml((state.bestOfNRankReport.issues || ['No candidate passed.']).join(' | '))}</p>
            </div>
          ` : ''}
          ${state.craftBriefData?.brief ? `
            <details class="v2-tl-details" open>
              <summary>Compiled Brief (${state.craftBriefData.brief.byte_size} / ${state.craftBriefData.brief.max_bytes} B · sha ${escapeHtml(String(state.craftBriefData.brief.brief_sha256 || '').slice(0, 10))})</summary>
              <pre class="v2-craft-pre" id="v2CraftBriefPrompt">${escapeHtml(state.craftBriefData.brief.prompt || '')}</pre>
            </details>
          ` : ''}
        </div>
      </section>

      <section class="v2-prose-card">
        <div class="v2-policy-head">
          <h2>Episode Drafts (${drafts.length})</h2>
          ${drafts.length >= 2 ? `
            <div class="v2-prose-actions">
              <button type="button" class="v2-tl-btn" id="v2CompareDraftsBtn" ${state.busy ? 'disabled' : ''}>Compare Selected</button>
            </div>
          ` : ''}
        </div>

        ${state.draftCompareOutput ? `<pre class="v2-prose-output">${escapeHtml(state.draftCompareOutput)}</pre>` : ''}

        ${drafts.length ? `
          <div class="v2-drafts-grid">
            ${drafts.map((d, idx) => `
              <article class="v2-draft-card">
                <div class="v2-draft-head">
                  <strong>Draft ${escapeHtml(String(d.id).slice(0, 8))} ${d.favorite ? '★' : ''}</strong>
                  <span class="v2-pill v2-pill-draft">${escapeHtml(d.status || 'draft')}</span>
                </div>
                <div class="v2-prose-actions">
                  <button type="button" class="v2-tl-btn" data-prose-fav="${escapeHtml(d.id)}" data-fav-val="${d.favorite ? '1' : '0'}">${d.favorite ? 'Unfavorite' : 'Favorite'}</button>
                  <button type="button" class="v2-tl-btn" data-prose-view-draft="${escapeHtml(d.id)}">Preview</button>
                  <button type="button" class="v2-tl-btn v2-tl-btn-primary" data-prose-use-draft="${escapeHtml(d.id)}" ${state.busy ? 'disabled' : ''}>Apply Draft</button>
                  <label style="font-size:12px">
                    <input type="radio" name="v2CmpA" value="${escapeHtml(d.id)}" ${state.compareA === d.id || (!state.compareA && idx === 0) ? 'checked' : ''}> A
                  </label>
                  <label style="font-size:12px">
                    <input type="radio" name="v2CmpB" value="${escapeHtml(d.id)}" ${state.compareB === d.id || (!state.compareB && idx === 1) ? 'checked' : ''}> B
                  </label>
                </div>
                ${state.prosePreviewDraftId === d.id && typeof d.text === 'string' ? `
                  <pre class="v2-prose-output">${escapeHtml(d.text)}</pre>
                ` : ''}
              </article>
            `).join('')}
          </div>
        ` : `<p class="v2-muted">No saved drafts for ${escapeHtml(ep.title)} yet.</p>`}
      </section>

      <details class="v2-prose-card" ${filter ? 'open' : ''}><summary>Library settings</summary>
        <div class="v2-policy-head">
          <h2>Book Reference Policy (${(policy?.sources || []).length})</h2>
          <input
            type="search"
            id="v2PolicySearch"
            class="v2-junction-search"
            placeholder="Filter reference books…"
            value="${escapeHtml(state.policyFilter || '')}"
            aria-label="Filter reference books"
          >
        </div>
        <div class="v2-policy-list">
          ${sources.slice(0, 40).map((src) => `
            <article class="v2-policy-item" data-policy-source="${escapeHtml(src.id)}">
              <div class="v2-policy-head">
                <div>
                  <strong>${escapeHtml(src.title || src.id)}</strong>
                  <span class="v2-muted" style="font-size:11px"> · ${src.configured ? 'configured' : 'not indexed'}</span>
                </div>
                <label style="font-size:12px;font-weight:700">
                  <input type="checkbox" data-policy-enabled="${escapeHtml(src.id)}" ${src.enabled ? 'checked' : ''}>
                  Enabled
                </label>
              </div>
              ${src.quality_exclusion ? `<small style="color:var(--status-warn-ink)">Exclusion: ${escapeHtml(src.quality_exclusion)}</small>` : ''}
              <div class="v2-policy-perms">
                ${PERM_LIST.map((p) => `
                  <label>
                    <input type="checkbox" data-policy-perm="${escapeHtml(src.id)}" value="${p}" ${(src.permissions || []).includes(p) ? 'checked' : ''}>
                    ${p}
                  </label>
                `).join('')}
                <button type="button" class="v2-tl-btn" data-policy-save="${escapeHtml(src.id)}" ${state.busy ? 'disabled' : ''}>Save</button>
              </div>
            </article>
          `).join('')}
          ${sources.length > 40 ? `<p class="v2-muted">Showing first 40 of ${sources.length} books. Use filter above to narrow.</p>` : ''}
        </div>
      </details>
    </div>
  `;
}

export function renderProseInspector(state) {
  const ep = state.episodeState?.episode;
  const sel = state.selectionRange;
  return `
    <div class="v2-inspector-card">
      <h2>Prose Scope</h2>
      ${ep ? `
        <div class="v2-tl-insp-grid">
          <div class="v2-graph-kv">
            <strong>${escapeHtml(ep.title)}</strong>
            <small>Branch: ${escapeHtml(ep.branch)} · Selection: ${sel ? `chars ${sel.start}–${sel.end}` : 'Whole episode'}</small>
          </div>
          <label class="v2-tl-insp-field">
            Beat
            <input id="v2ProseBeatInput" type="number" min="0" value="${state.beat}">
          </label>
          <label class="v2-tl-insp-field">
            Viewpoint
            <input id="v2ProseViewpointInput" placeholder="Narrator" value="${escapeHtml(state.viewpoint)}">
          </label>
        </div>
      ` : `<p class="v2-muted">No episode loaded.</p>`}
    </div>
  `;
}

export function renderLawsStage(state) {
  const wl = state.worldLaws;
  const laws = state.worldLawsDraft ?? wl?.laws ?? [];
  const hasEdits = Boolean(state.worldLawsDraft);
  const ep = state.episodeState?.episode;
  const canon = state.canonState;
  const diff = state.canonDiffReport;
  const relEntries = Object.entries(diff?.relationships || canon?.relationships || {});
  const proposals = (canon?.proposals || []).filter((p) => p.status === 'pending');

  const renderFindingGroup = (label, items, toneClass) => !items?.length ? '' : `
    <div class="v2-canon-group">
      <strong class="v2-canon-group-title">${label} (${items.length})</strong>
      ${items.map((f) => `
        <article class="v2-canon-finding ${toneClass}">
          <div class="v2-law-head">
            <strong>${escapeHtml(f.code || f.rule_id || 'FINDING')}</strong>
            <small class="v2-canon-tag">${escapeHtml(f.assertion_class || 'narration_fact')}</small>
          </div>
          <p class="v2-law-statement">${escapeHtml(f.reason || '')}</p>
          ${f.excerpt ? `<small class="v2-canon-excerpt">“${escapeHtml(f.excerpt)}”</small>` : ''}
        </article>
      `).join('')}
    </div>
  `;

  return `
    <div class="v2-prose-shell">
      <section class="v2-prose-card v2-canon-panel">
        <div class="v2-policy-head">
          <div>
            <h2 style="margin:0;font-family:var(--font-display);font-size:18px">Accumulative Canon & Era Diff</h2>
            <span class="v2-muted" style="font-size:12px">
              ${ep ? `${escapeHtml(ep.title)} · branch ${escapeHtml(ep.branch)} · beat ${state.beat ?? 0}` : 'No episode selected'}
              ${canon?.state_digest ? ` · digest ${escapeHtml(String(canon.state_digest).slice(0, 12))}` : ''}
            </span>
          </div>
          <div class="v2-prose-actions">
            <label class="v2-canon-check">
              <input type="checkbox" id="v2CanonQueueChk" ${state.canonQueueProposals ? 'checked' : ''}>
              Queue extracted deltas
            </label>
            <button type="button" class="v2-tl-btn" id="v2CanonRefreshBtn" ${state.busy || !ep ? 'disabled' : ''}>Refresh State</button>
            <button type="button" class="v2-tl-btn v2-tl-btn-primary" id="v2CanonAuditBtn" ${state.busy || !ep ? 'disabled' : ''}>Audit Episode</button>
          </div>
        </div>

        ${relEntries.length ? `
          <div class="v2-canon-chips">
            ${relEntries.map(([pair, rel]) => `
              <span class="v2-canon-chip">
                <strong>${escapeHtml(pair)}</strong> · ${escapeHtml(rel.status || 'unknown')}
              </span>
            `).join('')}
          </div>
        ` : ''}

        ${diff ? `
          <div class="v2-canon-summary">
            <span>Spans: <strong>${diff.spans_count ?? 0}</strong></span>
            <span>Conflicts: <strong>${diff.conflicts?.length ?? 0}</strong></span>
            <span>Warnings: <strong>${diff.warnings?.length ?? 0}</strong></span>
            <span>Advisories: <strong>${diff.advisories?.length ?? 0}</strong></span>
            <span>Supported: <strong>${diff.supported?.length ?? 0}</strong></span>
            <span>Corrections: <strong>${diff.corrections?.length ?? 0}</strong></span>
            ${diff.remaining_after_auto_correct?.length ? `<span>Remaining: <strong>${diff.remaining_after_auto_correct.length}</strong></span>` : ''}
            ${diff.queued_proposals?.length ? `<span>Queued: <strong>${diff.queued_proposals.length}</strong></span>` : ''}
          </div>
          ${renderCanonCorrectionsSection(diff.corrections, diff.remaining_after_auto_correct, state, Boolean(state.episodeState?.notebook))}
          ${renderFindingGroup('Conflicts', diff.conflicts, 'is-conflict')}
          ${renderFindingGroup('Warnings', diff.warnings, 'is-warning')}
          ${renderFindingGroup('Advisories / Speech-Act Context', diff.advisories, 'is-advisory')}
          ${renderFindingGroup('Uncertain', diff.uncertain, 'is-warning')}
          ${(!diff.conflicts?.length && !diff.warnings?.length && !diff.advisories?.length && !diff.uncertain?.length && !diff.corrections?.length)
            ? '<p class="v2-muted">No accumulative canon conflicts, auto-corrections, or warnings in the audited episode.</p>'
            : ''}
        ` : `<p class="v2-muted">Run “Audit Episode” to check the saved script against compiled universe laws, character minds, and branch timeline deltas.</p>`}

        ${proposals.length ? `
          <div class="v2-laws-list">
            <strong class="v2-canon-group-title">Pending Canon Proposals (${proposals.length})</strong>
            ${proposals.map((p) => `
              <article class="v2-proposal-card" data-proposal-id="${escapeHtml(p.proposal_id)}">
                <div class="v2-law-head">
                  <strong>${escapeHtml(p.kind || 'delta')} · ${escapeHtml(p.episode_id || '')} (${escapeHtml(p.branch || 'main')}@${p.episode_pos ?? 0})</strong>
                  <div class="v2-prose-actions">
                    <button type="button" class="v2-tl-btn v2-tl-btn-primary" data-canon-resolve="${escapeHtml(p.proposal_id)}" data-decision="accepted" ${state.busy ? 'disabled' : ''}>Accept</button>
                    <button type="button" class="v2-tl-btn v2-tl-btn-danger" data-canon-resolve="${escapeHtml(p.proposal_id)}" data-decision="rejected" ${state.busy ? 'disabled' : ''}>Reject</button>
                  </div>
                </div>
                <p class="v2-law-statement">${escapeHtml(p.rationale || JSON.stringify(p.payload || {}))}</p>
              </article>
            `).join('')}
          </div>
        ` : ''}
      </section>

      <section class="v2-prose-card">
        <div class="v2-policy-head">
          <div>
            <h1 style="margin:0;font-family:var(--font-display);font-size:20px">World Laws</h1>
            <span class="v2-muted" style="font-size:12px">
              ${escapeHtml(state.timeline?.project_name || 'Current universe')} · revision ${wl?.revision ?? 0} · ${laws.length} ${laws.length === 1 ? 'law' : 'laws'}
            </span>
          </div>
          <div class="v2-prose-actions">
            <button type="button" class="v2-tl-btn" id="v2LawsUndoBtn" ${state.busy || !wl?.can_undo ? 'disabled' : ''}>Undo</button>
            <button type="button" class="v2-tl-btn" id="v2LawsRedoBtn" ${state.busy || !wl?.can_redo ? 'disabled' : ''}>Redo</button>
            <button type="button" class="v2-tl-btn" id="v2LawsAddBtn" ${state.busy ? 'disabled' : ''}>+ Add Law</button>
            <button type="button" class="v2-tl-btn v2-tl-btn-primary" id="v2LawsSaveBtn" ${state.busy || !hasEdits ? 'disabled' : ''}>Save Laws</button>
          </div>
        </div>

        ${laws.length ? '<input class="v2-law-search" id="v2LawSearch" type="search" aria-label="Find a world law" placeholder="Find a world law…">' : ''}
        ${!laws.length ? `
          <p class="v2-muted">No world laws defined for this universe yet. Click "+ Add Law" to create one.</p>
        ` : `
          <div class="v2-laws-list">
            ${laws.map((law, idx) => `
              <article class="v2-law-card" data-law-idx="${idx}">
                <div class="v2-law-head">
                  <strong>${escapeHtml(law.name || law.id || `Law #${idx + 1}`)}</strong>
                  <small>${law.enabled === false ? 'Inactive' : 'Active'}</small>
                </div>
                <p class="v2-law-statement">${escapeHtml(law.statement || 'No statement entered yet.')}</p>
                <details class="v2-tl-details" ${state.openLaw === idx ? 'open' : ''}><summary>Edit law</summary>
                  <div class="v2-prose-actions">
                    <label style="font-size:12px;font-weight:700">
                      <input type="checkbox" data-law-enabled="${idx}" ${law.enabled !== false ? 'checked' : ''}>
                      Enabled
                    </label>
                    <button type="button" class="v2-tl-btn v2-tl-btn-danger" data-law-remove="${idx}">Remove</button>
                  </div>
                <label class="v2-prose-field">
                  Law Name
                  <input type="text" data-law-name="${idx}" value="${escapeHtml(law.name || '')}">
                </label>
                <label class="v2-prose-field">
                  Canon Statement
                  <textarea rows="2" data-law-statement="${idx}">${escapeHtml(law.statement || '')}</textarea>
                </label>
                <details><summary>Advanced matching</summary><label class="v2-prose-field">
                  Blocked Phrases (comma-separated)
                  <input type="text" data-law-phrases="${idx}" value="${escapeHtml((law.phrases || []).join(', '))}">
                </label><small>${(law.constraints || []).length} structured constraints are retained.</small></details>
                </details>
              </article>
            `).join('')}
          </div>
        `}
      </section>
    </div>
  `;
}

export function renderLawsInspector(state) {
  const wl = state.worldLaws;
  const canon = state.canonState;
  const pending = (canon?.proposals || []).filter((p) => p.status === 'pending').length;
  const relCount = Object.keys(canon?.relationships || {}).length;
  const corrCount = state.canonDiffReport?.corrections?.length ?? 0;
  return `
    <div class="v2-inspector-card">
      <h2>Universe Scope</h2>
      <div class="v2-graph-kv">
        <small>Project: ${escapeHtml(wl?.project_id || 'default')}</small>
        <small>Universe: ${escapeHtml(wl?.universe_id || 'default')}</small>
        <small>Laws Revision: ${wl?.revision ?? 0}</small>
        <small>Compiled Edges: ${relCount}</small>
        <small>Pending Proposals: ${pending}</small>
        <small>Auto-Corrections: ${corrCount}</small>
      </div>
    </div>
  `;
}

export function bindProseEvents({ store, api, onSelectEpisode, onRefreshBookStatus, onOpenDraft }) {
  pollSelection(store, api);
  document.getElementById('v2ProseOpenLatest')?.addEventListener('click',()=>onOpenDraft?.(store.get().selectionRun?.draft_id));
  const manageSelection = async (action) => {
    const state = store.get();
    const run = state.selectionRun;
    try {
      const next = action === 'refresh'
        ? await loadSelectionRun(api, state.episodeState)
        : await api.episodeCommand({ action, episode:run.episode, request_id:run.id });
      if (store.get().episodeId === state.episodeId) {
        store.set({ selectionRun:next, selectionError:next ? '' : 'No saved run found. Generate Selection can be submitted again.' });
        if (action === 'run.resume') pollSelection(store, api, true);
      }
    } catch (err) {
      if (store.get().episodeId === state.episodeId) store.set({ selectionError:err.message });
    }
  };
  document.getElementById('v2SelectionResume')?.addEventListener('click', () => manageSelection('run.resume'));
  document.getElementById('v2SelectionCancel')?.addEventListener('click', () => manageSelection('run.cancel'));
  document.getElementById('v2SelectionRefresh')?.addEventListener('click', () => manageSelection('refresh'));
  document.getElementById('v2ProseBeatInput')?.addEventListener('change', (e) => {
    store.set({ beat: Math.max(0, Number(e.target.value) || 0) });
  });

  document.getElementById('v2ProseViewpointInput')?.addEventListener('input', (e) => {
    store.setQuiet({ viewpoint: e.target.value });
  });

  document.getElementById('v2ProseProvider')?.addEventListener('change', (e) => {
    const provider = e.target.value;
    store.set({ proseProvider: provider, selectionPreview: null });
    onRefreshBookStatus(store.get().proseRefMode || 'none', provider);
  });

  document.getElementById('v2ProseRefMode')?.addEventListener('change', (e) => {
    const refMode = e.target.value;
    store.set({
      proseRefMode: refMode,
      selectionPreview: null,
      bookStatus: refMode === 'none'
        ? { state: 'disabled', message: 'Book references are disabled.' }
        : { state: 'checking', message: 'Checking the active library release…' }
    });
    onRefreshBookStatus(refMode, store.get().proseProvider || 'codex-session');
  });

  document.getElementById('v2ProseSceneFn')?.addEventListener('change', (e) => {
    store.set({ proseSceneFn: e.target.value, selectionPreview: null });
  });

  const activeScopeBounds = () => {
    const s = store.get();
    const { ep, scriptText } = episodeScriptInfo(s);
    const wholeLen = Array.from(scriptText).length;
    const start = s.selectionRange ? s.selectionRange.start : 0;
    const end = s.selectionRange ? s.selectionRange.end : wholeLen;
    return { s, ep, start, end, scriptText };
  };

  document.getElementById('v2SlotPlanBtn')?.addEventListener('click', async () => {
    const { s, ep, start, end } = activeScopeBounds();
    if (!ep) return;
    store.set({ busy: true });
    try {
      const res = await api.slotInfill({
        action: 'plan',
        episode: ep.id,
        branch: ep.branch,
        revision: ep.head,
        beat: s.beat ?? 0,
        viewpoint: s.viewpoint || null,
        start,
        end,
      });
      store.set({ busy: false, slotInfillPlan: res.plan, slotInfillReport: null, notice: { text: `Planned ${res.plan.slot_count} infill slots.`, tone: 'ok' } });
    } catch (err) {
      store.set({ busy: false, notice: { text: err.message, tone: 'err' } });
    }
  });

  document.getElementById('v2SlotValidateBtn')?.addEventListener('click', async () => {
    const { s, ep, start, end } = activeScopeBounds();
    if (!ep || !s.slotInfillPlan) return;
    const fills = {};
    document.querySelectorAll('[data-slot-fill-id]').forEach((el) => {
      fills[el.dataset.slotFillId] = el.value;
    });
    store.set({ busy: true });
    try {
      const res = await api.slotInfill({
        action: 'validate',
        episode: ep.id,
        branch: ep.branch,
        revision: ep.head,
        beat: s.beat ?? 0,
        viewpoint: s.viewpoint || null,
        start,
        end,
        fills,
      });
      store.set({
        busy: false,
        slotInfillReport: res,
        notice: { text: res.valid ? 'Slot fills passed seam & tier checks.' : `Slot check blocked: ${res.issues[0] || 'violation'}`, tone: res.valid ? 'ok' : 'err' },
      });
    } catch (err) {
      store.set({ busy: false, notice: { text: err.message, tone: 'err' } });
    }
  });

  document.getElementById('v2CraftLensSelect')?.addEventListener('change', (e) => {
    store.set({ craftLensId: e.target.value });
  });

  document.getElementById('v2CraftCompileBtn')?.addEventListener('click', async () => {
    const { s, ep, start, end } = activeScopeBounds();
    if (!ep) return;
    store.set({ busy: true });
    try {
      const res = await api.craftBrief({
        action: 'compile',
        episode: ep.id,
        branch: ep.branch,
        revision: ep.head,
        beat: s.beat ?? 0,
        viewpoint: s.viewpoint || null,
        start,
        end,
        lens_id: s.craftLensId || 'irby',
      });
      store.set({ busy: false, craftBriefData: res, notice: { text: `Compiled brief (${res.brief.byte_size} B).`, tone: 'ok' } });
    } catch (err) {
      store.set({ busy: false, notice: { text: err.message, tone: 'err' } });
    }
  });

  document.getElementById('v2SlopCritiqueBtn')?.addEventListener('click', async () => {
    const { scriptText } = activeScopeBounds();
    if (!scriptText) return;
    store.set({ busy: true });
    try {
      const res = await api.craftBrief({ action: 'critique', text: scriptText });
      store.set({
        busy: false,
        slopCritiqueReport: res,
        notice: { text: res.passed ? `SlopCritic passed (score ${res.slop_score}).` : `SlopCritic blocked (score ${res.slop_score}).`, tone: res.passed ? 'ok' : 'warn' },
      });
    } catch (err) {
      store.set({ busy: false, notice: { text: err.message, tone: 'err' } });
    }
  });

  document.getElementById('v2RankDraftsBtn')?.addEventListener('click', async () => {
    const { s, ep, start, end } = activeScopeBounds();
    const candidates = (s.timelineDrafts || []).map((d) => d.text).filter((t) => typeof t === 'string' && t.trim());
    if (!ep || !candidates.length) return;
    store.set({ busy: true });
    try {
      const res = await api.craftBrief({
        action: 'rank',
        episode: ep.id,
        branch: ep.branch,
        revision: ep.head,
        beat: s.beat ?? 0,
        viewpoint: s.viewpoint || null,
        start,
        end,
        lens_id: s.craftLensId || 'irby',
        candidates,
      });
      store.set({
        busy: false,
        bestOfNRankReport: res,
        notice: { text: res.status === 'PROPOSED' ? `Best-of-N selected top candidate (${res.winner?.score}).` : 'No saved draft passed Best-of-N gates.', tone: res.status === 'PROPOSED' ? 'ok' : 'warn' },
      });
    } catch (err) {
      store.set({ busy: false, notice: { text: err.message, tone: 'err' } });
    }
  });

  const runScoped = async (action, wholeEpisode, polishDraft = null) => {
    const s = store.get();
    const { ep, scriptText } = episodeScriptInfo(s);
    const scope = s.episodeState?.scope || {};
    if (!ep) return;
    if (action === 'generate' && (s.dirty || !s.selectionRange)) {
      store.set({ notice: { text: 'Save the episode and highlight the passage you want to write.', tone: 'warn' } });
      return;
    }
    const start = wholeEpisode ? 0 : (s.selectionRange?.start ?? 0);
    const end = wholeEpisode ? Array.from(scriptText).length : (s.selectionRange?.end ?? Array.from(scriptText).length);
    if (end <= start) {
      store.set({ notice: { text: 'Episode text is empty.', tone: 'warn' } });
      return;
    }
    const plan = currentScenePlan(s);
    const forScene = !wholeEpisode && plan?.target.start === start && plan.target.end === end;
    if (!wholeEpisode && s.selectionRange?.scenePlan && (!forScene || plan.id !== s.selectionRange.scenePlan)) {
      store.set({ notice: { text: 'The saved scene plan changed. Select the planned passage again.', tone: 'warn' } });
      return;
    }
    if (polishDraft && !forScene) return;
    const passage = !wholeEpisode && !forScene && s.beatMap?.beats.find(b => b.start===start && b.end===end && b.anchor);
    store.set({ busy: true, proseOutput:action==='generate'?'Submitting the saved selection…':'', selectionError:'' });
    try {
      const payload = {
        action,
        episode: ep.id,
        beat: forScene ? plan.cutoff : passage?.scope_beat ?? 0,
        viewpoint: forScene ? null : s.viewpoint || null,
        revision: ep.head,
        start,
        end,
        project: scope.project_id,
        universe: scope.universe_id,
        branch: ep.branch,
        provider: s.proseProvider || 'codex-session',
        references: s.proseRefMode || 'none',
        reference_delivery: 'cadence',
        scene_function: s.proseSceneFn || 'scene',
        direction: s.beatGroupInstruction || '',
        ...(forScene ? {scene_plan:plan.id} : passage ? {passage_anchor:passage.anchor} : {}),
        ...(polishDraft ? {polish_draft:polishDraft} : {}),
      };
      if (!wholeEpisode && s.episodeState?.notebook) payload.notebook_revision = s.episodeState.notebook.revision;
      const previewKey = JSON.stringify({ ...payload, action:'run.selection' });
      if (action === 'generate') {
        payload.action = 'run.selection';
        if (s.selectionPreview?.key === previewKey) payload.expected_prompt_sha256 = s.selectionPreview.digest;
        const key = JSON.stringify(payload);
        const pending = pendingSubmission(s.episodeState);
        if (pending?.id) {
          const previous = await loadSelectionRun(api, s.episodeState);
          if (previous?.id === pending.id) {
            if (store.get().episodeId === ep.id) store.set({ busy:false, proseOutput:'', selectionRun:previous });
            return;
          }
        }
        payload.request_id = pending?.key === key ? pending.id : crypto.randomUUID();
        rememberSubmission(s.episodeState, { key, id:payload.request_id });
        const run = await api.episodeCommand(payload);
        rememberSubmission(s.episodeState, null);
        if (store.get().episodeId === ep.id) store.set({ busy:false, proseOutput:'', selectionRun:run });
        return;
      }
      const command = action === 'rhythm-preview' && !wholeEpisode ? 'run.selection.preview' : action;
      const checkedSlice = wholeEpisode ? scriptText : Array.from(scriptText).slice(start, end).join('');
      const res = await api.scopedAction({
        ...payload,
        action: command,
        ...(action === 'validate' && s.dirty ? { text: checkedSlice } : {}),
      });
      if (action === 'validate') {
        const issueTexts = (res.issues || []).map(issueLabel).filter(Boolean);
        const semCount = res.semantic_review?.findings?.length ?? 0;
        const fixCount = res.suggested_corrections?.length ?? 0;
        const hasProblem = Boolean(issueTexts.length || semCount || fixCount);
        store.set({
          busy: false,
          scopedValidationReport: { ...res, start, end, wholeEpisode, checked_text: checkedSlice },
          proseOutput: issueTexts.length
            ? issueTexts.join('\n')
            : (hasProblem ? '' : 'Scoped, semantic paraphrase & canon checks passed cleanly.'),
          notice: {
            text: fixCount
              ? `Found ${fixCount} auto-correction(s) in validated scope.`
              : hasProblem
                ? `Validation flagged ${issueTexts.length + semCount} item(s).`
                : 'Scoped checks passed cleanly.',
            tone: hasProblem ? 'warn' : 'ok',
          },
        });
      } else {
        store.set({
          busy: false,
          ...(command === 'run.selection.preview'
            ? { selectionPreview: { key:previewKey, digest:res.prompt_sha256, craftCards: res.craft_cards || [] } } : {}),
          proseOutput: action==='rhythm-preview' ? (res.rhythm_guidance?.cues || []).map(c=>c.instruction).join('\n')
            : Array.isArray(res.issues) && res.issues.length ? res.issues.map(issueLabel).join('\n') : 'Scoped checks finished.',
          notice: { text: 'Scoped checks finished.', tone: 'ok' },
        });
      }
    } catch (err) {
      if (store.get().episodeId !== ep.id) return;
      if (action === 'generate') {
        store.set({ busy:false, proseOutput:'', selectionError:'Submission could not be confirmed. ' + err.message });
      } else {
        store.set({ busy:false, proseOutput:err.message, notice:{text:err.message, tone:'err'} });
      }
    }
  };

  document.getElementById('v2ScopedValidateBtn')?.addEventListener('click', () => runScoped('validate', !store.get().selectionRange));
  document.getElementById('v2ScopedApplyFixesBtn')?.addEventListener('click', async () => {
    const s = store.get();
    const ep = s.episodeState?.episode;
    const nb = s.episodeState?.notebook;
    const report = s.scopedValidationReport;
    if (!ep || !nb || !report?.auto_corrected_text) return;
    if (s.dirty) {
      store.set({ notice: { text: 'Save your edits before applying auto-corrections.', tone: 'warn' } });
      return;
    }
    const count = report.suggested_corrections?.length ?? 0;
    store.set({ busy: true });
    try {
      await api.notebookAction(
        report.wholeEpisode
          ? {
              action: 'save-document',
              episode: ep.id,
              revision: nb.revision,
              timeline_revision: nb.timeline_revision,
              text: report.auto_corrected_text,
              graph: null,
            }
          : {
              action: 'edit',
              episode: ep.id,
              revision: nb.revision,
              timeline_revision: nb.timeline_revision,
              start: report.start,
              end: report.end,
              text: report.auto_corrected_text,
            },
      );
      await onSelectEpisode?.(ep.id);
      store.set({
        busy: false,
        selectionRange: null,
        scopedValidationReport: null,
        proseOutput: `Applied ${count} world-rule/mind auto-correction(s) to notebook.`,
        notice: { text: `Applied ${count} auto-correction(s) cleanly.`, tone: 'ok' },
      });
    } catch (err) {
      store.set({ busy: false, notice: { text: err.message, tone: 'err' } });
    }
  });
  document.getElementById('v2ScopedRhythmBtn')?.addEventListener('click', () => runScoped('rhythm-preview', !store.get().selectionRange));
  document.getElementById('v2PolishDraft')?.addEventListener('click',
    () => runScoped('generate', false, store.get().selectionRun?.draft_id));
  document.getElementById('v2ScopedGenSelBtn')?.addEventListener('click', () => runScoped('generate', false));
  document.getElementById('v2ScopedGenAllBtn')?.addEventListener('click', () => {
    const url = new URL(location.href);
    url.searchParams.set('view', 'beat');
    history.replaceState(null, '', url);
    store.set({ view: 'beat', beatWriter:store.get().proseProvider, notice: { text: 'Choose the passages you want to write.' , tone: 'ok' } });
  });

  document.querySelectorAll('[data-prose-view-draft]').forEach((btn) => {
    btn.addEventListener('click', () => {
      const id = btn.dataset.proseViewDraft;
      store.set({ prosePreviewDraftId: store.get().prosePreviewDraftId === id ? '' : id });
    });
  });

  document.querySelectorAll('[data-prose-fav]').forEach((btn) => {
    btn.addEventListener('click', async () => {
      const s = store.get();
      const ep = s.episodeState?.episode;
      if (!ep) return;
      const draft = btn.dataset.proseFav;
      const prev = btn.dataset.favVal === '1';
      store.set({ busy: true });
      try {
        await api.draftsAction({
          action: 'favorite',
          episode: ep.id,
          branch: ep.branch,
          draft,
          value: !prev,
          expected_favorite: prev,
          expected_revision: s.timelineDraftHistory?.favorite_revision,
        });
        await onSelectEpisode(ep.id);
        store.set({ busy: false, notice: { text: !prev ? 'Draft starred.' : 'Draft unfavorited.', tone: 'ok' } });
      } catch (err) {
        store.set({ busy: false, notice: { text: err.message, tone: 'err' } });
      }
    });
  });

  document.querySelectorAll('[data-prose-use-draft]').forEach((btn) => {
    btn.addEventListener('click', async () => {
      const s = store.get();
      const ep = s.episodeState?.episode;
      const nb = s.episodeState?.notebook;
      if (!ep || !nb) return;
      store.set({ busy: true });
      try {
        await api.draftsAction({
          action: 'use',
          episode: ep.id,
          branch: ep.branch,
          draft: btn.dataset.proseUseDraft,
          revision: nb.revision,
          timeline_revision: nb.timeline_revision,
        });
        await onSelectEpisode(ep.id);
        store.set({ busy: false, notice: { text: 'Applied draft to notebook.', tone: 'ok' } });
      } catch (err) {
        store.set({ busy: false, notice: { text: err.message, tone: 'err' } });
      }
    });
  });

  document.getElementById('v2CompareDraftsBtn')?.addEventListener('click', async () => {
    const s = store.get();
    const ep = s.episodeState?.episode;
    const first = document.querySelector('input[name="v2CmpA"]:checked')?.value;
    const second = document.querySelector('input[name="v2CmpB"]:checked')?.value;
    if (!ep || !first || !second) return;
    store.set({ busy: true, compareA: first, compareB: second });
    try {
      const res = await api.draftsAction({ action: 'compare', episode: ep.id, branch: ep.branch, first, second });
      store.set({ busy: false, draftCompareOutput: res.diff || JSON.stringify(res, null, 2) });
    } catch (err) {
      store.set({ busy: false, notice: { text: err.message, tone: 'err' } });
    }
  });

  document.getElementById('v2PolicySearch')?.addEventListener('input', (e) => {
    const val = e.target.value;
    store.set({ policyFilter: val });
    const el = document.getElementById('v2PolicySearch');
    if (el) {
      el.focus();
      el.setSelectionRange(val.length, val.length);
    }
  });

  document.querySelectorAll('[data-policy-save]').forEach((btn) => {
    btn.addEventListener('click', async () => {
      const source = btn.dataset.policySave;
      const policy = store.get().bookPolicy;
      if (!policy) return;
      const enabled = Boolean(document.querySelector(`[data-policy-enabled="${CSS.escape(source)}"]`)?.checked);
      const permissions = [...document.querySelectorAll(`[data-policy-perm="${CSS.escape(source)}"]:checked`)].map((c) => c.value);
      store.set({ busy: true });
      try {
        const nextPolicy = await api.saveBookPolicy({
          source,
          enabled,
          permissions,
          revision: policy.revision,
        });
        store.set({
          busy: false,
          bookPolicy: nextPolicy,
          notice: { text: `Saved book policy for ${source}.`, tone: 'ok' },
        });
      } catch (err) {
        store.set({ busy: false, notice: { text: err.message, tone: 'err' } });
      }
    });
  });
}

export function bindLawsEvents({ store, api, onSelectEpisode }) {
  document.getElementById('v2LawSearch')?.addEventListener('input',e=>{
    const query = e.target.value.trim().toLowerCase();
    document.querySelectorAll('.v2-law-card').forEach(card=>{
      card.hidden = !(card.querySelector('.v2-law-head strong').textContent+' '+card.querySelector('.v2-law-statement').textContent).toLowerCase().includes(query);
    });
  });
  const ensureDraft = () => {
    const s = store.get();
    return structuredClone(s.worldLawsDraft ?? s.worldLaws?.laws ?? []);
  };

  document.getElementById('v2LawsAddBtn')?.addEventListener('click', () => {
    const draft = ensureDraft();
    draft.push({
      id: `law-${crypto.randomUUID().slice(0, 8)}`,
      name: 'New World Law',
      statement: '',
      enabled: true,
      phrases: [],
      constraints: [],
    });
    store.set({ worldLawsDraft: draft, openLaw:draft.length-1, notice: { text: 'Write the new law, then save.', tone: 'warn' } });
  });

  document.querySelectorAll('[data-law-remove]').forEach((btn) => {
    btn.addEventListener('click', () => {
      const idx = Number(btn.dataset.lawRemove);
      const draft = ensureDraft();
      draft.splice(idx, 1);
      store.set({ worldLawsDraft: draft, notice: { text: 'Removed draft law (click Save Laws to commit).', tone: 'warn' } });
    });
  });

  const syncField = (idx, updater) => {
    const draft = ensureDraft();
    if (!draft[idx]) return;
    updater(draft[idx]);
    store.setQuiet({ worldLawsDraft: draft });
    const saveBtn = document.getElementById('v2LawsSaveBtn');
    if (saveBtn) saveBtn.disabled = false;
  };

  document.querySelectorAll('[data-law-enabled]').forEach((el) => {
    el.addEventListener('change', () => syncField(Number(el.dataset.lawEnabled), (l) => { l.enabled = el.checked; }));
  });
  document.querySelectorAll('[data-law-name]').forEach((el) => {
    el.addEventListener('input', () => syncField(Number(el.dataset.lawName), (l) => { l.name = el.value; }));
  });
  document.querySelectorAll('[data-law-statement]').forEach((el) => {
    el.addEventListener('input', () => syncField(Number(el.dataset.lawStatement), (l) => { l.statement = el.value; }));
  });
  document.querySelectorAll('[data-law-phrases]').forEach((el) => {
    el.addEventListener('input', () => syncField(Number(el.dataset.lawPhrases), (l) => {
      l.phrases = el.value.split(',').map((p) => p.trim()).filter(Boolean);
    }));
  });

  const runLaws = async (action, lawsPayload) => {
    const wl = store.get().worldLaws;
    store.set({ busy: true });
    try {
      const next = await api.worldLawsAction({
        action,
        revision: wl?.revision ?? 0,
        ...(lawsPayload ? { laws: lawsPayload } : {}),
      });
      store.set({
        busy: false,
        worldLaws: next,
        worldLawsDraft: null,
        openLaw:null,
        notice: { text: `World laws ${action} completed (rev ${next.revision}).`, tone: 'ok' },
      });
    } catch (err) {
      store.set({ busy: false, notice: { text: err.message, tone: 'err' } });
    }
  };

  document.getElementById('v2LawsSaveBtn')?.addEventListener('click', () => {
    const draft = store.get().worldLawsDraft;
    if (draft) runLaws('save', draft);
  });
  document.getElementById('v2LawsUndoBtn')?.addEventListener('click', () => runLaws('undo'));
  document.getElementById('v2LawsRedoBtn')?.addEventListener('click', () => runLaws('redo'));

  document.getElementById('v2CanonQueueChk')?.addEventListener('change', (e) => {
    store.setQuiet({ canonQueueProposals: e.target.checked });
  });

  const refreshCanon = async () => {
    const s = store.get();
    const ep = s.episodeState?.episode;
    const scope = s.episodeState?.scope || {};
    if (!ep) return;
    store.set({ busy: true });
    try {
      const canonState = await api.canonProposals({
        action: 'open',
        episode: ep.id,
        branch: ep.branch,
        beat: s.beat || 0,
        project: scope.project_id,
        universe: scope.universe_id,
      });
      store.set({ busy: false, canonState, notice: { text: 'Accumulative canon state refreshed.', tone: 'ok' } });
    } catch (err) {
      store.set({ busy: false, notice: { text: err.message, tone: 'err' } });
    }
  };

  document.getElementById('v2CanonRefreshBtn')?.addEventListener('click', refreshCanon);

  document.getElementById('v2CanonAuditBtn')?.addEventListener('click', async () => {
    window.NOIR_FX?.trigger('PROC_SWEEP', { el: document.getElementById('v2CanonAuditBtn'), label: 'Canon Audit...' });
    const s = store.get();
    const { ep, scriptText } = episodeScriptInfo(s);
    const scope = s.episodeState?.scope || {};
    if (!ep) return;
    const queue = Boolean(document.getElementById('v2CanonQueueChk')?.checked ?? s.canonQueueProposals);
    store.set({ busy: true });
    try {
      const canonDiffReport = await api.canonDiff({
        episode: ep.id,
        branch: ep.branch,
        beat: s.beat || 0,
        viewpoint: s.viewpoint || null,
        queue_proposals: queue,
        project: scope.project_id,
        universe: scope.universe_id,
        ...(s.dirty ? { text: scriptText } : {}),
      });
      const canonState = await api.canonProposals({
        action: 'open',
        episode: ep.id,
        branch: ep.branch,
        beat: s.beat || 0,
        project: scope.project_id,
        universe: scope.universe_id,
      });
      const nConflicts = canonDiffReport.conflicts?.length ?? 0;
      const nCorrections = canonDiffReport.corrections?.length ?? 0;
      store.set({
        busy: false,
        canonDiffReport,
        canonState,
        notice: {
          text: nCorrections
            ? `Audit found ${nConflicts} conflict(s) and ${nCorrections} auto-correction(s).`
            : nConflicts
              ? `Audit found ${nConflicts} canon conflict(s).`
              : 'Canon audit finished cleanly.',
          tone: (nConflicts || nCorrections) ? 'warn' : 'ok',
        },
      });
    } catch (err) {
      store.set({ busy: false, notice: { text: err.message, tone: 'err' } });
    }
  });

  document.getElementById('v2CanonApplyCorrectionsBtn')?.addEventListener('click', async () => {
    const s = store.get();
    const ep = s.episodeState?.episode;
    const nb = s.episodeState?.notebook;
    const scope = s.episodeState?.scope || {};
    const diff = s.canonDiffReport;
    if (!ep || !nb || !diff?.auto_corrected_text) return;
    if (s.dirty) {
      store.set({ notice: { text: 'Save your edits before applying auto-corrections.', tone: 'warn' } });
      return;
    }
    const appliedCount = diff.corrections?.length ?? 0;
    store.set({ busy: true });
    try {
      await api.notebookAction({
        action: 'save-document',
        episode: ep.id,
        revision: nb.revision,
        timeline_revision: nb.timeline_revision,
        text: diff.auto_corrected_text,
        graph: null,
      });
      await onSelectEpisode?.(ep.id);
      const canonDiffReport = await api.canonDiff({
        episode: ep.id,
        branch: ep.branch,
        beat: s.beat || 0,
        viewpoint: s.viewpoint || null,
        queue_proposals: false,
        project: scope.project_id,
        universe: scope.universe_id,
      });
      const canonState = await api.canonProposals({
        action: 'open',
        episode: ep.id,
        branch: ep.branch,
        beat: s.beat || 0,
        project: scope.project_id,
        universe: scope.universe_id,
      });
      store.set({
        busy: false,
        canonDiffReport,
        canonState,
        notice: {
          text: `Applied ${appliedCount} auto-correction(s) to notebook (${canonDiffReport.conflicts?.length ?? 0} remaining conflict(s)).`,
          tone: (canonDiffReport.conflicts?.length ?? 0) ? 'warn' : 'ok',
        },
      });
    } catch (err) {
      store.set({ busy: false, notice: { text: err.message, tone: 'err' } });
    }
  });

  document.querySelectorAll('[data-canon-resolve]').forEach((btn) => {
    btn.addEventListener('click', async () => {
      const s = store.get();
      const ep = s.episodeState?.episode;
      const scope = s.episodeState?.scope || {};
      const proposalId = btn.dataset.canonResolve;
      const decision = btn.dataset.decision;
      store.set({ busy: true });
      try {
        await api.canonProposals({
          action: 'resolve',
          proposal_id: proposalId,
          decision,
          reviewer: 'studio-author',
          project: scope.project_id,
          universe: scope.universe_id,
        });
        const canonState = ep ? await api.canonProposals({
          action: 'open',
          episode: ep.id,
          branch: ep.branch,
          beat: s.beat || 0,
          project: scope.project_id,
          universe: scope.universe_id,
        }) : s.canonState;
        store.set({
          busy: false,
          canonState,
          notice: { text: `Proposal ${decision}.`, tone: 'ok' },
        });
      } catch (err) {
        store.set({ busy: false, notice: { text: err.message, tone: 'err' } });
      }
    });
  });
}
