/* Noir Fiction Studio v2 — M4/G3 Houdini Story Node Canvas & Character Form Junctions */

import { escapeHtml } from './compose.js';
import {
  getGraphData,
  blocksForCharacter,
  filterJunctions,
  resolveActiveJunction,
  buildCharacterTopology,
} from './graph_state.js';
import { fromBackendGraph, OPERATOR_SPECS, getOperatorSpec, isPortTypeCompatible } from './graph_engine.js';
import { createGraphController } from './graph_controller.js';
import { mountHoudiniCanvasView } from './graph_canvas_view.js';
import { playCookStart, playCookComplete } from './sound.js';
import { openFormBoard } from './form-board.js';
import { currentScenePlan, renderScenePlan, selectedSceneTurn } from './scene_plan.js';
import { renderCharSwitchyard, bindCharSwitchyard } from './char_switchyard.js';

let storyController = null;
let storyCanvasView = null;
let storyCanvasEl = null;
let storyThemeObserver = null;
let charCyInstance = null;
let mountedStoryEpisodeId = '';
let mountedStoryTheme = '';
let mountedCharKey = '';
let savedStoryCamera = { episodeId: '', camera: null };
let savedCharViewport = { key: '', zoom: null, pan: null };
let latestCtx = null;
const expandedCharClusters = new Set();

function cssVar(name, fallback) {
  const val = getComputedStyle(document.body).getPropertyValue(name).trim();
  return val || fallback;
}

function captureStoryViewport(episodeId) {
  if (!storyCanvasView || !episodeId) return;
  try {
    savedStoryCamera = {
      episodeId,
      camera: storyCanvasView.getCamera(),
    };
  } catch (_) {}
}

function captureCharViewport(key) {
  if (!charCyInstance || !key) return;
  try {
    savedCharViewport = {
      key,
      zoom: charCyInstance.zoom(),
      pan: { ...charCyInstance.pan() },
    };
  } catch (_) {}
}

const FORM_UNLOCK_MAP = {
  peter_griffin_celestial_variant: { episode: 'spring-break', pos: 10 },
  'rainee-split-1': { episode: 'spring-break', pos: 10 },
  'rainee-split-2': { episode: 'spring-break', pos: 10 },
  'rainee-split-3': { episode: 'spring-break', pos: 10 },
  nurse_pamela_franny_anderson: { episode: 'spring-break', pos: 10 },
  mtv_beach_host: { episode: 'spring-break', pos: 10 },
  rutgers_royal_persona: { episode: 'spring-break', pos: 10 },
  awakened_haley_fox: { episode: 'hot-scoomp', pos: 20 },
  big_tiddy_steve_stella: { episode: 'tapped-out', pos: 30 },
};

function formAvailabilityBadge(form, ep) {
  const unlockPos = Number(form.unlock_pos ?? FORM_UNLOCK_MAP[form.id]?.pos ?? 0);
  const unlockEp = form.unlock_episode || FORM_UNLOCK_MAP[form.id]?.episode || '';
  if (form.kind === 'base' || unlockPos <= 0) {
    return { text: 'BASE', locked: false };
  }
  const epPos = ep && ep.position != null ? Number(ep.position) : null;
  if (epPos !== null && epPos < unlockPos && !ep?.time_travel_override) {
    return { text: `🔒 LOCKED → ${unlockEp || 'later'} (${unlockPos})`, locked: true };
  }
  return { text: `✓ ${unlockEp ? `@ ${unlockEp}` : 'UNLOCKED'} (${unlockPos})`, locked: false };
}

function renderJunctionCards(filteredJunctions, state, allJunctions) {
  const ep = state.episodeState?.episode || null;
  return filteredJunctions
    .map((j) => {
      const charBlocks = blocksForCharacter(state, j.character_id, allJunctions);
      const isCardSelected =
        state.graphSelection?.characterId === j.character_id ||
        state.selectedProfile?.character === j.character_id;
      return `
        <article class="v2-junction-card ${isCardSelected ? 'is-selected' : ''}" data-junction-character="${escapeHtml(j.character_id)}">
          <div class="v2-junction-head">
            <strong>${escapeHtml(j.label || j.character_id)}</strong>
            <div class="v2-junction-badges">
              <span class="v2-pill">${charBlocks.length} ${charBlocks.length === 1 ? 'block' : 'blocks'}</span>
              <span class="v2-pill v2-pill-draft">${(j.forms || []).length} ${(j.forms || []).length === 1 ? 'form' : 'forms'}</span>
            </div>
          </div>
          <div class="v2-junction-forms">
            ${(j.forms || [])
              .map((f) => {
                const isSelected =
                  state.selectedProfile?.character === j.character_id &&
                  state.selectedProfile?.form === f.id;
                return `
                  <div class="v2-form-row ${isSelected ? 'is-selected' : ''}">
                    <div class="v2-form-thumb">
                      ${
                        f.image
                          ? `<img src="${escapeHtml(f.image)}" alt="${escapeHtml(f.display_label || f.label)}">`
                          : escapeHtml((f.display_label || f.label || '?').slice(0, 2).toUpperCase())
                      }
                    </div>
                    <div class="v2-form-info">
                      <strong>${escapeHtml(f.display_label || f.label || f.id)}</strong>
                      <small>${escapeHtml(f.kind || 'form')} · ${escapeHtml(f.status || 'active')}${f.link ? '' : ' · Mind socket empty'}</small>
                      ${(() => {
                        const gate = formAvailabilityBadge(f, ep);
                        return `<span class="v2-form-gate-pill ${gate.locked ? 'is-locked' : ''}">${escapeHtml(gate.text)}</span>`;
                      })()}
                    </div>
                    <button type="button" class="v2-tl-btn v2-tl-btn-primary"
                      data-open-form-board="${escapeHtml(f.port_id)}"
                      data-character="${escapeHtml(j.character_id)}"
                      aria-label="Open board for ${escapeHtml(f.display_label || f.label || f.id)}">Board</button>
                    <button
                      type="button"
                      class="v2-tl-btn"
                      data-inspect-form="${escapeHtml(f.id)}"
                      data-character="${escapeHtml(j.character_id)}"
                      data-node="${escapeHtml(f.port_id || j.junction_id)}"
                    >Inspect</button>
                  </div>
                `;
              })
              .join('')}
          </div>
        </article>
      `;
    })
    .join('');
}

function bridgeBeat(state) {
  const graph = state.formGraph;
  if (!graph?.bridge_cast) return null;
  const id = selectedSceneTurn(state)?.id || state.bridgeBeatId;
  return graph.beats.find(beat => beat.id === id) || graph.beats.at(-1);
}

