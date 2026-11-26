/* Noir Fiction Studio v2 — M3 Unified Timeline & Branching Canvas */

import { escapeHtml } from './compose.js';
import { rememberCreation, confirmCreation } from './intake.js';

function episodeStageLabel(ep) {
  if (!ep) return { text: 'Draft', cls: 'v2-pill-draft' };
  if (/unprocessed/i.test(ep.title || '')) return { text: 'Unprocessed', cls: 'v2-pill-unprocessed' };
  if (ep.status === 'finished') return { text: 'Finished', cls: 'v2-pill-finished' };
  return { text: 'Draft', cls: 'v2-pill-draft' };
}

function branchCardsFor(timeline, branchId) {
  return (timeline?.cards || [])
    .filter((c) => c.branch === branchId)
    .sort((a, b) => a.position - b.position);
}

function currentPreviousAfter(timeline, ep) {
  if (!ep) return 'start';
  const list = branchCardsFor(timeline, ep.branch);
  const idx = list.findIndex((c) => c.id === ep.id);
  return idx <= 0 ? 'start' : list[idx - 1].id;
}

async function readCoverFile(file) {
  if (!file) return null;
  if (file.size > 1_000_000 || !['image/png', 'image/jpeg', 'image/webp'].includes(file.type)) {
    throw new Error('Choose a PNG, JPEG or WebP image up to 1 MB.');
  }
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(reader.result);
    reader.onerror = () => reject(new Error('Could not read the cover image.'));
    reader.readAsDataURL(file);
  });
}

export function drawTimelineWires(timeline) {
  const lanes = document.getElementById('v2TimelineLanes');
  const svg = document.getElementById('v2TimelineWires');
  if (!lanes || !svg || !timeline) return;

  svg.replaceChildren();
  const cr = lanes.getBoundingClientRect();
  const w = lanes.scrollWidth;
  const h = lanes.scrollHeight;
  svg.setAttribute('width', String(w));
  svg.setAttribute('height', String(h));
  svg.setAttribute('viewBox', `0 0 ${w} ${h}`);

  const rect = (el) => {
    const r = el.getBoundingClientRect();
    return {
      left: r.left - cr.left,
      right: r.right - cr.left,
      top: r.top - cr.top,
      bottom: r.bottom - cr.top,
      mid: r.top - cr.top + r.height / 2,
      center: r.left - cr.left + r.width / 2,
    };
  };

  const addPath = (d) => {
    const path = document.createElementNS('http://www.w3.org/2000/svg', 'path');
    path.setAttribute('d', d);
    svg.appendChild(path);
  };

  const cards = [...lanes.querySelectorAll('.v2-tl-card')];
  for (const branch of timeline.branches || []) {
    const rows = cards.filter((el) => el.dataset.branch === branch.id);
    for (let i = 1; i < rows.length; i += 1) {
      const a = rect(rows[i - 1]);
      const b = rect(rows[i]);
      const midX = (a.right + b.left) / 2;
      addPath(`M ${a.right} ${a.mid} H ${midX} V ${b.mid} H ${b.left}`);
    }
    if (branch.parent && branch.fork_episode && rows.length) {
      const parentCard = cards.find((el) => el.dataset.episode === branch.fork_episode);
      if (parentCard) {
        const a = rect(parentCard);
        const b = rect(rows[0]);
        const midY = (a.bottom + b.top) / 2;
        addPath(`M ${a.center} ${a.bottom} V ${midY} H ${b.center} V ${b.top}`);
      }
    }
  }
}