export function renderGraphStage(state) {
  const ep = state.episodeState?.episode;
  const subtab = state.graphSubtab || 'switchyard';
  const snap = fromBackendGraph(getGraphData(state));
  const { nodes, edges } = snap;
  const prepared = state.preparation?.timeline_revision === ep?.head &&
    state.preparation?.notebook_revision === state.episodeState?.notebook?.revision ? state.preparation : null;
  const firstScene = prepared?.fragments?.[0];
  const sceneGraphs = firstScene
    ? '/scene-fragments?' + new URLSearchParams({episode:ep.id, fragment:firstScene.id}).toString() : '';
  const isDirty = Boolean(state.graphDraft || storyController?.isDirty());
  const canUndo = Boolean(storyController?.canUndo());
  const canRedo = Boolean(storyController?.canRedo());
  const fg = state.formGraph;
  const selectedBeat = bridgeBeat(state);
  const junctions = (fg?.junctions || []).map(group => selectedBeat ? {
    ...group, forms: group.forms.map(form => ({ ...form, status: selectedBeat.forms[form.port_id] })),
  } : group);
  const filteredJunctions = filterJunctions(junctions, state.graphFilter);
  const activeJ = resolveActiveJunction(junctions, filteredJunctions, state.selectedProfile, state.graphSelection);
  const activeBlocks = activeJ ? blocksForCharacter(state, activeJ.character_id, junctions) : [];

  return `
    <div class="v2-graph-shell">
      ${subtab === 'switchyard' && !state.triSplit ? `
        <section class="sg-subbar" aria-label="Graph workspace">
          <div class="sg-subtabs" role="tablist">
            <button type="button" class="sg-subtab" role="tab" data-graph-tab="switchyard" aria-selected="true">Form Switchyard</button>
            <button type="button" class="sg-subtab" role="tab" data-graph-tab="story" aria-selected="false">Story DAG</button>
            <button type="button" class="sg-subtab" role="tab" data-graph-tab="forms" aria-selected="false">Character Junctions (${junctions.length})</button>
          </div>
          <span class="v2-muted">${ep ? escapeHtml(ep.title) : 'All Sample Minds'} · Live Compose Sync</span>
        </section>
      ` : `
      <section class="v2-graph-toolbar">
        <div class="v2-graph-title-group">
          <h1>${subtab === 'story' ? 'Story Graph' : 'Character Form Junctions'}</h1>
          <span id="v2GraphMetaSummary">${ep ? escapeHtml(ep.title) : 'No episode'} · ${subtab === 'story' ? `${nodes.length} nodes · ${edges.length} edges` : `${junctions.length} characters`}</span>
          ${subtab === 'story' && isDirty ? `<span class="v2-graph-dirty-pill" id="v2GraphDirtyPill">Unsaved changes</span>` : `<span class="v2-graph-dirty-pill" id="v2GraphDirtyPill" hidden>Unsaved changes</span>`}
        </div>
        <div class="v2-graph-controls">
          <div class="v2-graph-subtabs" role="tablist" aria-label="Graph workspace">
            <button type="button" class="v2-graph-subtab" role="tab" data-graph-tab="switchyard" aria-selected="${subtab === 'switchyard' ? 'true' : 'false'}">Form Switchyard</button>
            <button type="button" class="v2-graph-subtab" role="tab" data-graph-tab="story" aria-selected="${subtab === 'story' ? 'true' : 'false'}">Story DAG</button>
            <button type="button" class="v2-graph-subtab" role="tab" data-graph-tab="forms" aria-selected="${subtab === 'forms' ? 'true' : 'false'}">Character Junctions (${junctions.length})</button>
          </div>
          ${sceneGraphs ? `<a class="v2-tl-btn" href="${escapeHtml(sceneGraphs)}">Prepared scene graphs</a>` : ''}
          ${subtab === 'story' ? `
            <button type="button" class="v2-tl-btn" id="v2GraphUndoBtn" ${state.busy || !canUndo ? 'disabled' : ''}>Undo</button>
            <button type="button" class="v2-tl-btn" id="v2GraphRedoBtn" ${state.busy || !canRedo ? 'disabled' : ''}>Redo</button>
            <button type="button" class="v2-tl-btn" id="v2GraphFitBtn" ${!nodes.length ? 'disabled' : ''}>Fit</button>
            <button type="button" class="v2-tl-btn" id="v2GraphLayoutBtn" ${nodes.length < 2 ? 'disabled' : ''}>Auto-Layout</button>
            <button type="button" class="v2-tl-btn" id="v2GraphAddNodeBtn" ${state.busy || !ep ? 'disabled' : ''}>+ Add Node</button>
            <button type="button" class="v2-tl-btn v2-tl-btn-primary" id="v2GraphSaveBtn" ${state.busy || !isDirty ? 'disabled' : ''}>Save Graph</button>
          ` : `
            <button type="button" class="v2-tl-btn" id="v2FgUndoBtn" ${state.busy || !fg?.can_undo_graph ? 'disabled' : ''}>Undo Form Graph</button>
            <button type="button" class="v2-tl-btn" id="v2FgRedoBtn" ${state.busy || !fg?.can_redo_graph ? 'disabled' : ''}>Redo Form Graph</button>
          `}
        </div>
      </section>
      `}

      ${subtab === 'switchyard' ? renderCharSwitchyard(state) : subtab === 'story' ? (
        !ep ? `
          <section class="v2-graph-empty">
            <h2>Select an episode</h2>
            <p>Choose an episode from the left rail to inspect or edit its story graph.</p>
          </section>
        ` : !nodes.length ? `
          <section class="v2-graph-empty" id="v2GraphEmptyState">
            <h2>${firstScene ? 'Prepared scene graphs ready' : 'No story graph nodes yet'}</h2>
            <p>
              ${firstScene ? `${prepared.fragments.length} source-linked scene graphs are available for this revision.`
                : 'Prepare the saved text in Compose to build scene graphs, or add a story node here.'}
            </p>
            <div class="v2-graph-empty-actions">
              <button type="button" class="v2-tl-btn v2-tl-btn-primary" id="v2GraphEmptyAddBtn" ${state.busy ? 'disabled' : ''}>+ Add First Node</button>
              <button type="button" class="v2-tl-btn" id="v2GraphGoComposeBtn">Open in Compose</button>
              ${junctions.length ? `<button type="button" class="v2-tl-btn" data-graph-tab="forms">Browse Character Junctions (${junctions.length})</button>` : ''}
            </div>
          </section>
        ` : `
          <div class="v2-deep-mine-bar">
            <div class="v2-houdini-legend" aria-label="Houdini wire authority legend">
              <span class="v2-wire-tag is-law">🔴 World Law</span>
              <span class="v2-wire-tag is-media">🟡 Media / Gag Pin</span>
              <span class="v2-wire-tag is-mind">🔵 Character Mind</span>
              <span class="v2-wire-tag is-book">🟣 190-Book Craft</span>
            </div>
            <div class="v2-drop-zone" id="v2StoryDropZone" title="Drop .mp4 / .wav / .srt clip or click to cycle sample">
              📥 <span id="v2StoryDropLabel">${escapeHtml(state.stagedDeepMineClip || 'Drop clip or click to stage (Billy and Mandy Gag.mp4)')}</span>
            </div>
            <button type="button" class="v2-tl-btn v2-tl-btn-primary" id="v2DeepMineConnectBtn" ${state.busy ? 'disabled' : ''}>⛏ Connect Deep Mine</button>
          </div>
          <section class="v2-graph-canvas-wrap">
            <div id="v2GraphBreadcrumb" class="v2-graph-breadcrumb">
              <button type="button" class="v2-graph-crumb-btn" data-enter-subnet="">Episode Root</button>
            </div>
            <canvas id="v2HoudiniCanvas" class="v2-houdini-canvas" aria-label="Episode story node network"></canvas>
            <div class="v2-graph-hud" aria-label="Canvas camera controls">
              <span id="v2GraphHoverHint">Drag nodes · Space+Drag pan · Wheel zoom · F fit</span>
              <span class="v2-graph-zoom-pill" id="v2GraphZoomReadout">${savedStoryCamera.episodeId === ep.id && savedStoryCamera.camera ? `${Math.round(savedStoryCamera.camera.zoom * 100)}%` : '100%'}</span>
              ${nodes
                .filter((n) => ['scene', 'branch_junction', 'episode_source'].includes(n.type))
                .slice(0, 7)
                .map((n, idx) => `<button type="button" class="v2-graph-hud-btn" data-jump-graph-node="${escapeHtml(n.id)}" title="${escapeHtml(n.parms?.title || n.id)}">S${idx + 1}</button>`)
                .join('')}
              <button type="button" class="v2-graph-hud-btn" id="v2GraphHudFitBtn">Fit [F]</button>
              <button type="button" class="v2-graph-hud-btn" id="v2GraphHudFrameBtn">Frame [H]</button>
              <button type="button" class="v2-graph-hud-btn" id="v2GraphHudLayoutBtn">Auto-Layout</button>
              <button type="button" class="v2-graph-hud-btn" id="v2GraphSpineBtn" title="Snap backbone beats onto chronological spine and modifiers to parallel lane">Spine Layout</button>
            </div>
          </section>
        `
      ) : `
        <section class="v2-junction-toolbar">
          <input
            type="search"
            id="v2JunctionSearch"
            class="v2-junction-search"
            placeholder="Filter characters or forms…"
            value="${escapeHtml(state.graphFilter || '')}"
            aria-label="Filter character junctions"
          >
          <div class="v2-junction-add">
            <input
              type="text"
              id="v2AddCharLabelInput"
              class="v2-junction-search"
              placeholder="New character name…"
              aria-label="New character name"
            >
            <button type="button" class="v2-tl-btn v2-tl-btn-primary" id="v2AddCharBtn" ${state.busy || !ep ? 'disabled' : ''}>+ Add Character</button>
          </div>
          <span class="v2-muted" id="v2JunctionFilterCount" style="font-size:12px">Showing ${filteredJunctions.length} of ${junctions.length} character junctions</span>
        </section>

        ${!junctions.length ? `
          <section class="v2-graph-empty">
            <h2>No character junctions available</h2>
            <p>No character form adapter is active for this universe.</p>
          </section>
        ` : `
          ${activeJ ? `
            <section class="v2-char-graph-wrap" aria-label="Selected character graph">
              <div class="v2-char-graph-head">
                <div>
                  <strong id="v2CharGraphTitle">${escapeHtml(activeJ.label || activeJ.character_id)} — Character Graph</strong>
                  <span class="v2-muted" id="v2CharGraphSubtitle"> · ${(activeJ.forms || []).length} forms · ${activeBlocks.length} episode blocks · tap cluster to expand or block to jump</span>
                </div>
                <div class="v2-char-graph-actions">
                  <button type="button" class="v2-tl-btn" id="v2CharFitBtn">Fit</button>
                  <button type="button" class="v2-tl-btn" id="v2CharCollapseBtn">Reset Clusters</button>
                </div>
              </div>
              <div class="v2-char-graph-canvas-wrap">
                <div id="v2CharGraphCanvas" class="v2-char-graph-canvas"></div>
              </div>
            </section>
          ` : ''}

          <section class="v2-junction-grid" id="v2JunctionGridSlot">
            ${filteredJunctions.length
              ? renderJunctionCards(filteredJunctions, state, junctions)
              : `<section class="v2-graph-empty"><h2>No matching character junctions</h2><p>Try clearing the search filter.</p></section>`}
          </section>
        `}
      `}
    </div>
  `;
}

export function renderGraphInspector(state) {
  return renderScenePlan(state) + renderGraphDetails(state);
}

function renderGraphDetails(state) {
  const subtab = state.graphSubtab || 'switchyard';
  const ep = state.episodeState?.episode;

  if (subtab === 'forms') {
    const sel = state.selectedProfile;
    const data = sel?.data;
    const fields = data?.fields || {};
    const fieldKeys = Object.keys(fields);
    const junctions = state.formGraph?.junctions || [];
    const activeCharId = sel?.character || state.graphSelection?.characterId || null;
    const activeJunction = activeCharId ? junctions.find((j) => j.character_id === activeCharId) : null;
    const activeNodeKey = sel?.node || activeJunction?.junction_id || null;
    const activeForm = activeJunction?.forms.find((form) => form.id === sel?.form);
    const nodeDataMap = activeJunction?.node_data || {};
    const currentNodeData = activeNodeKey ? (nodeDataMap[activeNodeKey] ?? {}) : {};
    const canUndoNodeData = Boolean(activeNodeKey && activeJunction?.node_data_undo?.[activeNodeKey]);
    const canRedoNodeData = Boolean(activeNodeKey && activeJunction?.node_data_redo?.[activeNodeKey]);
    const connectedBlocks = activeCharId ? blocksForCharacter(state, activeCharId, junctions) : [];
    const replayBeat = bridgeBeat(state);
    const mindQuery = new URLSearchParams({ episode: state.episodeId });
    if (replayBeat) mindQuery.set('turn', replayBeat.id);
    if (activeForm) {
      mindQuery.set('character', activeCharId);
      mindQuery.set('form', activeForm.id);
    }

    return `
      <div class="v2-inspector-card">
        <h2>Character Form Profile</h2>
        ${replayBeat && !currentScenePlan(state) ? `<label>Replay beat <select data-bridge-beat>
            ${state.formGraph.beats.map(beat => `<option value="${escapeHtml(beat.id)}" ${beat.id === replayBeat.id ? 'selected' : ''}>${escapeHtml(beat.label)}</option>`).join('')}
          </select></label>
          ${Object.values(state.formGraph.bridge_cast.turns.find(turn => turn.beat === replayBeat.id).actors)
            .map(actor => `<p>${escapeHtml(actor.form)} · ${escapeHtml(actor.location)}${actor.mind ? ' · ' + escapeHtml(actor.mind) : ''}</p>`).join('')}` : ''}
        ${(replayBeat || activeForm) && ep?.head ? `<a class="v2-tl-btn" href="/mind-inspector?${escapeHtml(mindQuery.toString())}">Inspect Mind</a>` : ''}
        ${activeForm ? `<button type="button" id="v2OpenProfileBoard" class="v2-tl-btn v2-tl-btn-primary"
          data-character="${escapeHtml(activeCharId)}" data-port="${escapeHtml(activeForm.port_id)}">Open reference board</button>` : ''}
        ${!sel ? `
          <p class="v2-muted">Click <strong>Inspect</strong> on any character form card or tap a form node to edit its canon profile.</p>
        ` : sel.error ? `
          <div class="v2-notice" data-tone="err">${escapeHtml(sel.error)}</div>
        ` : `
          <div class="v2-tl-insp-grid">
            <div class="v2-graph-kv">
              <strong>${escapeHtml(sel.character)} · ${escapeHtml(sel.form)}</strong>
              <small>Revision ${data?.revision ?? 0}${data?.kind ? ` · ${escapeHtml(data.kind)}` : ''}</small>
            </div>
            ${fieldKeys.length ? fieldKeys.map((key) => `
              <label class="v2-tl-insp-field">
                ${escapeHtml(key)}
                <textarea rows="2" data-profile-field="${escapeHtml(key)}">${escapeHtml(String(fields[key] ?? ''))}</textarea>
              </label>
            `).join('') : `
              <p class="v2-muted">No editable profile fields returned for this form.</p>
            `}
            <div class="v2-tl-insp-row">
              <button type="button" class="v2-tl-btn v2-tl-btn-primary" id="v2SaveProfileBtn" ${state.busy || !fieldKeys.length ? 'disabled' : ''}>Save Profile</button>
              <button type="button" class="v2-tl-btn" id="v2UndoProfileBtn" ${state.busy || !data?.can_undo ? 'disabled' : ''}>Undo Profile</button>
            </div>
          </div>
        `}
      </div>

      ${activeJunction ? `
        <div class="v2-inspector-card">
          <h2>Graph Node Data (Influence Generation)</h2>
          <p class="v2-hint">Structured JSON or notes stored on <code>${escapeHtml(activeNodeKey || '')}</code> to influence story &amp; prose generation.</p>
          <div class="v2-tl-insp-grid">
            <label class="v2-tl-insp-field">
              Node payload (JSON object or notes)
              <textarea rows="4" id="v2NodeDataTextarea">${escapeHtml(JSON.stringify(currentNodeData, null, 2))}</textarea>
            </label>
            <div class="v2-tl-insp-row">
              <button type="button" class="v2-tl-btn v2-tl-btn-primary" id="v2SaveNodeDataBtn" ${state.busy ? 'disabled' : ''}>Save Node Data</button>
              <button type="button" class="v2-tl-btn" id="v2UndoNodeDataBtn" ${state.busy || !canUndoNodeData ? 'disabled' : ''}>Undo</button>
              <button type="button" class="v2-tl-btn" id="v2RedoNodeDataBtn" ${state.busy || !canRedoNodeData ? 'disabled' : ''}>Redo</button>
            </div>
          </div>
        </div>

        <div class="v2-inspector-card">
          <h2>Connected Script Blocks (${connectedBlocks.length})</h2>
          ${connectedBlocks.length ? `
            <div class="v2-connected-blocks">
              ${connectedBlocks.map(({ index, block }) => `
                <div class="v2-connected-block-row">
                  <span class="v2-connected-block-text">#${index + 1} · ${escapeHtml(String(block.text || '').trim().slice(0, 48))}</span>
                  <button type="button" class="v2-mini-btn" data-jump-compose-block="${escapeHtml(block.id)}">Jump ↗</button>
                </div>
              `).join('')}
            </div>
          ` : `<p class="v2-muted">No blocks in ${ep ? escapeHtml(ep.title) : 'this episode'} reference ${escapeHtml(activeJunction.label || activeCharId)} yet.</p>`}
        </div>
      ` : ''}
    `;
  }

  // Story DAG Inspector
  const snap = fromBackendGraph(getGraphData(state));
  const { nodes, edges } = snap;
  const selectedNode = nodes.find((n) => n.id === state.graphSelectedNodeId) || null;
  const selectedEdge = !selectedNode ? (edges.find((e) => e.id === state.graphSelectedEdgeId) || null) : null;
  const nodeTitleMap = new Map(nodes.map((n) => [n.id, n.title || n.id]));
  const imported = state.episodeState?.imported_source;
  const spec = selectedNode ? getOperatorSpec(selectedNode.legacyType || selectedNode.type) : null;
  const specParms = (spec?.parms || []).filter((p) => p.key !== 'title');

  const renderParmControl = (parm) => {
    const val = selectedNode?.parms?.[parm.key] ?? parm.default;
    if (parm.kind === 'slider') {
      const numVal = Number.isFinite(Number(val)) ? Number(val) : Number(parm.default ?? 0);
      return `
        <label class="v2-parm-row">
          <span>${escapeHtml(parm.label)}</span>
          <div class="v2-parm-slider-wrap">
            <input
              type="range"
              class="v2-parm-slider"
              data-node-parm="${escapeHtml(parm.key)}"
              data-parm-kind="slider"
              min="${parm.min ?? 0}"
              max="${parm.max ?? 1}"
              step="${parm.step ?? 0.05}"
              value="${numVal}"
            >
            <span class="v2-parm-val" data-parm-readout="${escapeHtml(parm.key)}">${numVal}</span>
          </div>
        </label>
      `;
    }
    if (parm.kind === 'toggle') {
      return `
        <label class="v2-parm-toggle-row">
          <span>${escapeHtml(parm.label)}</span>
          <input
            type="checkbox"
            data-node-parm="${escapeHtml(parm.key)}"
            data-parm-kind="toggle"
            ${val ? 'checked' : ''}
          >
        </label>
      `;
    }
    return `
      <label class="v2-parm-row">
        <span>${escapeHtml(parm.label)}</span>
        <input
          type="text"
          data-node-parm="${escapeHtml(parm.key)}"
          data-parm-kind="text"
          value="${escapeHtml(String(val ?? ''))}"
        >
      </label>
    `;
  };

  return `
    <div class="v2-inspector-card">
      <h2>${selectedNode ? 'Selected Node' : selectedEdge ? 'Wire Contract' : 'Story Graph Inspector'}</h2>
      ${selectedNode ? `
        <div class="v2-tl-insp-grid">
          <div class="v2-graph-kv">
            <strong>${escapeHtml(selectedNode.title || selectedNode.id)}</strong>
            <small>ID: ${escapeHtml(selectedNode.id)} · Op: ${escapeHtml(spec?.label || selectedNode.type)} · (${Math.round(selectedNode.x)}, ${Math.round(selectedNode.y)})</small>
          </div>
          <div class="v2-flag-row" role="group" aria-label="Node flags">
            <button type="button" class="v2-flag-pill" data-toggle-flag="bypass" data-node-id="${escapeHtml(selectedNode.id)}" data-active="${selectedNode.flags?.bypass ? 'true' : 'false'}" title="Bypass operator evaluation">B · Bypass</button>
            <button type="button" class="v2-flag-pill" data-toggle-flag="display" data-node-id="${escapeHtml(selectedNode.id)}" data-active="${selectedNode.flags?.display ? 'true' : 'false'}" title="Render / Display flag">R · Render</button>
            <button type="button" class="v2-flag-pill" data-toggle-flag="locked" data-node-id="${escapeHtml(selectedNode.id)}" data-active="${selectedNode.flags?.locked ? 'true' : 'false'}" title="Lock parameters and cache">L · Lock</button>
          </div>
          <label class="v2-tl-insp-field">
            Title
            <input id="v2NodeTitleInput" value="${escapeHtml(selectedNode.title || '')}">
          </label>
          <label class="v2-tl-insp-field">
            Operator Type
            <select id="v2NodeTypeSelect">
              ${Object.values(OPERATOR_SPECS).map((op) =>
                `<option value="${escapeHtml(op.type)}" ${selectedNode.type === op.type ? 'selected' : ''}>${escapeHtml(op.label)} (${escapeHtml(op.category)})</option>`
              ).join('')}
            </select>
          </label>
          ${specParms.length ? `
            <div class="v2-parm-list">
              ${specParms.map(renderParmControl).join('')}
            </div>
          ` : ''}
          <div class="v2-tl-insp-row">
            <button type="button" class="v2-tl-btn v2-tl-btn-primary" id="v2ApplyNodeEditBtn">Apply</button>
            <button type="button" class="v2-tl-btn v2-tl-btn-danger" id="v2RemoveNodeBtn">Remove Node</button>
          </div>
          <div class="v2-tl-insp-row">
            <button type="button" class="v2-tl-btn" id="v2GraphCookSelectedBtn" ${state.busy ? 'disabled' : ''}>Cook Selected</button>
            <button type="button" class="v2-tl-btn" id="v2GraphCookDownstreamBtn" ${state.busy ? 'disabled' : ''}>Cook Downstream</button>
            ${(() => {
              const cid = selectedNode.parms?.character_id;
              const matchJ = cid ? (state.formGraph?.junctions || []).find((j) => j.character_id === cid) : null;
              const matchPort = matchJ?.forms?.[0]?.port_id || '';
              return matchJ && matchPort
                ? `<button type="button" class="v2-tl-btn v2-tl-btn-primary" data-open-form-board="${escapeHtml(matchPort)}" data-character="${escapeHtml(matchJ.character_id)}">Open Board (${matchJ.forms.length}F)</button>`
                : '';
            })()}
          </div>
          <details class="v2-dev-json">
            <summary>Developer JSON</summary>
            <pre>${escapeHtml(JSON.stringify({ id: selectedNode.id, type: selectedNode.type, parms: selectedNode.parms, flags: selectedNode.flags, eval: selectedNode.eval }, null, 2))}</pre>
          </details>
          <label class="v2-tl-insp-field">
            Connect output to node
            <select id="v2ConnectTargetSelect">
              ${nodes.filter((n) => n.id !== selectedNode.id).map((n) =>
                `<option value="${escapeHtml(n.id)}">${escapeHtml(n.title || n.id)} [${escapeHtml(n.type)}]</option>`
              ).join('')}
            </select>
          </label>
          <button type="button" class="v2-tl-btn" id="v2AddEdgeBtn" ${nodes.length < 2 ? 'disabled' : ''}>+ Connect Edge</button>
        </div>
      ` : selectedEdge ? `
        <div class="v2-wire-card">
          <div class="v2-graph-kv">
            <strong>${escapeHtml(nodeTitleMap.get(selectedEdge.fromNode) || selectedEdge.fromNode)}.${escapeHtml(selectedEdge.fromPort)} → ${escapeHtml(nodeTitleMap.get(selectedEdge.toNode) || selectedEdge.toNode)}.${escapeHtml(selectedEdge.toPort)}</strong>
            <small>Wire ID: ${escapeHtml(selectedEdge.id)} · Type: <span class="v2-wire-badge">${escapeHtml(selectedEdge.dataType || 'ANY')}</span></small>
          </div>
          <button type="button" class="v2-tl-btn v2-tl-btn-danger" id="v2DisconnectWireBtn" data-edge-id="${escapeHtml(selectedEdge.id)}">Disconnect Wire</button>
        </div>
      ` : `
        <p class="v2-muted">
          ${nodes.length
            ? 'Click any node or wire in the network canvas to inspect ports, flags, or typed parameters.'
            : (ep ? `${escapeHtml(ep.title)} has no story graph nodes yet.` : 'Select an episode first.')}
        </p>
      `}
    </div>

    <div class="v2-inspector-card">
      <h2>Edges (${edges.length})</h2>
      ${edges.length ? `
        <div class="v2-tl-list">
          ${edges.map((edge, idx) => `
            <div class="v2-tl-item v2-graph-edge-item ${edge.id === state.graphSelectedEdgeId ? 'is-selected' : ''}" data-select-edge="${escapeHtml(edge.id)}">
              <span class="v2-graph-edge-label">${escapeHtml(edge.fromNode)}.${escapeHtml(edge.fromPort)} → ${escapeHtml(edge.toNode)}.${escapeHtml(edge.toPort)} <span class="v2-wire-badge">${escapeHtml(edge.dataType || 'ANY')}</span></span>
              <button type="button" class="v2-tl-btn" data-remove-edge="${idx}" data-edge-id="${escapeHtml(edge.id)}">Remove edge</button>
            </div>
          `).join('')}
        </div>
      ` : `<p class="v2-muted">No edges in this graph.</p>`}
    </div>

    ${imported ? `
      <div class="v2-inspector-card">
        <h2>Historical Source</h2>
        <div class="v2-graph-kv">
          <span>Edition: ${escapeHtml(imported.edition || 'source')} (line ${imported.source_line})</span>
          <small>${escapeHtml(imported.status || '')}</small>
          <small>Characters: ${Object.keys(imported.characters || {}).length} · Unresolved cues: ${imported.unresolved_cues ?? 0}</small>
        </div>
      </div>
    ` : ''}
  `;
}