export function renderTimelineStage(state) {
  const timeline = state.timeline;
  const cards = timeline?.cards || [];
  const archived = timeline?.archived_cards || [];
  const branches = [...(timeline?.branches || [])].sort((a, b) =>
    a.id === 'main' ? -1 : b.id === 'main' ? 1 : a.id.localeCompare(b.id)
  );
  const hist = timeline?.history || { can_undo: false, can_redo: false };
  const zoom = Math.min(1.25, Math.max(.6, Number(state.timelineZoom) || 1));

  return `
    <div class="v2-tl-shell">
      <section class="v2-tl-toolbar">
        <div class="v2-tl-title-group">
          <h1>Project Timeline</h1>
          <span>${cards.length} ${cards.length === 1 ? 'episode' : 'episodes'} · ${branches.length} ${branches.length === 1 ? 'branch' : 'branches'}</span>
        </div>
        <div class="v2-tl-actions">
          <button type="button" class="v2-tl-btn" id="v2OpenStoryTrack" ${state.busy || !state.episodeState?.episode?.head ? 'disabled' : ''}>Story beats</button>
          <button type="button" class="v2-tl-btn v2-tl-btn-primary" id="v2AddEpisodeBtn" ${state.busy ? 'disabled' : ''}>+ Add Episode</button>
          <button type="button" class="v2-tl-btn" id="v2TlUndoBtn" ${state.busy || !hist.can_undo ? 'disabled' : ''}>Timeline Undo</button>
          <button type="button" class="v2-tl-btn" id="v2TlRedoBtn" ${state.busy || !hist.can_redo ? 'disabled' : ''}>Timeline Redo</button>
          ${cards.length === 0 ? `<button type="button" class="v2-tl-btn" id="v2TlStartersBtn" ${state.busy ? 'disabled' : ''}>Starter Cards</button>` : ''}
          <div class="v2-tl-zoom" role="group" aria-label="Timeline zoom"><button type="button" class="v2-tl-btn" data-zoom="out" aria-label="Zoom out">−</button><button type="button" class="v2-tl-btn" data-zoom="fit" aria-label="Fit timeline">${Math.round(zoom*100)}%</button><button type="button" class="v2-tl-btn" data-zoom="in" aria-label="Zoom in">+</button></div>
          ${archived.length ? `
            <button type="button" class="v2-tl-btn" id="v2TlRemovedToggle" aria-expanded="${state.timelineRemovedOpen ? 'true' : 'false'}">
              Removed (${archived.length})
            </button>
          ` : ''}
        </div>
      </section>

      ${state.timelineRemovedOpen && archived.length ? `
        <section class="v2-tl-removed-bar" aria-label="Removed episodes">
          <strong>Removed episodes</strong>
          <div class="v2-tl-removed-list">
            ${archived.map((e) => `
              <button type="button" class="v2-tl-btn" data-restore-episode="${escapeHtml(e.id)}" ${state.busy ? 'disabled' : ''}>
                Restore ${escapeHtml(e.title)}
              </button>
            `).join('')}
          </div>
        </section>
      ` : ''}

      <section class="v2-tl-canvas-wrap">
        <div class="v2-tl-canvas" id="v2TimelineCanvas" style="--episode-card-width:${Math.round(190*zoom)}px">
          <svg class="v2-tl-wires" id="v2TimelineWires" aria-hidden="true"></svg>
          <div class="v2-tl-lanes" id="v2TimelineLanes">
            ${!branches.length || !cards.length ? `
              <p class="v2-muted" style="color: var(--ink-muted-on-chrome)">No episodes on the timeline yet. Click "+ Add Episode" or "Starter Cards" to begin.</p>
            ` : branches.map((branch) => {
              const laneCards = branchCardsFor(timeline, branch.id);
              return `
                <div class="v2-tl-lane" data-lane="${escapeHtml(branch.id)}">
                  <div class="v2-tl-lane-label">
                    ${branch.id === 'main' ? 'Main timeline' : escapeHtml(branch.id)}
                    ${branch.parent ? `<small>From ${escapeHtml(cards.find(c=>c.id===branch.fork_episode)?.title || branch.parent)} · beat ${branch.fork_beat}</small>` : ''}
                  </div>
                  ${laneCards.map((c) => {
                    const badge = episodeStageLabel(c);
                    const hasCover = c.cover && /^data:image\/(png|jpeg|webp);base64,/.test(c.cover);
                    return `
                      <article
                        class="v2-tl-card ${c.id === state.episodeId ? 'is-selected' : ''}"
                        data-episode="${escapeHtml(c.id)}"
                        data-branch="${escapeHtml(c.branch)}"
                        tabindex="0"
                        aria-label="${escapeHtml(c.title)} · ${escapeHtml(c.branch)} · ${escapeHtml(badge.text)}"
                      >
                        <div class="v2-tl-cover" title="Double-click or click ✎ to set cover image">
                          ${hasCover ? `<img src="${escapeHtml(c.cover)}" alt="Cover for ${escapeHtml(c.title)}">` : `<div class="v2-tl-cover-empty"><span aria-hidden="true">${String(laneCards.indexOf(c)+1).padStart(2,'0')}</span><small>Add cover art</small></div>`}
                          <button type="button" class="v2-tl-cover-edit" data-cover-edit="${escapeHtml(c.id)}" aria-label="Change cover for ${escapeHtml(c.title)}">✎</button>
                          <input type="file" accept="image/png,image/jpeg,image/webp" hidden data-cover-input="${escapeHtml(c.id)}" data-head="${c.head}">
                        </div>
                        <div class="v2-tl-card-body" title="Double-click to open draft variants"><strong class="v2-tl-card-title">${escapeHtml(c.title)}</strong>
                        <div class="v2-tl-card-meta">
                          <span>Episode ${laneCards.indexOf(c)+1}</span>
                          <span class="v2-pill ${badge.cls}">${escapeHtml(badge.text)}</span>
                        </div>
                        </div>
                        <div class="v2-tl-card-footer">
                          <button type="button" class="v2-tl-btn" data-open-compose="${escapeHtml(c.id)}">Compose</button>
                          <button type="button" class="v2-tl-btn" data-open-variants="${escapeHtml(c.id)}">Drafts</button>
                          <button type="button" class="v2-tl-btn v2-tl-drag" data-drag-card="${escapeHtml(c.id)}" draggable="true" aria-label="Move ${escapeHtml(c.title)}" title="Drag to reorder, or click to open placement controls">⋮⋮</button>
                        </div>
                      </article>
                    `;
                  }).join('')}
                </div>
              `;
            }).join('')}
          </div>
        </div>
        <p class="v2-tl-hint">Double-click a cover to change it, or a title to open its drafts. Drag an episode by its grip to place it on the same branch.</p>
      </section>
    </div>

    <dialog id="v2NewEpisodeDialog" class="v2-tl-dialog" aria-labelledby="v2NewEpTitle">
      <form id="v2NewEpisodeForm" class="v2-tl-insp-grid">
        <h2 id="v2NewEpTitle">Add an episode</h2>
        <label class="v2-tl-insp-field">
          Episode title
          <input id="v2NewEpTitleInput" required maxlength="200" autocomplete="off" placeholder="e.g. Episode 04">
        </label>
        <label class="v2-tl-insp-field">
          Timeline branch
          <select id="v2NewEpBranch">
            ${(timeline?.branches || [{ id: 'main' }]).map((b) => `<option value="${escapeHtml(b.id)}">${b.id === 'main' ? 'Main timeline' : escapeHtml(b.id)}</option>`).join('')}
          </select>
        </label>
        <label class="v2-tl-insp-field">
          Place after
          <select id="v2NewEpAfter"></select>
        </label>
        <label class="v2-tl-insp-field">
          Cover image (optional, PNG/JPEG/WebP up to 1 MB)
          <input id="v2NewEpCover" type="file" accept="image/png,image/jpeg,image/webp">
        </label>
        <p id="v2NewEpMsg" class="v2-muted" role="status"></p>
        <div class="v2-tl-dialog-actions">
          <button type="button" class="v2-tl-btn" id="v2NewEpImport">Import PDF or DOCX</button>
          <button type="button" class="v2-tl-btn" id="v2CancelNewEpBtn">Cancel</button>
          <button type="submit" class="v2-tl-btn v2-tl-btn-primary">Create episode</button>
        </div>
      </form>
    </dialog>
  `;
}

export function renderTimelineInspector(state) {
  const timeline = state.timeline;
  const ep = state.episodeState?.episode;
  if (!ep) {
    return `
      <div class="v2-inspector-card">
        <h2>Timeline Inspector</h2>
        <p class="v2-muted">Select an episode card on the canvas to reorder, manage covers, branch, or inspect drafts and events.</p>
      </div>
    `;
  }

  const branchCards = branchCardsFor(timeline, ep.branch);
  const others = branchCards.filter((c) => c.id !== ep.id);
  const idx = branchCards.findIndex((c) => c.id === ep.id);
  const prevAfter = currentPreviousAfter(timeline, ep);
  const events = state.timelineEvents || [];
  const drafts = state.timelineDrafts || [];
  const favHist = state.timelineDraftHistory || {};
  const branchInfo = (timeline?.branches || []).find((b) => b.id === ep.branch);
  const parentEpisodes = branchInfo?.parent ? branchCardsFor(timeline, branchInfo.parent) : (timeline?.cards || []);

  if (state.timelinePanel === 'drafts') return `
    <div class="v2-inspector-card v2-variant-drawer" aria-label="Episode drafts">
      <button type="button" class="v2-tl-btn" id="v2TimelineBackToEpisode">← Episode</button>
      <h2>${escapeHtml(ep.title)}</h2><p class="v2-muted">Draft variants · ${drafts.length} saved</p>
      ${drafts.length ? `<div class="v2-tl-list">${drafts.map((d,i)=>`<article class="v2-tl-item">
        <strong>Draft ${drafts.length-i}${d.favorite?' · ★':''}</strong>
        <small>${escapeHtml(d.origin === 'imported' ? 'Imported' : d.origin === 'generated' ? 'Generated' : 'Saved')} · ${escapeHtml(d.status==='PROPOSED' ? 'Ready to apply' : d.status || 'Saved')} · source r${d.timeline_revision ?? d.scope?.revision ?? ep.head}</small>
        <div class="v2-tl-insp-row"><button type="button" class="v2-tl-btn" data-open-saved-variant="${escapeHtml(d.id)}">Open</button>
          <button type="button" class="v2-tl-btn" data-fav-draft="${escapeHtml(d.id)}" data-fav-val="${d.favorite ? '1':'0'}">${d.favorite?'Unfavorite':'Favorite'}</button></div>
      </article>`).join('')}</div><button type="button" class="v2-tl-btn" id="v2CompareFromTimeline">Compare in Prose Engine</button>` : '<p>No drafts yet. Write from the Beat Map to save a variant here.</p>'}
    </div>`;

  return `
    <div class="v2-inspector-card">
      <h2>Selected episode</h2>
      <div class="v2-tl-insp-grid">
        <div>
          <strong>${escapeHtml(ep.title)}</strong>
          <div class="v2-muted" style="font-size:12px">${escapeHtml(ep.branch)} · ${escapeHtml(ep.status)} · r${ep.head}</div>
        </div>
        <div class="v2-tl-insp-row">
          <button type="button" class="v2-tl-btn v2-tl-btn-primary" id="v2InspOpenCompose">Open in Compose</button>
          <button type="button" class="v2-tl-btn" id="v2ShowTimelineDrafts">Drafts (${drafts.length})</button>
          <button type="button" class="v2-tl-btn v2-tl-btn-danger" id="v2InspArchiveEp" ${state.busy ? 'disabled' : ''}>Remove</button>
        </div>

        <label class="v2-tl-insp-field">
          Order on branch
          <select id="v2InspMoveAfter" ${state.busy || !others.length ? 'disabled' : ''}>
            <option value="start" ${prevAfter === 'start' ? 'selected' : ''}>At the start</option>
            ${others.map((o) => `<option value="${escapeHtml(o.id)}" ${prevAfter === o.id ? 'selected' : ''}>After ${escapeHtml(o.title)}</option>`).join('')}
          </select>
        </label>
        <div class="v2-tl-insp-row">
          <button type="button" class="v2-tl-btn" id="v2InspMoveEarlier" ${state.busy || idx <= 0 ? 'disabled' : ''}>← Earlier</button>
          <button type="button" class="v2-tl-btn" id="v2InspMoveLater" ${state.busy || idx < 0 || idx >= branchCards.length - 1 ? 'disabled' : ''}>Later →</button>
          <button type="button" class="v2-tl-btn" id="v2InspMoveApply" ${state.busy || !others.length ? 'disabled' : ''}>Move</button>
        </div>

        <div class="v2-tl-insp-row">
          <button type="button" class="v2-tl-btn" id="v2InspUndoCover" ${state.busy || !ep.can_undo_cover ? 'disabled' : ''}>Undo cover</button>
          <button type="button" class="v2-tl-btn" id="v2InspRedoCover" ${state.busy || !ep.can_redo_cover ? 'disabled' : ''}>Redo cover</button>
        </div>
      </div>
    </div>

    <details class="v2-inspector-card v2-tl-details"><summary>Story continuity</summary>
    <div class="v2-inspector-card">
      <h2>Episode status</h2>
      <div class="v2-tl-insp-grid">
        <div class="v2-tl-insp-row">
          <button type="button" class="v2-tl-btn v2-tl-btn-primary" id="v2InspFinishBtn" ${state.busy || ep.status === 'finished' ? 'disabled' : ''}>Finish revision</button>
          <button type="button" class="v2-tl-btn" id="v2InspReopenBtn" ${state.busy || ep.status !== 'finished' ? 'disabled' : ''}>Reopen draft</button>
        </div>
      </div>
    </div>

    <div class="v2-inspector-card">
      <h2>Branching</h2>
      <div class="v2-tl-insp-grid">
        <label class="v2-tl-insp-field">
          Branch name
          <input id="v2InspForkBranch" placeholder="e.g. Alternate ending" maxlength="100">
        </label>
        <label class="v2-tl-insp-field">
          Fork at beat
          <input id="v2InspForkBeat" type="number" min="0" value="${state.beat}">
        </label>
        <button type="button" class="v2-tl-btn" id="v2InspForkBtn" ${state.busy ? 'disabled' : ''}>Create branch</button>

        <details class="v2-tl-details">
          <summary>Rejoin event to parent</summary>
          <div class="v2-tl-insp-grid" style="margin-top:8px">
            <label class="v2-tl-insp-field">
              Event to carry over
              <select id="v2RejoinEventId">${events.filter(e=>e.status==='approved').map(e=>`<option value="${escapeHtml(e.id)}">${escapeHtml(String(e.content || e.id).slice(0,100))}</option>`).join('')}</select>
            </label>
            <label class="v2-tl-insp-field">
              Target parent episode
              <select id="v2RejoinTarget">
                ${parentEpisodes.map((p) => `<option value="${escapeHtml(p.id)}">${escapeHtml(p.title)}</option>`).join('')}
              </select>
            </label>
            <label class="v2-tl-insp-field">
              Target beat
              <input id="v2RejoinBeat" type="number" min="0" value="0">
            </label>
            <label class="v2-tl-check">
              <input type="checkbox" id="v2RejoinPermitted">
              Permit transfer
            </label>
            <button type="button" class="v2-tl-btn" id="v2RejoinSubmitBtn" ${state.busy ? 'disabled' : ''}>Transfer event</button>
          </div>
        </details>
      </div>
    </div>

    <div class="v2-inspector-card">
      <h2>Timeline events (${events.length})</h2>
      <div class="v2-tl-insp-grid">
        ${events.length ? `
          <div class="v2-tl-list">
            ${events.map((ev) => `
              <div class="v2-tl-item">
                <strong>Beat ${ev.beat} · ${escapeHtml(ev.status)}</strong>
                <span>${escapeHtml(ev.content || '')}</span>
                ${ev.form_id ? `<small>${escapeHtml(ev.form_character)}:${escapeHtml(ev.form_id)} (${escapeHtml(ev.form_action)})</small>` : ''}
                <div class="v2-tl-insp-row">
                  ${ev.status === 'draft' ? `
                    ${ev.form_id ? `<button type="button" class="v2-tl-btn" data-unbind-event="${escapeHtml(ev.id)}">Unbind form</button>` : ''}
                    <button type="button" class="v2-tl-btn" data-remove-event="${escapeHtml(ev.id)}">Remove</button>
                    <button type="button" class="v2-tl-btn v2-tl-btn-primary" data-approve-event="${escapeHtml(ev.id)}">Approve</button>
                  ` : `
                    ${ev.rejoined
                      ? `<button type="button" class="v2-tl-btn" data-unrejoin-event="${escapeHtml(ev.id)}">Undo rejoin</button>`
                      : `<button type="button" class="v2-tl-btn" data-unapprove-event="${escapeHtml(ev.id)}">Unapprove</button>`}
                  `}
                </div>
              </div>
            `).join('')}
          </div>
        ` : `<p class="v2-muted">No timeline events recorded for this episode.</p>`}

        <details class="v2-tl-details">
          <summary>+ Add draft event</summary>
          <div class="v2-tl-insp-grid" style="margin-top:8px">
            <label class="v2-tl-insp-field">
              Beat
              <input id="v2NewEventBeat" type="number" min="0" value="${state.beat}">
            </label>
            <label class="v2-tl-insp-field">
              Description
              <textarea id="v2NewEventContent" rows="2" placeholder="What happens at this beat?"></textarea>
            </label>
            <label class="v2-tl-insp-field">
              Viewpoint (optional)
              <input id="v2NewEventViewpoint" placeholder="Narrator" value="${escapeHtml(state.viewpoint)}">
            </label>
            <button type="button" class="v2-tl-btn v2-tl-btn-primary" id="v2AddEventBtn" ${state.busy ? 'disabled' : ''}>Save draft event</button>
          </div>
        </details>
      </div>
    </div>

    </details>
    <details class="v2-inspector-card v2-tl-details"><summary>Draft history</summary>
      <h2>Draft variants (${drafts.length})</h2>
      <div class="v2-tl-insp-grid">
        <div class="v2-tl-insp-row">
          <button type="button" class="v2-tl-btn" id="v2FavUndoBtn" ${state.busy || !favHist.can_undo_favorite ? 'disabled' : ''}>Undo fav</button>
          <button type="button" class="v2-tl-btn" id="v2FavRedoBtn" ${state.busy || !favHist.can_redo_favorite ? 'disabled' : ''}>Redo fav</button>
        </div>
        ${drafts.length ? `
          <div class="v2-tl-list">
            ${drafts.map((d) => `
              <div class="v2-tl-item">
                <strong>Draft ${escapeHtml(String(d.id).slice(0, 8))}</strong>
                <small>${escapeHtml(d.status || 'draft')}${d.favorite ? ' · ★ favorite' : ''}</small>
                <div class="v2-tl-insp-row">
                  <button type="button" class="v2-tl-btn" data-fav-draft="${escapeHtml(d.id)}" data-fav-val="${d.favorite ? '1' : '0'}">
                    ${d.favorite ? 'Unfavorite' : 'Favorite'}
                  </button>
                  ${typeof d.text === 'string' ? `<button type="button" class="v2-tl-btn" data-preview-draft="${escapeHtml(d.id)}">Preview</button>` : ''}
                </div>
                ${state.timelineDraftPreviewId === d.id && typeof d.text === 'string' ? `
                  <pre class="v2-tl-draft-preview">${escapeHtml(d.text)}</pre>
                ` : ''}
              </div>
            `).join('')}
          </div>
        ` : `<p class="v2-muted">No saved drafts for this episode yet.</p>`}
      </div>
    </details>
  `;
}