function notifyQuiet(ctx, text, tone = 'ok') {
  const notice = { text, tone };
  if (typeof ctx.onNotice === 'function') {
    ctx.onNotice(notice);
    return;
  }
  ctx.store.setQuiet({ notice });
  const el = document.querySelector('.v2-rail-right .v2-notice[role="status"]');
  if (el) {
    el.dataset.tone = tone;
    el.textContent = text;
  }
}

function syncBreadcrumbBar(snap) {
  const bar = document.getElementById('v2GraphBreadcrumb');
  if (!bar) return;
  const trail = [];
  let cur = snap?.subnetId || null;
  const byId = new Map((snap?.nodes || []).map((n) => [n.id, n]));
  while (cur && byId.has(cur)) {
    const n = byId.get(cur);
    trail.unshift(n);
    cur = n.parentSubnetId ?? null;
  }
  bar.innerHTML = [
    `<button type="button" class="v2-graph-crumb-btn" data-enter-subnet="">Episode Root</button>`,
    ...trail.map((n) => `<span>›</span><button type="button" class="v2-graph-crumb-btn" data-enter-subnet="${escapeHtml(n.id)}">${escapeHtml(n.title || n.id)}</button>`),
  ].join('');
  bar.querySelectorAll('[data-enter-subnet]').forEach((btn) => {
    btn.addEventListener('click', () => {
      if (!storyController) return;
      storyController.dispatch({ type: 'ENTER_SUBNET', subnetId: btn.dataset.enterSubnet || null }, { refreshInspector: true });
      syncBreadcrumbBar(storyController.getSnapshot());
    });
  });
}

function syncStoryToolbarStatus(state) {
  const ep = state.episodeState?.episode;
  const vm = storyController ? storyController.getViewModel() : null;
  const nodes = vm ? vm.snapshot.nodes : fromBackendGraph(getGraphData(state)).nodes;
  const edges = vm ? vm.snapshot.edges : fromBackendGraph(getGraphData(state)).edges;
  const isDirty = vm ? vm.dirty : Boolean(state.graphDraft);
  const canUndo = vm ? vm.canUndo : false;
  const canRedo = vm ? vm.canRedo : false;

  const summary = document.getElementById('v2GraphMetaSummary');
  if (summary) {
    summary.textContent = `${ep ? ep.title : 'No episode'} · ${nodes.length} nodes · ${edges.length} edges`;
  }
  const dirtyPill = document.getElementById('v2GraphDirtyPill');
  if (dirtyPill) dirtyPill.hidden = !isDirty;

  const undoBtn = document.getElementById('v2GraphUndoBtn');
  if (undoBtn) undoBtn.disabled = Boolean(state.busy || !canUndo);

  const redoBtn = document.getElementById('v2GraphRedoBtn');
  if (redoBtn) redoBtn.disabled = Boolean(state.busy || !canRedo);

  const saveBtn = document.getElementById('v2GraphSaveBtn');
  if (saveBtn) saveBtn.disabled = Boolean(state.busy || !isDirty);

  const fitBtn = document.getElementById('v2GraphFitBtn');
  if (fitBtn) fitBtn.disabled = !nodes.length;

  const layoutBtn = document.getElementById('v2GraphLayoutBtn');
  if (layoutBtn) layoutBtn.disabled = nodes.length < 2;
}

function ensureStoryController(ctx) {
  latestCtx = ctx;
  if (!storyController) {
    storyController = createGraphController({
      store: ctx.store,
      api: ctx.api,
      onSelectEpisode: (...args) => latestCtx?.onSelectEpisode?.(...args),
      onNotify: (text, tone) => latestCtx && notifyQuiet(latestCtx, text, tone),
      onInspectorChange: () => {
        if (!latestCtx) return;
        syncStoryToolbarStatus(latestCtx.store.get());
        refreshInspectorOnly(latestCtx);
      },
    });
    storyController.subscribe((vm) => {
      const curCanvas = document.getElementById('v2HoudiniCanvas');
      if (storyCanvasView && curCanvas && storyCanvasEl === curCanvas) {
        storyCanvasView.updateModel(vm);
      }
      if (latestCtx) {
        syncStoryToolbarStatus(latestCtx.store.get());
      }
    });
  }
  return storyController;
}

function mountHoudiniStoryCanvas(ctx) {
  const { store } = ctx;
  const ctrl = ensureStoryController(ctx);
  const state = store.get();
  const canvas = document.getElementById('v2HoudiniCanvas');
  if (!canvas) {
    if (storyCanvasView) {
      try {
        storyCanvasView.destroy();
      } catch (_) {}
      storyCanvasView = null;
      storyCanvasEl = null;
    }
    return;
  }

  const epId = state.episodeState?.episode?.id || '';
  const curTheme = document.body.dataset.theme || 'racing';
  const vm = ctrl.syncWithState(state);

  if (storyCanvasView && storyCanvasEl === canvas && mountedStoryEpisodeId === epId) {
    storyCanvasView.updateModel(vm);
    if (mountedStoryTheme !== curTheme) {
      mountedStoryTheme = curTheme;
      storyCanvasView.refreshTheme();
    }
    syncStoryToolbarStatus(store.get());
    return;
  }

  if (storyCanvasView) {
    try {
      storyCanvasView.destroy();
    } catch (_) {}
    storyCanvasView = null;
    storyCanvasEl = null;
  }

  const hasSavedCamera = Boolean(epId && savedStoryCamera.episodeId === epId && savedStoryCamera.camera);
  storyCanvasEl = canvas;
  mountedStoryEpisodeId = epId;
  mountedStoryTheme = curTheme;

  storyCanvasView = mountHoudiniCanvasView({
    canvas,
    initialModel: vm,
    savedCamera: hasSavedCamera ? savedStoryCamera.camera : null,
    onSelectNode: (nodeId) => ctrl.selectNode(nodeId),
    onSelectEdge: (edgeId) => ctrl.selectEdge(edgeId),
    onMoveNode: (nodeId, x, y) => {
      ctrl.dispatch(
        { type: 'MOVE_NODES', moves: [{ id: nodeId, x, y }] },
        { noticeText: `Positioned ${nodeId} (unsaved — click Save Graph to commit).`, noticeTone: 'warn', refreshInspector: true }
      );
    },
    onToggleFlag: (nodeId, flag) => {
      ctrl.dispatch(
        { type: 'TOGGLE_FLAG', nodeId, flag },
        { noticeText: `Toggled ${flag.toUpperCase()} on ${nodeId} (unsaved).`, noticeTone: 'warn', refreshInspector: true }
      );
    },
    onConnectPorts: (payload) => {
      ctrl.dispatch(
        { type: 'CONNECT_PORTS', ...payload },
        { noticeText: `Wired ${payload.fromNode}.${payload.fromPort} → ${payload.toNode}.${payload.toPort} (unsaved).`, noticeTone: 'warn', refreshInspector: true }
      );
    },
    onSpliceNodeOnEdge: (nodeId, edgeId) => {
      ctrl.dispatch(
        { type: 'SPLICE_NODE_ON_EDGE', nodeId, edgeId },
        { noticeText: `Spliced ${nodeId} onto wire ${edgeId} (unsaved).`, noticeTone: 'warn', refreshInspector: true }
      );
    },
    onCutEdges: (edgeIds) => {
      ctrl.dispatch(
        { type: 'DISCONNECT_EDGE', edgeIds },
        { noticeText: `Cut ${edgeIds.length} ${edgeIds.length === 1 ? 'wire' : 'wires'} (unsaved).`, noticeTone: 'warn', refreshInspector: true }
      );
    },
    onRequestTabMenu: (opts) => {
      openTabOperatorPalette(opts);
    },
    onDuplicateNode: (nodeId, x, y) => {
      const orig = ctrl.getSnapshot().nodes.find((n) => n.id === nodeId);
      if (!orig) return;
      ctrl.dispatch(
        { type: 'ADD_NODE', nodeType: orig.legacyType || orig.type, x, y, title: `${orig.title} Copy`, parms: { ...orig.parms } },
        { noticeText: `Duplicated ${orig.title} (unsaved).`, noticeTone: 'warn', refreshInspector: true }
      );
    },
    onEnterSubnet: (subnetId) => {
      ctrl.dispatch({ type: 'ENTER_SUBNET', subnetId }, { refreshInspector: true });
      syncBreadcrumbBar(ctrl.getSnapshot());
    },
    onCameraChange: (cam) => {
      if (mountedStoryEpisodeId) {
        savedStoryCamera = { episodeId: mountedStoryEpisodeId, camera: cam };
      }
      const readout = document.getElementById('v2GraphZoomReadout');
      if (readout && cam) readout.textContent = `${Math.round(cam.zoom * 100)}%`;
    },
    onHoverHint: (hint) => {
      const el = document.getElementById('v2GraphHoverHint');
      if (el) el.textContent = hint || 'Drag nodes · Space+Drag pan · Wheel zoom · F fit';
    },
  });

  if (!storyThemeObserver && typeof MutationObserver === 'function') {
    storyThemeObserver = new MutationObserver(() => {
      const nextTheme = document.body.dataset.theme || 'racing';
      if (nextTheme !== mountedStoryTheme) {
        mountedStoryTheme = nextTheme;
        storyCanvasView?.refreshTheme();
      }
    });
    storyThemeObserver.observe(document.body, { attributes: true, attributeFilter: ['data-theme'] });
  }

  syncStoryToolbarStatus(store.get());
}

function syncCharCytoscapeTopology(ctx, activeJ, junctions) {
  const s = ctx.store.get();
  const charBlocks = blocksForCharacter(s, activeJ.character_id, junctions);
  const { elements, visibleBlocks, clusterCount } = buildCharacterTopology(activeJ, charBlocks, {
    expandedClusters: expandedCharClusters,
  });

  const titleEl = document.getElementById('v2CharGraphTitle');
  if (titleEl) {
    titleEl.textContent = `${activeJ.label || activeJ.character_id} — Character Graph`;
  }
  const subEl = document.getElementById('v2CharGraphSubtitle');
  if (subEl) {
    subEl.textContent = ` · ${(activeJ.forms || []).length} forms · ${visibleBlocks}/${charBlocks.length} visible blocks${clusterCount ? ` · ${clusterCount} clusters (tap to expand)` : ''} · click block to jump`;
  }

  if (!charCyInstance) return;
  const epId = s.episodeState?.episode?.id || '';
  const nextCharKey = `${epId}:${activeJ.character_id}`;
  const isSameCharacter = mountedCharKey === nextCharKey;
  const desiredIds = new Set(elements.map((el) => el.data.id));

  charCyInstance.batch(() => {
    if (!isSameCharacter) {
      charCyInstance.elements().remove();
      charCyInstance.add(elements);
    } else {
      charCyInstance.elements().forEach((el) => {
        if (!desiredIds.has(el.id())) el.remove();
      });
      for (const el of elements) {
        const existing = charCyInstance.getElementById(el.data.id);
        if (existing && existing.length) {
          existing.data(el.data);
          if (el.position && existing.isNode()) {
            existing.position(el.position);
          }
        } else {
          charCyInstance.add(el);
        }
      }
    }

    charCyInstance.nodes().unselect();
    if (s.selectedProfile?.form) {
      charCyInstance.getElementById(`form:${s.selectedProfile.form}`).select();
    }
  });

  if (!isSameCharacter) {
    mountedCharKey = nextCharKey;
    charCyInstance.fit(undefined, 28);
    captureCharViewport(nextCharKey);
  }
}

function mountCharacterCytoscape(ctx) {
  const { store, api, onJumpToComposeBlock } = ctx;
  const state = store.get();
  const container = document.getElementById('v2CharGraphCanvas');
  if (!container || typeof window.cytoscape !== 'function') return;

  const fg = state.formGraph;
  const junctions = fg?.junctions || [];
  const filteredJunctions = filterJunctions(junctions, state.graphFilter);
  const activeJ = resolveActiveJunction(junctions, filteredJunctions, state.selectedProfile, state.graphSelection);
  if (!activeJ) return;

  const epId = state.episodeState?.episode?.id || '';
  const charKey = `${epId}:${activeJ.character_id}`;

  if (charCyInstance) {
    try {
      if (charCyInstance.container() === container) {
        syncCharCytoscapeTopology(ctx, activeJ, junctions);
        return;
      }
      charCyInstance.destroy();
    } catch (_) {}
    charCyInstance = null;
  }

  const charBlocks = blocksForCharacter(state, activeJ.character_id, junctions);
  const { elements, visibleBlocks, clusterCount } = buildCharacterTopology(activeJ, charBlocks, {
    expandedClusters: expandedCharClusters,
  });

  const subEl = document.getElementById('v2CharGraphSubtitle');
  if (subEl) {
    subEl.textContent = ` · ${(activeJ.forms || []).length} forms · ${visibleBlocks}/${charBlocks.length} visible blocks${clusterCount ? ` · ${clusterCount} clusters (tap to expand)` : ''} · click block to jump`;
  }

  const accentBg = cssVar('--accent-primary', '#d97706');
  const accentInk = cssVar('--ink-on-accent', '#1c1208');
  const paperBg = cssVar('--surface-paper', '#f6efe2');
  const paperInk = cssVar('--ink-on-paper', '#1c2430');
  const borderCol = cssVar('--accent-primary-strong', '#7f4419');
  const focusCol = cssVar('--focus-ring', '#10b981');
  const hasSavedView = Boolean(
    charKey && savedCharViewport.key === charKey && savedCharViewport.zoom !== null && savedCharViewport.pan
  );

  charCyInstance = window.cytoscape({
    container,
    elements,
    layout: { name: 'preset', fit: !hasSavedView, padding: 28 },
    style: [
      {
        selector: 'node[kind="junction"]',
        style: {
          'background-color': accentBg,
          color: accentInk,
          'border-color': borderCol,
          'border-width': 3,
          label: 'data(label)',
          'font-size': 12,
          'font-weight': 800,
          'text-valign': 'center',
          'text-halign': 'center',
          'text-wrap': 'wrap',
          'text-max-width': '160px',
          shape: 'round-rectangle',
          width: 174,
          height: 58,
        },
      },
      {
        selector: 'node[kind="form"]',
        style: {
          'background-color': paperBg,
          color: paperInk,
          'border-color': borderCol,
          'border-width': 2,
          label: 'data(label)',
          'font-size': 11,
          'font-weight': 700,
          'text-valign': 'center',
          'text-halign': 'center',
          'text-wrap': 'wrap',
          'text-max-width': '145px',
          shape: 'round-rectangle',
          width: 158,
          height: 48,
        },
      },
      {
        selector: 'node[kind="block"]',
        style: {
          'background-color': paperBg,
          color: paperInk,
          'border-color': focusCol,
          'border-width': 2,
          label: 'data(label)',
          'font-size': 10,
          'font-weight': 600,
          'text-valign': 'center',
          'text-halign': 'center',
          'text-wrap': 'wrap',
          'text-max-width': '155px',
          shape: 'round-rectangle',
          width: 168,
          height: 42,
        },
      },
      {
        selector: 'node[kind="block_cluster"]',
        style: {
          'background-color': paperBg,
          color: paperInk,
          'border-color': borderCol,
          'border-style': 'dashed',
          'border-width': 2,
          label: 'data(label)',
          'font-size': 10,
          'font-weight': 700,
          'text-valign': 'center',
          'text-halign': 'center',
          'text-wrap': 'wrap',
          'text-max-width': '165px',
          shape: 'round-rectangle',
          width: 178,
          height: 48,
        },
      },
      {
        selector: 'node:selected',
        style: {
          'border-color': focusCol,
          'border-width': 4,
        },
      },
      {
        selector: 'node[kind="mind_socket"]',
        style: {
          'background-color': paperBg,
          color: paperInk,
          'border-color': '#06b6d4',
          'border-style': 'dashed',
          'border-width': 2,
          label: 'data(label)',
          'font-size': 9.5,
          'text-valign': 'center',
          'text-halign': 'center',
          'text-wrap': 'wrap',
          'text-max-width': '150px',
          shape: 'round-rectangle',
          width: 162,
          height: 36,
        },
      },
      {
        selector: 'node[kind="law_socket"]',
        style: {
          'background-color': paperBg,
          color: paperInk,
          'border-color': '#ef4444',
          'border-width': 2,
          label: 'data(label)',
          'font-size': 9.5,
          'text-valign': 'center',
          'text-halign': 'center',
          'text-wrap': 'wrap',
          'text-max-width': '150px',
          shape: 'round-rectangle',
          width: 162,
          height: 36,
        },
      },
      {
        selector: 'node[kind="relationship"]',
        style: {
          'background-color': paperBg,
          color: paperInk,
          'border-color': '#06b6d4',
          'border-style': 'dashed',
          'border-width': 2,
          label: 'data(label)',
          'font-size': 9.5,
          'text-valign': 'center',
          'text-halign': 'center',
          shape: 'round-rectangle',
          width: 130,
          height: 34,
        },
      },
      {
        selector: 'edge[kind="relationship-edge"]',
        style: {
          width: 2,
          'line-color': '#06b6d4',
          'line-style': 'dashed',
          'target-arrow-color': '#06b6d4',
          'target-arrow-shape': 'triangle',
          'curve-style': 'bezier',
        },
      },
      {
        selector: 'edge',
        style: {
          width: 2,
          'line-color': borderCol,
          'target-arrow-color': borderCol,
          'target-arrow-shape': 'triangle',
          'curve-style': 'bezier',
        },
      },
    ],
  });

  if (hasSavedView) {
    charCyInstance.zoom(savedCharViewport.zoom);
    charCyInstance.pan(savedCharViewport.pan);
  } else {
    captureCharViewport(charKey);
  }
  mountedCharKey = charKey;

  if (state.selectedProfile?.form) {
    charCyInstance.getElementById(`form:${state.selectedProfile.form}`).select();
  }

  charCyInstance.on('viewport', () => {
    captureCharViewport(mountedCharKey);
  });

  charCyInstance.on('tap', 'node[kind="block"]', (evt) => {
    const blockId = evt.target.data('blockId');
    if (blockId) onJumpToComposeBlock?.(blockId);
  });

  charCyInstance.on('tap', 'node[kind="block_cluster"]', (evt) => {
    const clusterId = evt.target.data('clusterId');
    if (!clusterId) return;
    if (expandedCharClusters.has(clusterId)) {
      expandedCharClusters.delete(clusterId);
    } else {
      expandedCharClusters.add(clusterId);
    }
    const latest = store.get();
    const curJunctions = latest.formGraph?.junctions || [];
    const curActive = resolveActiveJunction(
      curJunctions,
      filterJunctions(curJunctions, latest.graphFilter),
      latest.selectedProfile,
      latest.graphSelection
    );
    if (curActive) syncCharCytoscapeTopology(ctx, curActive, curJunctions);
  });

  charCyInstance.on('tap', 'node[kind="form"]', async (evt) => {
    const form = evt.target.data('formId');
    const node = evt.target.data('nodeId');
    if (!form) return;
    const latest = store.get();
    const curJunctions = latest.formGraph?.junctions || [];
    const curActive = resolveActiveJunction(
      curJunctions,
      filterJunctions(curJunctions, latest.graphFilter),
      latest.selectedProfile,
      latest.graphSelection
    );
    const character = curActive?.character_id;
    if (!character) return;
    await loadCharacterProfileQuiet(ctx, { character, form, node });
  });
  charCyInstance.on('dbltap', 'node[kind="form"]', (evt) => {
    if (evt.target.data('nodeId')) openBoard(ctx, activeJ.character_id, evt.target.data('nodeId'));
  });
}

function openBoard(ctx, character, port) {
  openFormBoard(ctx, character, port, {
    onChange: () => {
      const graph = ctx.store.get().formGraph;
      for (const [id, can] of [['v2FgUndoBtn', graph?.can_undo_graph], ['v2FgRedoBtn', graph?.can_redo_graph]]) {
        const button = document.getElementById(id);
        if (button) button.disabled = !can;
      }
    },
    openMind: (form, node) => loadCharacterProfileQuiet(ctx, { character, form: form.id, node }),
  });
}

async function loadCharacterProfileQuiet(ctx, { character, form, node }) {
  const { store, api } = ctx;
  store.setQuiet({ busy: true });
  try {
    const data = await api.characterProfileAction({ action: 'open', character, form, node });
    store.setQuiet({
      busy: false,
      selectedProfile: { character, form, node, data },
      graphSelection: null,
    });
    const latest = store.get();
    const junctions = latest.formGraph?.junctions || [];
    const targetJ = junctions.find((j) => j.character_id === character);
    if (targetJ) {
      syncCharCytoscapeTopology(ctx, targetJ, junctions);
    }
    refreshJunctionCardsOnly(ctx);
    refreshInspectorOnly(ctx);
    notifyQuiet(ctx, `Loaded profile for ${character}:${form}.`, 'ok');
  } catch (err) {
    store.setQuiet({
      busy: false,
      selectedProfile: { character, form, node, error: err.message },
      graphSelection: null,
    });
    refreshInspectorOnly(ctx);
    notifyQuiet(ctx, err.message, 'err');
  }
}