export function bindTimelineEvents({ store, api, onSelectEpisode, onRefreshTimeline, onView, onOpenDraft }) {
  const cur = store.get();
  requestAnimationFrame(() => drawTimelineWires(store.get().timeline));

  const change = (action, item, fields = {}) => api.timelineAction({
    action, episode: item?.id, branch: item?.branch, episode_revision: item?.head,
    expected_revision: cur.timeline?.history?.revision,
    project: cur.timeline?.scope?.project_id, universe: cur.timeline?.scope?.universe_id, ...fields,
  });
  const runTimeline = async (fn, successMsg) => {
    store.set({ busy: true });
    try {
      const res = await fn();
      await onRefreshTimeline(res);
      if (successMsg) {
        store.set({ busy: false, notice: { text: res?.status === 'REPLAYED' ? 'This change was already saved.' : successMsg, tone: 'ok' } });
      } else {
        store.set({ busy: false });
      }
      return res;
    } catch (err) {
      if (!store.get().dirty && /changed elsewhere/.test(err.message)) {
        await onRefreshTimeline().catch(() => null);
      }
      store.set({ busy: false, notice: { text: err.message, tone: 'err' } });
      return null;
    }
  };

  let pickTimer;
  let dragged;
  const showEpisode = async (id, panel) => {
    clearTimeout(pickTimer);
    if (store.get().episodeState?.episode?.id !== id && !(await onSelectEpisode(id))) return;
    store.set({ timelinePanel:panel,inspectorOpen:true });
  };
  document.querySelectorAll('[data-zoom]').forEach(btn=>btn.addEventListener('click',()=>{
    const now=store.get().timelineZoom || 1;
    const canvas=document.getElementById('v2TimelineCanvas');
    let next=btn.dataset.zoom==='in' ? now+.15 : now-.15;
    if (btn.dataset.zoom==='fit') {
      const max=Math.max(1,...(cur.timeline?.branches || []).map(b=>branchCardsFor(cur.timeline,b.id).length));
      next=Math.min(1,((canvas?.clientWidth || 800)-154-max*16)/(max*190));
    }
    store.set({timelineZoom:Math.max(.6,Math.min(1.25,next))});
  }));

  // Separate title/draft and cover activation; don't replace the card between clicks.
  document.querySelectorAll('.v2-tl-card[data-episode]').forEach((card) => {
    card.addEventListener('click', (e) => {
      if (e.target.closest('button,input,.v2-tl-cover') || e.detail > 1) return;
      clearTimeout(pickTimer);
      pickTimer = setTimeout(() => showEpisode(card.dataset.episode,'episode'),220);
    });
    card.querySelector('.v2-tl-card-body')?.addEventListener('dblclick', e => {
      e.preventDefault();
      showEpisode(card.dataset.episode,'drafts');
    });
    card.addEventListener('keydown', (e) => {
      if (e.key === 'Enter' && e.target === card) {
        e.preventDefault();
        showEpisode(card.dataset.episode,'episode');
      }
    });
    card.addEventListener('dragover', e => {
      if (!dragged || dragged.branch!==card.dataset.branch || dragged.id===card.dataset.episode) return;
      e.preventDefault();
      e.dataTransfer.dropEffect='move';
      const rect=card.getBoundingClientRect();
      card.dataset.dropSide=e.clientX < rect.left+rect.width/2 ? 'before' : 'after';
    });
    card.addEventListener('dragleave', e => { if (!card.contains(e.relatedTarget)) delete card.dataset.dropSide; });
    card.addEventListener('drop', e => {
      const side=card.dataset.dropSide;
      delete card.dataset.dropSide;
      if (!dragged || !side || dragged.branch!==card.dataset.branch || dragged.id===card.dataset.episode || store.get().busy) return;
      e.preventDefault();
      const item=dragged;
      const order=branchCardsFor(store.get().timeline,item.branch).filter(x=>x.id!==item.id);
      const index=order.findIndex(x=>x.id===card.dataset.episode);
      if (index < 0) return;
      const after=side==='after' ? order[index].id : (order[index-1]?.id || 'start');
      runTimeline(()=>change('timeline.move',item,{after}),`Moved ${item.title}.`);
    });
  });
  document.querySelectorAll('[data-drag-card]').forEach(btn=>{
    btn.addEventListener('dragstart',e=>{
      if (store.get().dirty || store.get().busy) { e.preventDefault(); return; }
      dragged=store.get().timeline?.cards?.find(c=>c.id===btn.dataset.dragCard);
      if (!dragged) return;
      e.dataTransfer.setData('text/plain',dragged.id);
      e.dataTransfer.effectAllowed='move';
    });
    btn.addEventListener('dragend',()=>{
      dragged=null;
      document.querySelectorAll('[data-drop-side]').forEach(c=>delete c.dataset.dropSide);
    });
    btn.addEventListener('click',()=>showEpisode(btn.dataset.dragCard,'episode'));
  });
  document.querySelectorAll('[data-open-variants]').forEach(btn=>btn.addEventListener('click',()=>showEpisode(btn.dataset.openVariants,'drafts')));

  document.querySelectorAll('[data-open-compose]').forEach((btn) => {
    btn.addEventListener('click', async (e) => {
      e.stopPropagation();
      const id = btn.dataset.openCompose;
      if (store.get().episodeId !== id) {
        if (!(await onSelectEpisode(id))) return;
      }
      store.setQuiet({activeDraftId:null});
      onView('compose');
    });
  });

  // Cover upload
  document.querySelectorAll('[data-cover-edit]').forEach((btn) => {
    btn.addEventListener('click', (e) => {
      e.stopPropagation();
      const id = btn.dataset.coverEdit;
      const input = document.querySelector(`[data-cover-input="${CSS.escape(id)}"]`);
      if (input) {
        input.value = '';
        input.click();
      }
    });
  });

  document.querySelectorAll('.v2-tl-cover').forEach((coverEl) => {
    coverEl.addEventListener('dblclick', (e) => {
      e.stopPropagation();
      const card = coverEl.closest('.v2-tl-card');
      const input = card?.querySelector('[data-cover-input]');
      if (input) {
        input.value = '';
        input.click();
      }
    });
  });

  document.querySelectorAll('[data-cover-input]').forEach((input) => {
    input.addEventListener('change', async () => {
      const file = input.files?.[0];
      if (!file) return;
      const id = input.dataset.coverInput;
      const cards = store.get().timeline?.cards || [];
      const card = cards.find((c) => c.id === id);
      if (!card) return;
      await runTimeline(async () => {
        const image = await readCoverFile(file);
        return change('timeline.cover.set',card,{cover_version:card.cover_version,cover:image});
      }, `Updated cover for ${card.title}.`);
    });
  });

  // Toolbar actions
  document.getElementById('v2TlUndoBtn')?.addEventListener('click', () => {
    runTimeline(() => change('timeline.undo'), 'Timeline change undone.');
  });

  document.getElementById('v2TlRedoBtn')?.addEventListener('click', () => {
    runTimeline(() => change('timeline.redo'), 'Timeline change reapplied.');
  });

  document.getElementById('v2TlStartersBtn')?.addEventListener('click', () => {
    runTimeline(() => api.timelineAction({ action: 'starters' }), 'Starter cards added as drafts.');
  });

  document.getElementById('v2TlRemovedToggle')?.addEventListener('click', () => {
    store.set({ timelineRemovedOpen: !store.get().timelineRemovedOpen });
  });

  document.querySelectorAll('[data-restore-episode]').forEach((btn) => {
    btn.addEventListener('click', () => {
      const id = btn.dataset.restoreEpisode;
      const card = cur.timeline?.archived_cards?.find(x => x.id === id);
      if (!card) return;
      runTimeline(async () => {
        const res = await change('timeline.restore',card);
        await onSelectEpisode(id);
        return res;
      }, 'Episode restored.');
    });
  });

  // Add Episode Modal
  const dialog = document.getElementById('v2NewEpisodeDialog');
  const branchSelect = document.getElementById('v2NewEpBranch');
  const afterSelect = document.getElementById('v2NewEpAfter');

  const populateAfter = () => {
    if (!branchSelect || !afterSelect) return;
    const branch = branchSelect.value || 'main';
    const list = branchCardsFor(store.get().timeline, branch);
    afterSelect.replaceChildren(
      new Option('At the end', 'end'),
      ...(list.length ? [new Option('At the start', 'start')] : []),
      ...list.map((e) => new Option(`After ${e.title}`, e.id))
    );
  };

  document.getElementById('v2AddEpisodeBtn')?.addEventListener('click', () => {
    if (!dialog) return;
    document.getElementById('v2NewEpisodeForm')?.reset();
    const msg = document.getElementById('v2NewEpMsg');
    if (msg) msg.textContent = '';
    populateAfter();
    dialog.showModal();
    document.getElementById('v2NewEpTitleInput')?.focus();
  });

  branchSelect?.addEventListener('change', populateAfter);
  document.getElementById('v2CancelNewEpBtn')?.addEventListener('click', () => dialog?.close());
  document.getElementById('v2NewEpImport')?.addEventListener('click', () => {
    const title=document.getElementById('v2NewEpTitleInput')?.value.trim();
    store.setQuiet({intake:{...store.get().intake, title, branch:branchSelect.value, after:afterSelect.value}});
    onView('start');
  });

  document.getElementById('v2NewEpisodeForm')?.addEventListener('submit', async (e) => {
    e.preventDefault();
    const msg = document.getElementById('v2NewEpMsg');
    const title = document.getElementById('v2NewEpTitleInput')?.value.trim() || '';
    const branch = branchSelect?.value || 'main';
    const after = afterSelect?.value || 'end';
    const coverInput = document.getElementById('v2NewEpCover');
    if (!title) {
      if (msg) msg.textContent = 'Enter an episode title.';
      return;
    }
    try {
      const cover = coverInput?.files?.[0] ? await readCoverFile(coverInput.files[0]) : null;
      const submit=e.submitter;
      if (submit) submit.disabled=true;
      try {
        const request_id=await rememberCreation(cur,'blank',[title,branch,after,cover]);
        const res = await api.intake({action:'episode.create', title, branch, after, cover, request_id,
          expected_revision:cur.timeline?.history?.revision,project:cur.timeline?.scope?.project_id,
          universe:cur.timeline?.scope?.universe_id});
        dialog?.close();
        await onSelectEpisode(res.episode);
        await onRefreshTimeline();
        confirmCreation(cur,'blank',request_id);
        store.set({notice:{text:res.status==='REPLAYED'?`Opened saved episode “${title}”.`:`Created episode “${title}”.`,tone:'ok'}});
      } finally { if (submit) submit.disabled=false; }
    } catch (err) {
      if (msg) msg.textContent = err.message;
    }
  });

  // Inspector controls
  const ep = cur.episodeState?.episode;
  if (!ep) return;

  document.getElementById('v2InspOpenCompose')?.addEventListener('click', () => {
    store.setQuiet({activeDraftId:null});
    onView('compose');
  });
  document.getElementById('v2ShowTimelineDrafts')?.addEventListener('click',()=>showEpisode(ep.id,'drafts'));
  document.getElementById('v2TimelineBackToEpisode')?.addEventListener('click',()=>showEpisode(ep.id,'episode'));
  document.getElementById('v2CompareFromTimeline')?.addEventListener('click',()=>onView('prose'));
  document.querySelectorAll('[data-open-saved-variant]').forEach(btn=>btn.addEventListener('click',()=>onOpenDraft(btn.dataset.openSavedVariant)));

  document.getElementById('v2InspArchiveEp')?.addEventListener('click', () => {
    if (store.get().dirty) {store.set({notice:{text:'Save the open notebook before removing this episode.',tone:'warn'}});return;}
    runTimeline(() => change('timeline.archive',ep), `Removed ${ep.title} (can be restored from Removed).`);
  });

  const moveEpisode = (params) => {
    runTimeline(
      () => change('timeline.move',ep,params),
      `Updated order for ${ep.title}.`
    );
  };
  document.getElementById('v2InspMoveEarlier')?.addEventListener('click', () => moveEpisode({ direction: 'earlier' }));
  document.getElementById('v2InspMoveLater')?.addEventListener('click', () => moveEpisode({ direction: 'later' }));
  document.getElementById('v2InspMoveApply')?.addEventListener('click', () => {
    const after = document.getElementById('v2InspMoveAfter')?.value || 'start';
    moveEpisode({ after });
  });

  document.getElementById('v2InspUndoCover')?.addEventListener('click', () => {
    runTimeline(
      () => api.timelineAction({ action: 'undo_cover', id: ep.id, expected_revision: ep.head, expected_cover: ep.cover }),
      'Previous cover restored.'
    );
  });
  document.getElementById('v2InspRedoCover')?.addEventListener('click', () => {
    runTimeline(
      () => api.timelineAction({ action: 'redo_cover', id: ep.id, expected_revision: ep.head, expected_cover: ep.cover }),
      'Cover reapplied.'
    );
  });

  document.getElementById('v2InspFinishBtn')?.addEventListener('click', () => {
    const reviewer = 'Author';
    runTimeline(
      () => api.timelineAction({ action: 'finish', id: ep.id, expected_revision: ep.head, reviewer }),
      `Marked ${ep.title} as finished.`
    );
  });

  document.getElementById('v2InspReopenBtn')?.addEventListener('click', () => {
    runTimeline(
      () => api.timelineAction({ action: 'reopen', id: ep.id, expected_revision: ep.head }),
      `Reopened ${ep.title} as draft.`
    );
  });

  document.getElementById('v2InspForkBtn')?.addEventListener('click', () => {
    const branch = document.getElementById('v2InspForkBranch')?.value.trim() || '';
    const beat = Number(document.getElementById('v2InspForkBeat')?.value || 0);
    if (!branch) {
      store.set({ notice: { text: 'Name the new branch first.', tone: 'warn' } });
      return;
    }
    runTimeline(
      () => api.timelineAction({ action: 'fork', branch, parent: ep.branch, episode: ep.id, beat }),
      `Created branch "${branch}" from ${ep.title} at beat ${beat}.`
    );
  });

  document.getElementById('v2RejoinSubmitBtn')?.addEventListener('click', () => {
    const event = document.getElementById('v2RejoinEventId')?.value.trim() || '';
    const target_episode = document.getElementById('v2RejoinTarget')?.value || '';
    const beat = Number(document.getElementById('v2RejoinBeat')?.value || 0);
    const source_id = `timeline:${ep.id}/${event}`;
    const reviewer = 'Author';
    const permitted = Boolean(document.getElementById('v2RejoinPermitted')?.checked);
    runTimeline(
      () => api.timelineAction({ action: 'rejoin', episode: ep.id, event, target_episode, beat, source_id, reviewer, permitted }),
      `Transferred event "${event}" to ${target_episode}.`
    );
  });

  // Event actions
  document.getElementById('v2AddEventBtn')?.addEventListener('click', () => {
    const event = document.getElementById('v2NewEventId')?.value.trim() || `evt-${crypto.randomUUID().slice(0, 8)}`;
    const beat = Number(document.getElementById('v2NewEventBeat')?.value || 0);
    const content = document.getElementById('v2NewEventContent')?.value.trim() || '';
    const viewpoint = document.getElementById('v2NewEventViewpoint')?.value.trim() || '';
    runTimeline(
      () => api.timelineAction({ action: 'event', episode: ep.id, event, beat, content, viewpoint }),
      `Saved draft event "${event}".`
    );
  });

  document.querySelectorAll('[data-unbind-event]').forEach((btn) => {
    btn.addEventListener('click', () => {
      runTimeline(
        () => api.timelineAction({ action: 'unbind_form', episode: ep.id, event: btn.dataset.unbindEvent }),
        'Form binding undone.'
      );
    });
  });

  document.querySelectorAll('[data-remove-event]').forEach((btn) => {
    btn.addEventListener('click', () => {
      runTimeline(
        () => api.timelineAction({ action: 'unadd_event', episode: ep.id, event: btn.dataset.removeEvent }),
        'Draft event removed.'
      );
    });
  });

  document.querySelectorAll('[data-approve-event]').forEach((btn) => {
    btn.addEventListener('click', () => {
      const reviewer = document.getElementById('v2InspReviewer')?.value.trim() || 'Author';
      runTimeline(
        () => api.timelineAction({
          action: 'review_event',
          episode: ep.id,
          event: btn.dataset.approveEvent,
          reviewer,
          source_id: `studio-${ep.id}`,
          permitted: true,
        }),
        `Approved event "${btn.dataset.approveEvent}".`
      );
    });
  });

  document.querySelectorAll('[data-unapprove-event]').forEach((btn) => {
    btn.addEventListener('click', () => {
      const reviewer = document.getElementById('v2InspReviewer')?.value.trim() || 'Author';
      runTimeline(
        () => api.timelineAction({ action: 'unreview_event', episode: ep.id, event: btn.dataset.unapproveEvent, reviewer }),
        'Event approval undone.'
      );
    });
  });

  document.querySelectorAll('[data-unrejoin-event]').forEach((btn) => {
    btn.addEventListener('click', () => {
      runTimeline(
        () => api.timelineAction({ action: 'unrejoin', target_episode: ep.id, event: btn.dataset.unrejoinEvent }),
        'Rejoin undone.'
      );
    });
  });

  // Draft variant actions
  document.querySelectorAll('[data-fav-draft]').forEach((btn) => {
    btn.addEventListener('click', () => {
      const draft = btn.dataset.favDraft;
      const prev = btn.dataset.favVal === '1';
      const rev = store.get().timelineDraftHistory?.favorite_revision;
      runTimeline(
        () => api.draftsAction({
          action: 'favorite',
          episode: ep.id,
          branch: ep.branch,
          draft,
          value: !prev,
          expected_favorite: prev,
          expected_revision: rev,
        }),
        !prev ? 'Draft starred.' : 'Draft favorite removed.'
      );
    });
  });

  document.querySelectorAll('[data-preview-draft]').forEach((btn) => {
    btn.addEventListener('click', () => {
      const id = btn.dataset.previewDraft;
      store.set({ timelineDraftPreviewId: store.get().timelineDraftPreviewId === id ? '' : id });
    });
  });

  document.getElementById('v2FavUndoBtn')?.addEventListener('click', () => {
    const rev = store.get().timelineDraftHistory?.favorite_revision;
    runTimeline(
      () => api.draftsAction({ action: 'undo-favorite', episode: ep.id, branch: ep.branch, expected_revision: rev }),
      'Draft favorite undone.'
    );
  });

  document.getElementById('v2FavRedoBtn')?.addEventListener('click', () => {
    const rev = store.get().timelineDraftHistory?.favorite_revision;
    runTimeline(
      () => api.draftsAction({ action: 'redo-favorite', episode: ep.id, branch: ep.branch, expected_revision: rev }),
      'Draft favorite redone.'
    );
  });
}