function refreshJunctionCardsOnly(ctx) {
  const slot = document.getElementById('v2JunctionGridSlot');
  if (!slot) return;
  const s = ctx.store.get();
  const junctions = s.formGraph?.junctions || [];
  const filtered = filterJunctions(junctions, s.graphFilter);
  const countEl = document.getElementById('v2JunctionFilterCount');
  if (countEl) {
    countEl.textContent = `Showing ${filtered.length} of ${junctions.length} character junctions`;
  }
  slot.innerHTML = filtered.length
    ? renderJunctionCards(filtered, s, junctions)
    : `<section class="v2-graph-empty"><h2>No matching character junctions</h2><p>Try clearing the search filter.</p></section>`;
  bindJunctionCardEvents(ctx);
}

function bindJunctionCardEvents(ctx) {
  document.querySelectorAll('[data-open-form-board]').forEach((button) => {
    button.addEventListener('click', () => openBoard(ctx, button.dataset.character, button.dataset.openFormBoard));
  });
  document.querySelectorAll('[data-inspect-form]').forEach((btn) => {
    btn.addEventListener('click', async () => {
      await loadCharacterProfileQuiet(ctx, {
        character: btn.dataset.character,
        form: btn.dataset.inspectForm,
        node: btn.dataset.node,
      });
    });
  });
}

function refreshInspectorOnly(ctx) {
  const host = document.getElementById('v2ViewInspectorHost');
  if (!host) {
    ctx.store.set({});
    return;
  }
  host.innerHTML = renderGraphInspector(ctx.store.get());
  bindInspectorEvents(ctx);
}

function bindInspectorEvents(ctx) {
  const selector = document.querySelector('[data-bridge-beat]');
  if (selector) selector.onchange = () => ctx.store.set({ bridgeBeatId: selector.value });
  const { store, api, onJumpToComposeBlock } = ctx;
  const ctrl = ensureStoryController(ctx);
  document.getElementById('v2OpenProfileBoard')?.addEventListener('click', (event) => {
    const { character, port } = event.currentTarget.dataset;
    openBoard(ctx, character, port);
  });

  document.getElementById('v2ApplyNodeEditBtn')?.addEventListener('click', () => {
    const s = store.get();
    const targetId = s.graphSelectedNodeId;
    if (!targetId) return;
    const snap = ctrl.getSnapshot();
    const curNode = snap.nodes.find((n) => n.id === targetId);
    if (!curNode) return;
    const title = document.getElementById('v2NodeTitleInput')?.value.trim() || targetId;
    const nextType = document.getElementById('v2NodeTypeSelect')?.value || curNode.type;

    let changed = false;
    if (title !== curNode.title) {
      const r1 = ctrl.dispatch(
        { type: 'SET_PARAM', nodeId: targetId, key: 'title', value: title },
        { noticeText: `Updated ${targetId} (unsaved).`, noticeTone: 'warn', refreshInspector: nextType === curNode.type }
      );
      if (!r1.ok) return;
      changed = true;
    }
    if (nextType !== curNode.type) {
      const r2 = ctrl.dispatch(
        { type: 'SET_NODE_TYPE', nodeId: targetId, nodeType: nextType },
        { noticeText: `Updated ${targetId} (${nextType}) (unsaved).`, noticeTone: 'warn', refreshInspector: true }
      );
      if (!r2.ok) return;
      changed = true;
    }
    if (changed) {
      refreshInspectorOnly(ctx);
    }
  });

  document.getElementById('v2RemoveNodeBtn')?.addEventListener('click', () => {
    const target = store.get().graphSelectedNodeId;
    if (!target) return;
    ctrl.dispatch(
      { type: 'REMOVE_SELECTION', nodeIds: [target], edgeIds: [] },
      { noticeText: `Removed ${target} (unsaved).`, noticeTone: 'warn', refreshInspector: true }
    );
  });

  document.getElementById('v2GraphCookSelectedBtn')?.addEventListener('click', async () => {
    playCookStart();
    const res = await ctrl.cookScoped({ mode: 'selected', nodeId: store.get().graphSelectedNodeId });
    if (res.ok) playCookComplete();
  });

  document.getElementById('v2GraphCookDownstreamBtn')?.addEventListener('click', async () => {
    playCookStart();
    const res = await ctrl.cookScoped({ mode: 'downstream', nodeId: store.get().graphSelectedNodeId });
    if (res.ok) playCookComplete();
  });

  document.querySelectorAll('[data-toggle-flag]').forEach((btn) => {
    btn.addEventListener('click', () => {
      const nodeId = btn.dataset.nodeId;
      const flag = btn.dataset.toggleFlag;
      if (!nodeId || !flag) return;
      ctrl.dispatch(
        { type: 'TOGGLE_FLAG', nodeId, flag },
        { noticeText: `Toggled ${flag.toUpperCase()} on ${nodeId} (unsaved).`, noticeTone: 'warn', refreshInspector: true }
      );
    });
  });

  document.querySelectorAll('[data-node-parm]').forEach((el) => {
    const key = el.dataset.nodeParm;
    const kind = el.dataset.parmKind;
    if (!key) return;
    if (kind === 'slider') {
      el.addEventListener('input', () => {
        const readout = document.querySelector(`[data-parm-readout="${CSS.escape(key)}"]`);
        if (readout) readout.textContent = el.value;
      });
    }
    el.addEventListener('change', () => {
      const s = store.get();
      const nodeId = s.graphSelectedNodeId;
      if (!nodeId) return;
      const value =
        kind === 'toggle' ? Boolean(el.checked) : kind === 'slider' ? Number(el.value) : el.value;
      const res = ctrl.dispatch(
        { type: 'SET_PARAM', nodeId, key, value },
        { noticeText: `Updated ${key} on ${nodeId} (unsaved).`, noticeTone: 'warn', refreshInspector: true }
      );
      if (!res.ok) {
        refreshInspectorOnly(ctx);
      }
    });
  });

  document.getElementById('v2AddEdgeBtn')?.addEventListener('click', () => {
    const s = store.get();
    const fromNode = s.graphSelectedNodeId;
    const toNode = document.getElementById('v2ConnectTargetSelect')?.value || '';
    if (!fromNode || !toNode) return;
    const snap = ctrl.getSnapshot();
    const src = snap.nodes.find((n) => n.id === fromNode);
    const dst = snap.nodes.find((n) => n.id === toNode);
    let chosenFrom = src?.outputs?.[0]?.id;
    let chosenTo = dst?.inputs?.[0]?.id;
    let foundMatch = false;
    for (const outPin of src?.outputs || []) {
      for (const inPin of dst?.inputs || []) {
        const probe = ctrl.canConnectPorts({ fromNode, fromPort: outPin.id, toNode, toPort: inPin.id });
        if (probe.ok) {
          chosenFrom = outPin.id;
          chosenTo = inPin.id;
          foundMatch = true;
          break;
        }
      }
      if (foundMatch) break;
    }
    ctrl.dispatch(
      { type: 'CONNECT_PORTS', fromNode, fromPort: chosenFrom, toNode, toPort: chosenTo },
      { noticeText: `Connected ${fromNode} → ${toNode} (unsaved).`, noticeTone: 'warn', refreshInspector: true }
    );
  });

  document.getElementById('v2DisconnectWireBtn')?.addEventListener('click', (e) => {
    const edgeId = e.currentTarget.dataset.edgeId;
    if (!edgeId) return;
    ctrl.dispatch(
      { type: 'DISCONNECT_EDGE', edgeId },
      { noticeText: `Disconnected wire ${edgeId} (unsaved).`, noticeTone: 'warn', refreshInspector: true }
    );
  });

  document.querySelectorAll('[data-select-edge]').forEach((row) => {
    row.addEventListener('click', (e) => {
      if (e.target.closest('[data-remove-edge]')) return;
      const edgeId = row.dataset.selectEdge;
      if (edgeId) ctrl.selectEdge(edgeId);
    });
  });

  document.querySelectorAll('[data-remove-edge]').forEach((btn) => {
    btn.addEventListener('click', (e) => {
      e.stopPropagation();
      const edgeId = btn.dataset.edgeId;
      if (!edgeId) return;
      ctrl.dispatch(
        { type: 'DISCONNECT_EDGE', edgeId },
        { noticeText: 'Edge removed (unsaved).', noticeTone: 'warn', refreshInspector: true }
      );
    });
  });

  document.querySelectorAll('#v2ViewInspectorHost [data-open-form-board]').forEach((button) => {
    button.addEventListener('click', () => openBoard(ctx, button.dataset.character, button.dataset.openFormBoard));
  });

  const runProfileStep = async (action) => {
    const s = store.get();
    const sel = s.selectedProfile;
    if (!sel || !sel.data) return;
    const fields = {};
    document.querySelectorAll('[data-profile-field]').forEach((el) => {
      fields[el.dataset.profileField] = el.value;
    });
    store.setQuiet({ busy: true });
    try {
      const payload = {
        action,
        character: sel.character,
        form: sel.form,
        node: sel.node,
        kind: sel.data.kind || 'form',
        revision: sel.data.revision,
        ...(action === 'save' ? { fields } : {}),
      };
      const data = await api.characterProfileAction(payload);
      store.setQuiet({
        busy: false,
        selectedProfile: { ...sel, data },
      });
      refreshInspectorOnly(ctx);
      notifyQuiet(
        ctx,
        action === 'save' ? `Saved profile for ${sel.character}:${sel.form}.` : 'Undid profile change.',
        'ok'
      );
    } catch (err) {
      store.setQuiet({ busy: false });
      notifyQuiet(ctx, err.message, 'err');
    }
  };

  document.getElementById('v2SaveProfileBtn')?.addEventListener('click', () => runProfileStep('save'));
  document.getElementById('v2UndoProfileBtn')?.addEventListener('click', () => runProfileStep('undo'));

  const runNodeDataStep = async (action) => {
    const s = store.get();
    const fg = s.formGraph;
    const sel = s.selectedProfile;
    const activeCharId = sel?.character || s.graphSelection?.characterId;
    const activeJunction = (fg?.junctions || []).find((j) => j.character_id === activeCharId);
    const node = sel?.node || activeJunction?.junction_id;
    if (!fg || !s.episodeId || !activeCharId || !node) return;
    let content = {};
    if (action === 'save_node_data') {
      const raw = document.getElementById('v2NodeDataTextarea')?.value.trim() || '{}';
      try {
        const parsed = JSON.parse(raw);
        content = parsed && typeof parsed === 'object' && !Array.isArray(parsed) ? parsed : { value: parsed };
      } catch (_) {
        content = { notes: raw };
      }
    }
    store.setQuiet({ busy: true });
    try {
      const nextFg = await api.formGraphAction({
        action,
        episode: s.episodeId,
        revision: fg.revision,
        character: activeCharId,
        node,
        ...(action === 'save_node_data' ? { content } : {}),
      });
      store.setQuiet({
        busy: false,
        formGraph: nextFg,
      });
      refreshInspectorOnly(ctx);
      notifyQuiet(
        ctx,
        action === 'save_node_data' ? `Saved node data for ${activeCharId}.` : `${action.replace(/_/g, ' ')} completed.`,
        'ok'
      );
    } catch (err) {
      store.setQuiet({ busy: false });
      notifyQuiet(ctx, err.message, 'err');
    }
  };

  document.getElementById('v2SaveNodeDataBtn')?.addEventListener('click', () => runNodeDataStep('save_node_data'));
  document.getElementById('v2UndoNodeDataBtn')?.addEventListener('click', () => runNodeDataStep('undo_node_data'));
  document.getElementById('v2RedoNodeDataBtn')?.addEventListener('click', () => runNodeDataStep('redo_node_data'));

  document.querySelectorAll('[data-jump-compose-block]').forEach((btn) => {
    btn.addEventListener('click', () => {
      onJumpToComposeBlock?.(btn.dataset.jumpComposeBlock);
    });
  });
}

export function bindGraphEvents(ctx) {
  const { store } = ctx;
  const ctrl = ensureStoryController(ctx);
  const cur = store.get();

  if (cur.triSplit) {
    ctrl.syncWithState(cur);
    requestAnimationFrame(() => {
      mountHoudiniStoryCanvas(ctx);
      mountCharacterCytoscape(ctx);
    });
  } else if ((cur.graphSubtab || 'switchyard') === 'switchyard') {
    bindCharSwitchyard(cur, () => {}, ctx.onJumpToComposeBlock);
  } else if ((cur.graphSubtab || 'story') === 'story') {
    ctrl.syncWithState(cur);
    requestAnimationFrame(() => mountHoudiniStoryCanvas(ctx));
  } else {
    requestAnimationFrame(() => mountCharacterCytoscape(ctx));
  }

  if (
    (cur.triSplit || (cur.graphSubtab || 'story') !== 'story') &&
    cur.graphSelection?.type === 'character' &&
    cur.graphSelection.characterId &&
    !cur.busy &&
    cur.selectedProfile?.character !== cur.graphSelection.characterId
  ) {
    const j = (cur.formGraph?.junctions || []).find((item) => item.character_id === cur.graphSelection.characterId);
    const f = j?.forms?.find((item) => item.id === cur.graphSelection.formId) || j?.forms?.[0];
    if (j && f) {
      loadCharacterProfileQuiet(ctx, {
        character: j.character_id,
        form: f.id,
        node: f.port_id || j.junction_id,
      });
    }
  }

  document.querySelectorAll('[data-graph-tab]').forEach((btn) => {
    btn.addEventListener('click', () => {
      captureStoryViewport(mountedStoryEpisodeId);
      captureCharViewport(mountedCharKey);
      store.set({ graphSubtab: btn.dataset.graphTab });
    });
  });

  const fitStory = () => {
    storyCanvasView?.fitAll();
    captureStoryViewport(mountedStoryEpisodeId);
  };
  document.getElementById('v2GraphFitBtn')?.addEventListener('click', fitStory);
  document.getElementById('v2GraphHudFitBtn')?.addEventListener('click', fitStory);
  document.getElementById('v2GraphHudFrameBtn')?.addEventListener('click', () => {
    storyCanvasView?.frameSelected();
    captureStoryViewport(mountedStoryEpisodeId);
  });

  document.getElementById('v2GraphUndoBtn')?.addEventListener('click', () => {
    ctrl.dispatch({ type: 'UNDO' }, { noticeText: 'Undid graph change (unsaved).', noticeTone: 'warn', refreshInspector: true });
  });
  document.getElementById('v2GraphRedoBtn')?.addEventListener('click', () => {
    ctrl.dispatch({ type: 'REDO' }, { noticeText: 'Redid graph change (unsaved).', noticeTone: 'warn', refreshInspector: true });
  });

  const runStoryAutoLayout = () => {
    const res = ctrl.dispatch(
      { type: 'APPLY_DAG_LAYOUT' },
      { noticeText: 'Auto-layout applied (unsaved — click Save Graph to commit).', noticeTone: 'warn', refreshInspector: true }
    );
    if (res.ok) {
      storyCanvasView?.fitAll();
      captureStoryViewport(mountedStoryEpisodeId);
    }
  };
  document.getElementById('v2GraphLayoutBtn')?.addEventListener('click', runStoryAutoLayout);
  document.getElementById('v2GraphHudLayoutBtn')?.addEventListener('click', runStoryAutoLayout);

  document.getElementById('v2GraphGoComposeBtn')?.addEventListener('click', () => {
    const url = new URL(location.href);
    url.searchParams.set('view', 'compose');
    history.replaceState(null, '', url);
    store.set({ view: 'compose' });
  });

  const addNode = () => {
    const hasCanvas = Boolean(storyCanvasView && document.getElementById('v2HoudiniCanvas'));
    const center = hasCanvas ? storyCanvasView.getViewportCenterWorld() : { x: 160, y: 140 };
    ctrl.dispatch(
      { type: 'ADD_NODE', nodeType: 'scene', x: center.x, y: center.y },
      { noticeText: 'Added node (unsaved — click Save Graph to commit).', noticeTone: 'warn', refreshInspector: true }
    );
  };

  document.getElementById('v2GraphAddNodeBtn')?.addEventListener('click', addNode);
  document.getElementById('v2GraphEmptyAddBtn')?.addEventListener('click', addNode);

  const dropZone = document.getElementById('v2StoryDropZone');
  if (dropZone) {
    const stageName = (name) => {
      store.setQuiet({ stagedDeepMineClip: name });
      const lbl = document.getElementById('v2StoryDropLabel');
      if (lbl) lbl.textContent = `Staged: ${name}`;
    };
    dropZone.addEventListener('dragover', (e) => {
      e.preventDefault();
      dropZone.classList.add('is-dragover');
    });
    dropZone.addEventListener('dragleave', () => dropZone.classList.remove('is-dragover'));
    dropZone.addEventListener('drop', (e) => {
      e.preventDefault();
      dropZone.classList.remove('is-dragover');
      const file = e.dataTransfer?.files?.[0];
      stageName(file ? file.name : 'Billy and Mandy Gag.mp4');
    });
    dropZone.addEventListener('click', () => {
      const samples = ['Billy and Mandy Gag.mp4', 'Complete Cutaway.mp4', 'Pretty Girl Fart #14.mp4'];
      const cur = store.get().stagedDeepMineClip || samples[0];
      stageName(samples[(samples.indexOf(cur) + 1) % samples.length]);
    });
  }
  document.getElementById('v2DeepMineConnectBtn')?.addEventListener('click', () => {
    const clip = store.get().stagedDeepMineClip || 'Billy and Mandy Gag.mp4';
    const hasCanvas = Boolean(storyCanvasView && document.getElementById('v2HoudiniCanvas'));
    const center = hasCanvas ? storyCanvasView.getViewportCenterWorld() : { x: 180, y: 160 };
    ctrl.dispatch(
      { type: 'ADD_NODE', nodeType: 'deep_mine', x: center.x, y: center.y, parms: { title: clip } },
      { noticeText: `Added Deep Mining node for ${clip} (unsaved — click Save Graph to commit).`, noticeTone: 'warn', refreshInspector: true }
    );
  });

  document.querySelectorAll('[data-jump-graph-node]').forEach((btn) => {
    btn.addEventListener('click', () => {
      const nid = btn.dataset.jumpGraphNode;
      if (!nid) return;
      ctrl.dispatch({ type: 'SELECT_NODE', nodeId: nid }, { refreshInspector: true });
      storyCanvasView?.frameSelected?.();
    });
  });

  document.getElementById('v2GraphSpineBtn')?.addEventListener('click', () => {
    const snap = ctrl.getState()?.snapshot;
    if (!snap || !Array.isArray(snap.nodes)) return;
    const backboneTypes = new Set(['episode_source', 'scene', 'beat', 'branch_junction', 'compile_out']);
    let bx = 60;
    let mx = 60;
    for (const node of snap.nodes) {
      if (backboneTypes.has(node.type)) {
        ctrl.dispatch({ type: 'MOVE_NODE', nodeId: node.id, x: bx, y: 140 }, {});
        bx += 260;
      } else {
        ctrl.dispatch({ type: 'MOVE_NODE', nodeId: node.id, x: mx, y: -40 }, {});
        mx += 260;
      }
    }
    storyCanvasView?.fitView?.();
    store.setQuiet({ notice: { text: 'Snapped backbone to chronological spine (unsaved — click Save Graph to commit).', tone: 'warn' } });
  });

  document.getElementById('v2GraphSaveBtn')?.addEventListener('click', async () => {
    const ep = store.get()?.episodeState?.episode;
    if (!ep) return;
    window.NOIR_FX?.trigger('EXECUTE_CONFIRM', { el: document.getElementById('v2GraphSaveBtn'), badgeText: 'Graph Saved' });
    captureStoryViewport(ep.id);
    await ctrl.saveGraph();
  });

  document.getElementById('v2CharFitBtn')?.addEventListener('click', () => {
    charCyInstance?.fit(undefined, 28);
    captureCharViewport(mountedCharKey);
  });

  document.getElementById('v2CharCollapseBtn')?.addEventListener('click', () => {
    expandedCharClusters.clear();
    const s = store.get();
    const junctions = s.formGraph?.junctions || [];
    const activeJ = resolveActiveJunction(junctions, filterJunctions(junctions, s.graphFilter), s.selectedProfile, s.graphSelection);
    if (activeJ) {
      syncCharCytoscapeTopology(ctx, activeJ, junctions);
      charCyInstance?.fit(undefined, 28);
      captureCharViewport(mountedCharKey);
    }
  });

  document.getElementById('v2JunctionSearch')?.addEventListener('input', (e) => {
    store.setQuiet({ graphFilter: e.target.value });
    refreshJunctionCardsOnly(ctx);
  });

  const stepFormGraph = async (action) => {
    const s = store.get();
    const fg = s.formGraph;
    if (!fg || !s.episodeId) return;
    store.set({ busy: true });
    try {
      const nextFg = await api.formGraphAction({ action, episode: s.episodeId, revision: fg.revision });
      store.set({
        busy: false,
        formGraph: nextFg,
        notice: { text: action === 'undo_graph' ? 'Undid character graph change.' : 'Redid character graph change.', tone: 'ok' },
      });
    } catch (err) {
      store.set({ busy: false, notice: { text: err.message, tone: 'err' } });
    }
  };

  document.getElementById('v2FgUndoBtn')?.addEventListener('click', () => stepFormGraph('undo_graph'));
  document.getElementById('v2FgRedoBtn')?.addEventListener('click', () => stepFormGraph('redo_graph'));

  document.getElementById('v2AddCharBtn')?.addEventListener('click', async () => {
    const s = store.get();
    const fg = s.formGraph;
    const input = document.getElementById('v2AddCharLabelInput');
    const label = input?.value.trim() || '';
    if (!fg || !s.episodeId || !label) return;
    store.set({ busy: true });
    try {
      const nextFg = await api.formGraphAction({
        action: 'add_character',
        episode: s.episodeId,
        revision: fg.revision,
        label,
      });
      if (input) input.value = '';
      store.set({
        busy: false,
        formGraph: nextFg,
        notice: { text: `Added ${label} to shared character graph.`, tone: 'ok' },
      });
    } catch (err) {
      store.set({ busy: false, notice: { text: err.message, tone: 'err' } });
    }
  });

  bindJunctionCardEvents(ctx);
  bindInspectorEvents(ctx);
}

let tabPaletteEl = null;

function closeTabOperatorPalette() {
  if (tabPaletteEl) {
    tabPaletteEl.remove();
    tabPaletteEl = null;
  }
}

function openTabOperatorPalette({ screenX = 360, screenY = 260, worldX = 200, worldY = 200, pendingWire = null } = {}) {
  closeTabOperatorPalette();
  if (!storyController || !document.getElementById('v2HoudiniCanvas')) return;

  const allOps = Object.values(OPERATOR_SPECS);
  const eligibleOps = pendingWire
    ? allOps.filter((op) => {
        if (pendingWire.fromKind === 'port_out') {
          return (op.inputs || []).some((p) => isPortTypeCompatible(pendingWire.port.dataType, p.dataType));
        }
        return (op.outputs || []).some((p) => isPortTypeCompatible(p.dataType, pendingWire.port.dataType));
      })
    : allOps;

  const el = document.createElement('div');
  el.id = 'v2TabPalette';
  el.className = 'v2-tab-palette';
  const left = Math.min(Math.max(12, screenX), Math.max(12, window.innerWidth - 300));
  const top = Math.min(Math.max(12, screenY), Math.max(12, window.innerHeight - 380));
  el.style.left = `${left}px`;
  el.style.top = `${top}px`;

  el.innerHTML = `
    <div class="v2-tab-palette-head">
      <span>${pendingWire ? `Quick-Connect (${escapeHtml(pendingWire.port.dataType)})` : 'Add Operator [Tab]'}</span>
      <button type="button" class="v2-graph-hud-btn" id="v2TabPaletteClose">Esc</button>
    </div>
    <input type="search" id="v2TabPaletteSearch" class="v2-tab-palette-search" placeholder="Search operators…" aria-label="Search operators">
    <div class="v2-tab-palette-list" id="v2TabPaletteList"></div>
  `;
  document.body.appendChild(el);
  tabPaletteEl = el;

  const searchInput = el.querySelector('#v2TabPaletteSearch');
  const listEl = el.querySelector('#v2TabPaletteList');
  let activeIdx = 0;
  let filtered = eligibleOps;

  const commitOperator = (op) => {
    closeTabOperatorPalette();
    const res = storyController.dispatch(
      { type: 'ADD_NODE', nodeType: op.type, x: Math.round(worldX), y: Math.round(worldY) },
      { noticeText: `Added ${op.label} (unsaved).`, noticeTone: 'warn', refreshInspector: true }
    );
    if (res.ok && res.nodeId && pendingWire) {
      if (pendingWire.fromKind === 'port_out') {
        const targetPin = (op.inputs || []).find((p) => isPortTypeCompatible(pendingWire.port.dataType, p.dataType));
        if (targetPin) {
          storyController.dispatch(
            {
              type: 'CONNECT_PORTS',
              fromNode: pendingWire.nodeId,
              fromPort: pendingWire.port.id,
              toNode: res.nodeId,
              toPort: targetPin.id,
            },
            { noticeText: `Added & wired ${op.label} (unsaved).`, noticeTone: 'warn', refreshInspector: true }
          );
        }
      } else {
        const srcPin = (op.outputs || []).find((p) => isPortTypeCompatible(p.dataType, pendingWire.port.dataType));
        if (srcPin) {
          storyController.dispatch(
            {
              type: 'CONNECT_PORTS',
              fromNode: res.nodeId,
              fromPort: srcPin.id,
              toNode: pendingWire.nodeId,
              toPort: pendingWire.port.id,
            },
            { noticeText: `Added & wired ${op.label} (unsaved).`, noticeTone: 'warn', refreshInspector: true }
          );
        }
      }
    }
  };

  const renderList = () => {
    const q = (searchInput.value || '').trim().toLowerCase();
    filtered = eligibleOps.filter(
      (op) => op.label.toLowerCase().includes(q) || op.type.toLowerCase().includes(q) || op.category.toLowerCase().includes(q)
    );
    if (activeIdx >= filtered.length) activeIdx = Math.max(0, filtered.length - 1);
    listEl.innerHTML = filtered.length
      ? filtered
          .map(
            (op, idx) => `
          <button type="button" class="v2-tab-palette-item ${idx === activeIdx ? 'is-active' : ''}" data-op-type="${escapeHtml(op.type)}">
            <span>${escapeHtml(op.label)}</span>
            <span class="v2-tab-palette-cat">${escapeHtml(op.category)}</span>
          </button>`
          )
          .join('')
      : `<div class="v2-muted" style="font-size:11.5px;padding:6px">No matching operators</div>`;
    listEl.querySelectorAll('[data-op-type]').forEach((btn, idx) => {
      btn.addEventListener('click', () => commitOperator(filtered[idx]));
    });
  };

  el.querySelector('#v2TabPaletteClose')?.addEventListener('click', closeTabOperatorPalette);
  searchInput.addEventListener('input', () => {
    activeIdx = 0;
    renderList();
  });
  searchInput.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') {
      e.preventDefault();
      closeTabOperatorPalette();
    } else if (e.key === 'ArrowDown') {
      e.preventDefault();
      if (filtered.length) {
        activeIdx = (activeIdx + 1) % filtered.length;
        renderList();
      }
    } else if (e.key === 'ArrowUp') {
      e.preventDefault();
      if (filtered.length) {
        activeIdx = (activeIdx - 1 + filtered.length) % filtered.length;
        renderList();
      }
    } else if (e.key === 'Enter' && filtered[activeIdx]) {
      e.preventDefault();
      commitOperator(filtered[activeIdx]);
    }
  });

  renderList();
  requestAnimationFrame(() => searchInput.focus());
}

let graphKeyBound = false;
if (!graphKeyBound && typeof document !== 'undefined') {
  graphKeyBound = true;
  document.addEventListener('keydown', (e) => {
    const tag = document.activeElement?.tagName;
    if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT') return;
    if (!storyCanvasView || !document.getElementById('v2HoudiniCanvas')) return;

    if (e.key === 'Tab') {
      e.preventDefault();
      const center = storyCanvasView.getViewportCenterWorld();
      const rect = document.getElementById('v2HoudiniCanvas').getBoundingClientRect();
      openTabOperatorPalette({
        screenX: rect.left + rect.width / 2 - 140,
        screenY: rect.top + rect.height / 2 - 140,
        worldX: center.x,
        worldY: center.y,
      });
      return;
    }

    const key = e.key.toLowerCase();
    if ((e.ctrlKey || e.metaKey) && key === 'z' && storyController) {
      e.preventDefault();
      if (e.shiftKey) {
        storyController.dispatch({ type: 'REDO' }, { noticeText: 'Redid graph change (unsaved).', noticeTone: 'warn', refreshInspector: true });
      } else {
        storyController.dispatch({ type: 'UNDO' }, { noticeText: 'Undid graph change (unsaved).', noticeTone: 'warn', refreshInspector: true });
      }
      return;
    }
    if ((e.ctrlKey || e.metaKey) && key === 'y' && storyController) {
      e.preventDefault();
      storyController.dispatch({ type: 'REDO' }, { noticeText: 'Redid graph change (unsaved).', noticeTone: 'warn', refreshInspector: true });
      return;
    }
    if (e.shiftKey && key === 'l' && storyController) {
      e.preventDefault();
      const res = storyController.dispatch(
        { type: 'APPLY_DAG_LAYOUT' },
        { noticeText: 'Auto-layout applied (unsaved).', noticeTone: 'warn', refreshInspector: true }
      );
      if (res.ok) storyCanvasView.fitAll();
      return;
    }
    if (e.shiftKey && key === 'o' && storyController) {
      e.preventDefault();
      const ids = storyCanvasView.getSelectedNodeIds();
      if (ids.length) {
        storyController.dispatch(
          { type: 'GROUP_NETWORK_BOX', nodeIds: ids },
          { noticeText: `Grouped ${ids.length} node(s) into Network Box (unsaved).`, noticeTone: 'warn', refreshInspector: true }
        );
      }
      return;
    }
    if (e.shiftKey && key === 'c' && storyController) {
      e.preventDefault();
      const ids = storyCanvasView.getSelectedNodeIds();
      if (ids.length) {
        storyController.dispatch(
          { type: 'CREATE_SUBNET', nodeIds: ids },
          { noticeText: `Collapsed ${ids.length} node(s) into Subnet (unsaved).`, noticeTone: 'warn', refreshInspector: true }
        );
      }
      return;
    }
    if (e.ctrlKey || e.metaKey || e.altKey) return;

    if (key === 'f') {
      storyCanvasView.fitAll();
      captureStoryViewport(mountedStoryEpisodeId);
    } else if (key === 'h') {
      storyCanvasView.frameSelected();
      captureStoryViewport(mountedStoryEpisodeId);
    } else if ((key === 'b' || key === 'r' || key === 'l') && storyController && latestCtx) {
      const selId = latestCtx.store.get().graphSelectedNodeId;
      if (!selId) return;
      const flag = key === 'b' ? 'bypass' : key === 'r' ? 'display' : 'locked';
      storyController.dispatch(
        { type: 'TOGGLE_FLAG', nodeId: selId, flag },
        { noticeText: `Toggled ${flag.toUpperCase()} on ${selId} (unsaved).`, noticeTone: 'warn', refreshInspector: true }
      );
    } else if ((e.key === 'Delete' || e.key === 'Backspace') && storyController && latestCtx) {
      const s = latestCtx.store.get();
      if (s.graphSelectedNodeId) {
        storyController.dispatch(
          { type: 'REMOVE_SELECTION', nodeIds: [s.graphSelectedNodeId], edgeIds: [] },
          { noticeText: `Removed ${s.graphSelectedNodeId} (unsaved).`, noticeTone: 'warn', refreshInspector: true }
        );
      } else if (s.graphSelectedEdgeId) {
        storyController.dispatch(
          { type: 'DISCONNECT_EDGE', edgeId: s.graphSelectedEdgeId },
          { noticeText: 'Wire disconnected (unsaved).', noticeTone: 'warn', refreshInspector: true }
        );
      }
    }
  });
}
