/* Noir Fiction Studio — Milestone 7 + Houdini 3-Level Node Graph (L1 Story + Ports + Media -> L2 Scene Blocks -> L3 Engine Wiring) */

import { escapeHtml } from './compose.js';
import { playTick, playSelect } from './sound.js';
import { renderActStructure, bindActStructure } from './beat.js';
import { NoirApi } from './api.js';
import { deriveLiveStoryGraph, stripMarkdown } from './live_graph_bridge.js';
import { openMediaVault, uploadMediaFiles } from './media_vault.js';

const STORAGE_KEY = 'noir-sg-persisted-v1';

const STARTER_BEATS = [
  { id: 'B01', title: 'Scene 1 · Kitchen Briefing', summary: 'Francine demands departure at 07:31 AM; Rainee stalls upstairs.', branch: 'G0', blockId: '' },
  { id: 'B02', title: 'Scene 2 · Master Suite Prep', summary: 'Rainee checks form state & locks mirror continuity.', branch: 'G0', blockId: '' },
  { id: 'B03', title: 'Scene 3 · Double Confrontation', summary: 'Stella & Haley test household rules; tension spikes.', branch: 'G0', blockId: '' },
  { id: 'B04', title: 'Scene 4 · Rainee-Peter Shift', summary: 'Peter Variant triggers; Fart Media rhythm beat fires.', branch: 'G0', blockId: '' },
  { id: 'B05', title: 'Scene 5 · Nurse Franny Pivot', summary: 'What-If fork: Nurse Pamela Franny intervention.', branch: 'G1', forkFrom: 'B03', blockId: '' },
  { id: 'B06', title: 'Scene 6 · Departure Cutaway', summary: 'Alternate fast exit with cutaway gag pacing.', branch: 'G2', forkFrom: 'B04', blockId: '' },
];

function loadLocalStore() {
  try {
    return JSON.parse(localStorage.getItem(STORAGE_KEY) || '{}') || {};
  } catch (_) {
    return {};
  }
}

const persisted = loadLocalStore();

const sgState = {
  level: 1, // 1 = Story Graph & Media Ports | 2 = Scene Code/Text Blocks | 3 = Houdini Engine Wiring
  activeBranch: 'G0',
  selectedBeatId: 'B01',
  camera: { tx: 28, ty: 20, zoom: 1 },
  nodePos: {},
  customBeats: [],
  portals: persisted.portals || {},
  rhythmClips: persisted.rhythmClips || {
    B04: [{ name: 'fg_mexican.mp4', tag: 'STORY_RHYTHM_ONLY' }],
  },
  rhythmNotes: persisted.rhythmNotes || {},
  mediaHooks: persisted.mediaHooks || [
    {
      id: 'MH_DEFAULT_1',
      targetBeatId: 'B02',
      betweenFromId: 'B01',
      name: 'spring_break_reference.pdf',
      mediaType: 'pdf',
      sizeLabel: 'Ref PDF',
      role: 'Scene & Tone Reference',
    },
  ],
  pendingHookTarget: { targetBeatId: 'B02', betweenFromId: 'B01' },
  toast: null,
};

function saveLocalStore() {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify({
      portals: sgState.portals,
      rhythmClips: sgState.rhythmClips,
      rhythmNotes: sgState.rhythmNotes,
      mediaHooks: sgState.mediaHooks,
    }));
  } catch (_) {}
  syncStoryToStore();
}

function getSgSnap() {
  return {
    activeBranch: sgState.activeBranch,
    selectedBeatId: sgState.selectedBeatId,
    customBeats: sgState.customBeats,
    portals: sgState.portals,
    rhythmClips: sgState.rhythmClips,
    rhythmNotes: sgState.rhythmNotes,
    mediaHooks: sgState.mediaHooks,
  };
}

function applySgSnap(snap, rerenderFn) {
  if (!snap) return;
  sgState.activeBranch = snap.activeBranch;
  sgState.selectedBeatId = snap.selectedBeatId;
  sgState.customBeats = snap.customBeats || [];
  sgState.portals = snap.portals || {};
  sgState.rhythmClips = snap.rhythmClips || {};
  sgState.rhythmNotes = snap.rhythmNotes || {};
  sgState.mediaHooks = snap.mediaHooks || [];
  saveLocalStore();
  if (rerenderFn) rerenderFn();
}

function syncStoryToStore() {
  const st = typeof window !== 'undefined' ? window.__noirStore : null;
  if (!st) return;
  const payload = {
    activeBranch: sgState.activeBranch,
    selectedBeatId: sgState.selectedBeatId,
    mediaHooksCount: sgState.mediaHooks.length,
    customBeatsCount: sgState.customBeats.length,
  };
  st.setQuiet({ storySync: payload });
  st.emit?.('story:changed', payload);
}

function getPortal(beatId) {
  if (!sgState.portals[beatId]) sgState.portals[beatId] = { sight: true, audio: true };
  return sgState.portals[beatId];
}

function getLodLabel(zoom) {
  if (zoom >= 1.25) return 'Detail';
  if (zoom >= 0.65) return 'Switchyard';
  return 'Constellation';
}

function savedStoryMedia(state, nodes) {
  const story = state?.storyTimeline;
  const episode = state?.episodeState?.episode;
  const blocks = state?.episodeState?.notebook?.blocks || [];
  if (!story || story.scope.episode !== episode?.id || story.timeline_revision !== episode.head
      || state.dirty || blocks.map((block) => block.text).join('') !== state.episodeState.script_text) {
    return new Map();
  }
  let offset = 0;
  const ranges = new Map(blocks.map((block) => {
    const start = offset;
    offset += [...block.text].length;
    return [block.id, { start, end: offset }];
  }));
  const destinations = new Map();
  for (const node of nodes) {
    const spans = node.passage ? [node.passage] : (node.blockIds || [node.blockId]).map((id) => ranges.get(id)).filter(Boolean);
    const matches = story.scenes.flatMap((scene) => scene.beats.filter(({ passage }) =>
      spans.some(({ start, end }) => start < passage.end && passage.start < end)
    ).map((beat) => ({ scene, beat })));
    if (matches.length === 1) {
      const { beat } = matches[0];
      destinations.set(node.id, { target: { beat: beat.id }, links: beat.media || [] });
    } else if (matches.length && matches.every(({ scene }) => scene === matches[0].scene)) {
      const { scene } = matches[0];
      destinations.set(node.id, { target: { scene: scene.id }, links: scene.media || [] });
    }
  }
  return destinations;
}

function buildBeatsFromState(state) {
  const sampleChars = state?.sampleProjects?.[0]?.characters || [];
  const live = deriveLiveStoryGraph(state, sampleChars);
  const ep = state?.episodeState?.episode;
  const mapping = state?.beatMap;
  const saved = !state?.dirty && mapping && ep && mapping.episode === ep.id && mapping.revision === ep.head;
  let base = live.nodes;
  if (saved && mapping.beats.length) {
    let cursor = 0;
    const ranges = (state.episodeState.notebook?.blocks || []).map((block) => {
      const start = cursor;
      cursor += [...block.text].length;
      return { start, end: cursor, block };
    });
    base = mapping.beats.map((beat) => {
      const block = ranges.find((item) => item.start <= beat.start && item.end > beat.start)?.block;
      return { id: `B${String(beat.number).padStart(2, '0')}`, nodeType: 'BEAT', branch: 'G0',
        title: stripMarkdown(beat.text).slice(0, 56) || `Passage ${beat.number}`,
        summary: mapping.scenes.find((scene) => scene.id === beat.scene_id)?.title || '',
        blockId: block?.id || '', passage: { id: beat.id, start: beat.start, end: beat.end } };
    });
  }

  if (!base.length) {
    base = STARTER_BEATS.map((b) => ({ ...b }));
  } else {
    if (!base.some((b) => b.branch === 'G1')) {
      base.push({
        id: `B${String(base.length + 1).padStart(2, '0')}`,
        title: 'What-If Fork · Alternate Turn',
        summary: 'G1 branch diverging from earlier scene.',
        branch: 'G1',
        forkFrom: base[Math.min(1, base.length - 1)].id,
        blockId: '',
      });
    }
    if (!base.some((b) => b.branch === 'G2')) {
      base.push({
        id: `B${String(base.length + 1).padStart(2, '0')}`,
        title: 'G2 Cutaway Rhythm Branch',
        summary: 'Fast gag cutaway timing branch.',
        branch: 'G2',
        forkFrom: base[Math.min(2, base.length - 1)].id,
        blockId: '',
      });
    }
  }

  const all = [...base, ...sgState.customBeats];
  const visible = all.filter((b) => b.branch === 'G0' || b.branch === sgState.activeBranch || sgState.activeBranch === 'ALL');

  let g0Idx = 0;
  let g1Idx = 0;
  let g2Idx = 0;
  let maxY = 560;
  const nodes = visible.map((b) => {
    let defX = 48;
    let defY = 28;
    if (b.branch === 'G1') {
      defX = 460;
      defY = 174 + g1Idx * 156;
      g1Idx += 1;
    } else if (b.branch === 'G2') {
      defX = 760;
      defY = 320 + g2Idx * 156;
      g2Idx += 1;
    } else {
      defX = 48;
      defY = 28 + g0Idx * 156;
      g0Idx += 1;
    }
    if (defY > maxY) maxY = defY;

    if (!sgState.nodePos[b.id]) sgState.nodePos[b.id] = { x: defX, y: defY };
    const pos = sgState.nodePos[b.id];
    return { ...b, x: pos.x, y: pos.y, w: 236, h: 112 };
  });

  const wires = [];
  const betweenSlots = [];
  const g0Nodes = nodes.filter((n) => n.branch === 'G0');
  for (let i = 1; i < g0Nodes.length; i += 1) {
    const a = g0Nodes[i - 1];
    const b = g0Nodes[i];
    wires.push({ from: a, to: b, branch: false });
    betweenSlots.push({
      fromId: a.id,
      toId: b.id,
      x: Math.round((a.x + b.x) / 2 + a.w / 2),
      y: Math.round((a.y + a.h + b.y) / 2),
    });
  }
  for (const n of nodes.filter((x) => x.branch !== 'G0')) {
    const parent = nodes.find((x) => x.id === n.forkFrom) || g0Nodes[g0Nodes.length - 1];
    if (parent) wires.push({ from: parent, to: n, branch: true });
  }

  return { nodes, wires, betweenSlots, stageHeight: Math.max(760, maxY + 180) };
}

function wirePath(a, b) {
  const x1 = a.x + Math.round(a.w / 2);
  const y1 = a.y + a.h;
  const x2 = b.x + Math.round(b.w / 2);
  const y2 = b.y;
  const dy = Math.max(34, Math.abs(y2 - y1) * 0.45);
  return `M ${x1} ${y1} C ${x1} ${y1 + dy}, ${x2} ${y2 - dy}, ${x2} ${y2}`;
}

function mediaWirePath(mNode, targetNode) {
  const x1 = mNode.x;
  const y1 = mNode.y + 32;
  const x2 = targetNode.x;
  const y2 = targetNode.y + Math.round(targetNode.h / 2);
  const dx = Math.max(40, Math.abs(x1 - x2) * 0.45);
  return `M ${x1} ${y1} C ${x1 - dx} ${y1}, ${x2 - dx} ${y2}, ${x2} ${y2}`;
}

function resolveSceneBlocks(state, selectedBeat) {
  const allBlocks = state?.draftBlocks || state?.episodeState?.notebook?.blocks || state?.episodeState?.blocks || [];
  if (!allBlocks.length) return [];
  if (!selectedBeat?.blockId) return allBlocks.slice(0, 10);
  const startIdx = allBlocks.findIndex((b) => b.id === selectedBeat.blockId);
  if (startIdx < 0) return allBlocks.slice(0, 10);
  const out = [allBlocks[startIdx]];
  for (let i = startIdx + 1; i < allBlocks.length && out.length < 18; i += 1) {
    if (allBlocks[i].kind === 'scene-heading' && i > startIdx + 1) break;
    out.push(allBlocks[i]);
  }
  return out;
}

function renderLevel2SceneBlocks(state, selected) {
  const sceneBlocks = resolveSceneBlocks(state, selected);
  const nb = state?.episodeState?.notebook;
  const defProt = nb?.default_protection ?? 100;
  return `
    <div class="sg-l2-wrap">
      <div class="sg-l2-head">
        <div>
          <span class="sg-l2-eyebrow">LEVEL 2 · SCENE CODE &amp; TEXT BLOCKS (LIVE COMPOSER SYNC)</span>
          <strong>${escapeHtml(selected?.id || 'B01')} · ${escapeHtml(selected?.title || 'Scene')}</strong>
        </div>
        <div class="sg-l2-actions">
          <button type="button" class="v2-mini-btn" data-sg-level="1">↑ L1 Story Graph</button>
          <button type="button" class="v2-mini-btn v2-btn-accent" data-sg-level="3">↓ L3 Engine Wiring</button>
        </div>
      </div>
      <div class="sg-l2-list">
        ${sceneBlocks.length ? sceneBlocks.map((b, idx) => `
          <article class="sg-l2-card" data-kind="${escapeHtml(b.kind || 'narrator')}">
            <div class="sg-l2-card-head">
              <span class="sw-badge is-mint">#${idx + 1} · ${escapeHtml((b.kind || 'narrator').toUpperCase())}</span>
              <code>${escapeHtml(b.id)}</code>
              <span class="sg-rhythm-pill">${defProt}% Prot</span>
            </div>
            <textarea class="sg-l2-textarea" data-sg-l2-block="${escapeHtml(b.id)}" rows="4" aria-label="Edit block ${escapeHtml(b.id)}">${escapeHtml(b.text || '')}</textarea>
          </article>
        `).join('') : '<div class="sg-l2-empty">Select or open an episode in Compose to inspect &amp; edit its live code blocks here.</div>'}
      </div>
    </div>
  `;
}

function renderLevel3EngineWiring(state, selected) {
  const sceneBlocks = resolveSceneBlocks(state, selected);
  const hooks = sgState.mediaHooks.filter((h) => !selected || h.targetBeatId === selected.id);
  const wordCount = sceneBlocks.map((b) => (b.text || '').trim().split(/\s+/).filter(Boolean).length).reduce((a, b) => a + b, 0);
  const rhythmText = (selected && sgState.rhythmNotes[selected.id]) || 'Default scene pacing';
  const speakers = [...new Set(sceneBlocks.map((b) => b.speaker).filter(Boolean))];
  const lawCount = (state?.worldLaws?.rules || state?.worldLaws?.laws || []).length;
  const prot = state?.episodeState?.notebook?.default_protection ?? 100;

  // Houdini 3-Column Node Network
  const mediaNodes = hooks.length ? hooks : [{
    id: 'MH_EMPTY',
    name: 'No Media Hooked at L1',
    mediaType: 'stub',
    role: 'Click + Hook Media to wire a PDF, Movie, or Text Ref',
  }];

  const l3Nodes = [
    ...mediaNodes.map((m, i) => ({
      id: `L3_MEDIA_${i}`,
      col: 1,
      y: 26 + i * 112,
      title: m.name,
      badge: m.mediaType === 'stub' ? 'MEDIA SLOT' : `MEDIA · ${m.mediaType.toUpperCase()}`,
      tone: 'is-media',
      detail: m.role || 'Reference Ingest',
      inPort: null,
      outPort: 'EXTRACT OUT',
    })),
    {
      id: 'L3_SCENE_TEXT',
      col: 1,
      y: 26 + mediaNodes.length * 112,
      title: `Scene Text · ${selected?.id || 'B01'}`,
      badge: 'L2 BLOCKS',
      tone: 'is-canon',
      detail: `${sceneBlocks.length} blocks · ${wordCount} words · "${rhythmText.slice(0, 32)}"`,
      inPort: null,
      outPort: 'TEXT + RHYTHM',
    },
    {
      id: 'L3_CHAR_MINDS',
      col: 1,
      y: 26 + (mediaNodes.length + 1) * 112,
      title: 'Character Minds & Forms',
      badge: 'SWITCHYARD',
      tone: 'is-mint',
      detail: speakers.length ? `Active: ${speakers.join(', ')}` : 'All household minds standing by',
      inPort: null,
      outPort: 'INTENT + STANCE',
    },
    {
      id: 'L3_WORLD_LAWS',
      col: 1,
      y: 26 + (mediaNodes.length + 2) * 112,
      title: 'World Laws & Protections',
      badge: 'CONSTITUTION',
      tone: 'is-law',
      detail: `${lawCount} laws · ${prot}% Document Lock`,
      inPort: null,
      outPort: 'HARD GUARDS',
    },
    {
      id: 'L3_STAGE1_SIM',
      col: 2,
      y: 120,
      title: 'Stage 1 · Mind Sim & Blackboard',
      badge: 'SIMULATE',
      tone: 'is-stage',
      detail: 'Arbitrates agent intents, epistemic snapshots & media triggers',
      inPort: 'UPSTREAM PORTS',
      outPort: 'DISCOURSE PLAN',
    },
    {
      id: 'L3_STAGE2_PROSE',
      col: 3,
      y: 120,
      title: 'Stage 2 · PDG Prose Render',
      badge: 'OUTPUT',
      tone: 'is-mint',
      detail: 'Surgical uplift slots + Anti-RLHF + Frozen Lock Preservation',
      inPort: 'PLAN IN',
      outPort: 'MANUSCRIPT',
    },
  ];

  const colX = { 1: 28, 2: 350, 3: 670 };
  const l3H = Math.max(480, (mediaNodes.length + 3) * 116 + 40);
  const stage1 = l3Nodes.find((n) => n.id === 'L3_STAGE1_SIM');
  const stage2 = l3Nodes.find((n) => n.id === 'L3_STAGE2_PROSE');
  const col1Nodes = l3Nodes.filter((n) => n.col === 1);

  const l3Wires = [
    ...col1Nodes.map((n) => {
      const x1 = colX[1] + 244;
      const y1 = n.y + 44;
      const x2 = colX[2];
      const y2 = stage1.y + 44;
      const dx = 95;
      return { d: `M ${x1} ${y1} C ${x1 + dx} ${y1}, ${x2 - dx} ${y2}, ${x2} ${y2}`, cls: n.tone === 'is-media' ? 'is-media' : '' };
    }),
    {
      d: `M ${colX[2] + 244} ${stage1.y + 44} C ${colX[2] + 300} ${stage1.y + 44}, ${colX[3] - 56} ${stage2.y + 44}, ${colX[3]} ${stage2.y + 44}`,
      cls: 'is-branch',
    },
  ];

  return `
    <div class="sg-l3-wrap">
      <div class="sg-l2-head">
        <div>
          <span class="sg-l2-eyebrow">LEVEL 3 · HOUDINI ENGINE WIRING (${escapeHtml(selected?.id || 'B01')})</span>
          <strong>Upstream Media + L2 Text + Character Minds + Laws → Stage 1 Sim → Stage 2 Render</strong>
        </div>
        <div class="sg-l2-actions">
          <button type="button" class="v2-mini-btn" data-sg-level="2">↑ L2 Scene Blocks</button>
          <button type="button" class="v2-mini-btn" data-sg-level="1">↑↑ L1 Story Graph</button>
        </div>
      </div>
      <div class="sg-l3-viewport">
        <div class="sg-l3-stage" style="height:${l3H}px;">
          <svg class="sg-wires" viewBox="0 0 1000 ${l3H}" style="width:1000px;height:${l3H}px;">
            ${l3Wires.map((w) => `<path class="sg-wire ${w.cls}" d="${w.d}"></path>`).join('')}
          </svg>
          ${l3Nodes.map((n) => `
            <article class="sg-l3-node ${n.tone}" style="left:${colX[n.col]}px; top:${n.y}px;">
              ${n.inPort ? `<span class="sg-l3-port is-left" title="${escapeHtml(n.inPort)}"></span>` : ''}
              ${n.outPort ? `<span class="sg-l3-port is-right" title="${escapeHtml(n.outPort)}"></span>` : ''}
              <div class="sg-node-head">
                <span>${escapeHtml(n.badge)}</span>
                ${n.id === 'L3_SCENE_TEXT' ? '<button type="button" class="v2-mini-btn" data-sg-level="2">Edit L2</button>' : ''}
              </div>
              <div class="sg-node-body">
                <strong>${escapeHtml(n.title)}</strong>
                <small>${escapeHtml(n.detail)}</small>
              </div>
            </article>
          `).join('')}
        </div>
      </div>
    </div>
  `;
}

export function renderStoryGraphCanvas(state, opts = {}) {
  const compact = Boolean(opts.compact);
  const { nodes, wires, betweenSlots, stageHeight } = buildBeatsFromState(state);
  syncStoryToStore();
  const selected = nodes.find((n) => n.id === sgState.selectedBeatId) || nodes[0] || null;
  if (selected) sgState.selectedBeatId = selected.id;
  const zoomPct = Math.round(sgState.camera.zoom * 100);
  const lod = getLodLabel(sgState.camera.zoom).toLowerCase();
  const selRhythm = selected ? (sgState.rhythmClips[selected.id] || []) : [];
  const destinations = savedStoryMedia(state, nodes);
  const persisted = [...destinations].flatMap(([targetBeatId, { links }]) => links.map(({ pin, asset }) => ({
    id: pin, targetBeatId, name: asset.name, mediaType: asset.kind, assetId: asset.id,
  })));
  const hooks = [...sgState.mediaHooks, ...persisted];
  const selMedia = selected ? hooks.filter((hook) => hook.targetBeatId === selected.id) : [];

  // Build media nodes positioned to the right of their target scene node
  const nodeMap = new Map(nodes.map((n) => [n.id, n]));
  const structure = state.storyStructure;
  const savedStructure = structure && !state.dirty && structure.episode === state.episodeId
    && structure.timeline_revision === state.episodeState?.episode?.head;
  const points = savedStructure ? structure.points : [];
  const timingByPassage = new Map(points.map((point) => [point.id, point]));
  const timingFor = (node) => timingByPassage.get(node?.passage?.id
    || nodeMap.get(node?.forkFrom)?.passage?.id);
  const selectedTiming = timingFor(selected);
  const mediaCards = [];
  const mediaWires = [];
  const byTargetCount = new Map();
  for (const h of hooks) {
    const tgt = nodeMap.get(h.targetBeatId);
    if (!tgt) continue;
    const idx = byTargetCount.get(tgt.id) || 0;
    byTargetCount.set(tgt.id, idx + 1);
    const mx = tgt.x + 266;
    const my = Math.max(18, tgt.y - 10 + idx * 82);
    const mNode = { ...h, x: mx, y: my };
    mediaCards.push(mNode);
    mediaWires.push({ mNode, tgt });
  }

  return `
    <div class="sg-shell ${compact ? 'is-compact' : ''}" id="sgStoryMount">
      <section class="sg-canvas-col" aria-label="Story Graph Beat DAG">
        <div class="sg-breadcrumb-bar">
          <div class="sg-breadcrumbs" role="tablist" aria-label="Houdini Node Depth Level">
            <button type="button" class="sg-crumb-btn ${sgState.level === 1 ? 'is-active' : ''}" data-sg-level="1">L1 · Story Graph</button>
            <span class="sg-crumb-sep" aria-hidden="true">›</span>
            <button type="button" class="sg-crumb-btn ${sgState.level === 2 ? 'is-active' : ''}" data-sg-level="2">L2 · Scene Blocks (${escapeHtml(selected?.id || 'B01')})</button>
            <span class="sg-crumb-sep" aria-hidden="true">›</span>
            <button type="button" class="sg-crumb-btn ${sgState.level === 3 ? 'is-active' : ''}" data-sg-level="3">L3 · Engine Wiring</button>
          </div>
          <div class="sg-crumb-actions">
            <button type="button" class="v2-mini-btn" id="sgHookMediaBtn" title="Attach a PDF, Movie, Text, or Image reference">+ Hook Media</button>
            <input type="file" id="sgMediaFileInput" accept=".pdf,.txt,.md,.fountain,.docx,.png,.jpg,.jpeg,.webp,.mp4,.webm,.mov" hidden>
          </div>
        </div>

        ${sgState.level === 2 ? renderLevel2SceneBlocks(state, selected) : sgState.level === 3 ? renderLevel3EngineWiring(state, selected) : `
          <div class="sg-toolbar">
            <div class="sg-branch-group" role="group" aria-label="What-If Branches">
              <button type="button" class="sg-branch-btn" data-sg-branch="G0" aria-pressed="${sgState.activeBranch === 'G0' ? 'true' : 'false'}">${compact ? 'G0' : 'G0 · Canon'}</button>
              <button type="button" class="sg-branch-btn" data-sg-branch="G1" aria-pressed="${sgState.activeBranch === 'G1' ? 'true' : 'false'}">${compact ? 'G1' : 'G1 · What-If'}</button>
              <button type="button" class="sg-branch-btn" data-sg-branch="G2" aria-pressed="${sgState.activeBranch === 'G2' ? 'true' : 'false'}">${compact ? 'G2' : 'G2 · Cutaway'}</button>
              <button type="button" class="sg-branch-btn" data-sg-branch="ALL" aria-pressed="${sgState.activeBranch === 'ALL' ? 'true' : 'false'}">All</button>
            </div>
            <div class="sg-actions">
              ${compact ? '' : `<span class="sw-lod-pill" id="sgLodPill">LOD: ${getLodLabel(sgState.camera.zoom)}</span>`}
              <button type="button" class="v2-mini-btn" id="sgAddBeatBtn">+ Beat</button>
              <button type="button" class="v2-mini-btn" id="sgZoomOutBtn">-</button>
              <span class="sw-lod-pill" id="sgZoomPct">${zoomPct}%</span>
              <button type="button" class="v2-mini-btn" id="sgZoomInBtn">+</button>
              <button type="button" class="v2-mini-btn" id="sgFitBtn">Fit</button>
            </div>
          </div>

          <div class="sg-viewport" id="sgViewport">
            <div class="sg-stage" id="sgStage" data-lod="${lod}" style="height:${stageHeight}px; transform: translate(${sgState.camera.tx}px, ${sgState.camera.ty}px) scale(${sgState.camera.zoom});">
              <svg class="sg-wires" id="sgWires" viewBox="0 0 1400 ${stageHeight}" style="height:${stageHeight}px;">
                ${wires.map((w) => `<path class="sg-wire ${w.branch ? 'is-branch' : ''}" data-sg-from="${escapeHtml(w.from.id)}" data-sg-to="${escapeHtml(w.to.id)}" d="${wirePath(w.from, w.to)}"></path>`).join('')}
                ${mediaWires.map(({ mNode, tgt }) => `<path class="sg-wire is-media" d="${mediaWirePath(mNode, tgt)}"></path>`).join('')}
              </svg>

              ${betweenSlots.map((slot) => `
                <button
                  type="button"
                  class="sg-between-slot"
                  data-sg-between-from="${escapeHtml(slot.fromId)}"
                  data-sg-between-to="${escapeHtml(slot.toId)}"
                  style="left:${slot.x}px; top:${slot.y}px;"
                  title="Click or drop PDF/Movie/Text here to hook media between ${escapeHtml(slot.fromId)} and ${escapeHtml(slot.toId)}"
                >+ Media</button>
              `).join('')}

              ${mediaCards.map((m) => `
                <article class="sg-media-node" data-sg-media-id="${escapeHtml(m.id)}" style="left:${m.x}px; top:${m.y}px;">
                  <span class="sg-port is-media-out" title="Media Out -> Scene Media Port"></span>
                  <div class="sg-media-head">
                    <span class="sw-badge is-copper">${escapeHtml(m.mediaType.toUpperCase())}</span>
                    ${m.assetId ? '' : `<button type="button" class="sg-media-del" data-sg-del-media="${escapeHtml(m.id)}" title="Remove media hook">×</button>`}
                  </div>
                  <strong title="${escapeHtml(m.name)}">${escapeHtml(m.name)}</strong>
                  <small>→ ${escapeHtml(m.targetBeatId)} Media Port</small>
                </article>
              `).join('')}

              ${nodes.map((n) => {
                const timing = timingFor(n);
                const p = timing || getPortal(n.id);
                const clips = sgState.rhythmClips[n.id] || [];
                const mCount = hooks.filter((h) => h.targetBeatId === n.id).length;
                const isSel = selected?.id === n.id;
                const isStage = n.nodeType === 'STAGE';
                const tagText = n.branch === 'G0' ? (n.nodeType || 'CANON') : 'WHAT-IF';
                return `
                  <article
                    class="sg-node ${n.branch === 'G0' ? 'is-canon' : 'is-whatif'} ${isStage ? 'is-stage' : ''} ${isSel ? 'is-selected' : ''}"
                    data-sg-beat="${escapeHtml(n.id)}"
                    data-sg-block="${escapeHtml(n.blockId || '')}"
                    style="left:${n.x}px; top:${n.y}px;"
                    tabindex="0"
                    title="Double-click to dive into L2 Scene Blocks"
                  >
                    <span class="sg-port is-in" title="Scene Flow In"></span>
                    <span class="sg-port is-media" data-sg-media-drop="${escapeHtml(n.id)}" title="Drop PDF, Movie, Text, or Image here"></span>
                    <span class="sg-port is-out" title="Scene Flow Out"></span>
                    <div class="sg-node-head">
                      <span>${escapeHtml(n.id)} · ${escapeHtml(n.branch)}</span>
                      <span class="sw-badge ${isStage ? 'is-copper' : n.branch === 'G0' ? 'is-mint' : 'is-copper'}">${escapeHtml(tagText)}</span>
                    </div>
                    <div class="sg-node-body">
                      <strong>${escapeHtml(n.title)}</strong>
                      <small>${escapeHtml(n.summary || ((n.speakers || []).length ? `Cast: ${n.speakers.join(', ')}` : 'Active Beat Node'))}</small>
                      <div class="sg-node-ports">
                        <span class="sg-portal-dots">${p.sight ? '👁' : '—'} ${p.audio ? '🔊' : '—'}</span>
                        ${timing?.marker || timing?.act ? `<span class="sg-rhythm-pill sg-turning-point" title="${escapeHtml(timing.marker || timing.act)}">${escapeHtml(timing.marker || timing.act)}</span>` : ''}
                        ${timing?.tension != null ? `<span class="sg-rhythm-pill" title="${n.passage ? 'Saved tension' : 'Fork source tension'}">${timing.tension}/5</span>` : ''}
                        ${mCount ? `<span class="sg-rhythm-pill">📎 ${mCount}</span>` : ''}
                        <span class="sg-rhythm-pill">🔥 ${clips.length}</span>
                        <button type="button" class="sg-dive-mini" data-sg-dive-beat="${escapeHtml(n.id)}" title="Open L2 Scene Blocks">L2 ↓</button>
                      </div>
                    </div>
                  </article>
                `;
              }).join('')}
            </div>

            ${sgState.toast ? `<div class="sg-toast">${escapeHtml(sgState.toast)}</div>` : ''}
          </div>
        `}
      </section>

      ${compact ? `
        <footer class="sg-compact-rhythm" aria-label="Beat Rhythm Quick Dock">
          ${selected ? `
            <div class="sg-compact-rhythm-head">
              <strong>◈ ${escapeHtml(selected.id)} · ${escapeHtml(selected.title)}</strong>
              <span class="sg-rhythm-pill">🔥 ${selRhythm.length} Rhythm · 📎 ${selMedia.length} Media</span>
            </div>
            <div class="sg-compact-rhythm-row">
              <button type="button" class="v2-mini-btn" id="sgJumpComposeBtn">Jump ↗</button>
            </div>
          ` : ''}
        </footer>
      ` : `
        <aside class="sg-inspector" aria-label="Beat and Rhythm Inspector">
          ${selected ? `
            <div class="sg-insp-card">
              <h3>Selected Beat · ${escapeHtml(selected.id)}</h3>
              <strong>${escapeHtml(selected.title)}</strong>
              <small>${escapeHtml(selected.summary)}</small>
              ${selectedTiming ? `<small>${selected.passage ? 'Passage timing' : `Fork source timing · ${escapeHtml(selected.forkFrom)}`}
                ${selectedTiming.duration_ms === null ? '' : ` · ${selectedTiming.duration_ms} ms`}
                ${selectedTiming.tension === null ? '' : ` · Tension ${selectedTiming.tension}/5`}</small>` : ''}
              <div style="display:flex;gap:6px;flex-wrap:wrap;">
                <button type="button" class="v2-btn v2-btn-accent" id="sgJumpComposeBtn">Jump to Compose ↗</button>
                <button type="button" class="v2-btn" data-sg-level="2">L2 Blocks ↓</button>
                <button type="button" class="v2-btn" data-sg-level="3">L3 Wiring ↓</button>
              </div>
            </div>

            <div class="sg-insp-card">
              <h3>Reference Media (${selMedia.length})</h3>
              <button type="button" class="v2-mini-btn" id="sgMediaVaultBtn" data-open-media-vault>Open Media Vault</button>
              <div class="sg-rhythm-list">
                ${selMedia.map((m) => `
                  <div class="sg-rhythm-item">
                    <span>${escapeHtml(m.name)}</span>
                    <span class="sw-badge is-copper">${escapeHtml(m.mediaType.toUpperCase())}</span>
                  </div>
                `).join('') || '<small>Drop a PDF, Movie, Text, or Image onto a node or + Media slot.</small>'}
              </div>
            </div>

            ${renderActStructure(state)}
          ` : ''}
        </aside>
      `}
    </div>
  `;
}

export function bindStoryGraphCanvas({ state, store, compact = false, onJumpToBlock, onLiveL2BlockEdit, onRerender }) {
  const rerender = () => {
    const mount = document.getElementById('sgStoryMount')?.parentElement;
    if (mount) {
      const current = store?.get() || state;
      mount.innerHTML = renderStoryGraphCanvas(current, { compact });
      bindActStructure(store, NoirApi, mount);
      bindStoryGraphCanvas({ state: current, store, compact, onJumpToBlock, onLiveL2BlockEdit, onRerender });
    } else if (onRerender) {
      onRerender();
    }
  };

  const mediaDestination = (id) => {
    const current = store.get();
    return savedStoryMedia(current, buildBeatsFromState(current).nodes).get(id)?.target;
  };
  document.getElementById('sgMediaVaultBtn')?.addEventListener('click', (event) => {
    event.stopPropagation();
    openMediaVault(store, mediaDestination(sgState.selectedBeatId));
  });

  const attachMediaFile = async (file, targetBeatId) => {
    try {
      const target = mediaDestination(targetBeatId);
      if (!target) throw new Error('Choose a node tied to a saved beat or scene. Save any Compose edits first.');
      const pinRole = /^(audio|video)\//.test(file.type) ? 'rhythm_timing' : 'relationship_chemistry';
      const result = await uploadMediaFiles(store, [file], { target, pinRole });
      sgState.toast = result.errors.join(' · ') || `Saved media pin for ${file.name}.`;
    } catch (err) {
      sgState.toast = err.message;
    }
    rerender();
  };

  document.querySelectorAll('[data-sg-level]').forEach((btn) => {
    btn.addEventListener('click', () => {
      playTick();
      sgState.level = Number(btn.dataset.sgLevel) || 1;
      rerender();
    });
  });

  document.querySelectorAll('[data-sg-dive-beat]').forEach((btn) => {
    btn.addEventListener('click', (e) => {
      e.stopPropagation();
      playSelect();
      sgState.selectedBeatId = btn.dataset.sgDiveBeat;
      sgState.level = 2;
      rerender();
    });
  });

  document.getElementById('sgHookMediaBtn')?.addEventListener('click', () => {
    sgState.pendingHookTarget = { targetBeatId: sgState.selectedBeatId || 'B01', betweenFromId: '' };
    document.getElementById('sgMediaFileInput')?.click();
  });

  document.querySelectorAll('.sg-between-slot').forEach((slot) => {
    slot.addEventListener('click', () => {
      sgState.pendingHookTarget = { targetBeatId: slot.dataset.sgBetweenTo, betweenFromId: slot.dataset.sgBetweenFrom };
      document.getElementById('sgMediaFileInput')?.click();
    });
    slot.addEventListener('dragover', (e) => { e.preventDefault(); slot.classList.add('is-drop'); });
    slot.addEventListener('dragleave', () => slot.classList.remove('is-drop'));
    slot.addEventListener('drop', (e) => {
      e.preventDefault();
      slot.classList.remove('is-drop');
      const f = e.dataTransfer?.files?.[0];
      if (f) attachMediaFile(f, slot.dataset.sgBetweenTo);
    });
  });

  document.getElementById('sgMediaFileInput')?.addEventListener('change', (e) => {
    const f = e.target?.files?.[0];
    if (f) {
      const { targetBeatId } = sgState.pendingHookTarget || {};
      attachMediaFile(f, targetBeatId || sgState.selectedBeatId);
    }
  });

  document.querySelectorAll('[data-sg-del-media]').forEach((btn) => {
    btn.addEventListener('click', (e) => {
      e.stopPropagation();
      const targetId = btn.dataset.sgDelMedia;
      const hook = sgState.mediaHooks.find((h) => h.id === targetId);
      const removeFn = () => {
        sgState.mediaHooks = sgState.mediaHooks.filter((h) => h.id !== targetId);
        saveLocalStore();
      };
      if (window.__noirHistory && hook) {
        window.__noirHistory.softDelete(
          `Remove media hook ${hook.name}`,
          'media_hook',
          getSgSnap,
          (s) => applySgSnap(s, rerender),
          removeFn,
          () => {
            if (!sgState.mediaHooks.some((h) => h.id === hook.id)) sgState.mediaHooks.push(hook);
            saveLocalStore();
            rerender();
          },
        );
      } else {
        removeFn();
      }
      playTick();
      rerender();
    });
  });

  // Level 2 Live Bi-Directional Editing -> Composer
  document.querySelectorAll('[data-sg-l2-block]').forEach((ta) => {
    ta.addEventListener('input', () => {
      const bid = ta.dataset.sgL2Block;
      if (onLiveL2BlockEdit) onLiveL2BlockEdit(bid, ta.value);
    });
  });

  document.querySelectorAll('[data-sg-branch]').forEach((btn) => {
    btn.addEventListener('click', () => {
      playTick();
      sgState.activeBranch = btn.dataset.sgBranch;
      rerender();
    });
  });

  document.getElementById('sgAddBeatBtn')?.addEventListener('click', () => {
    playSelect();
    const { nodes } = buildBeatsFromState(state);
    const nextNum = nodes.length + 1;
    const id = `B${String(nextNum).padStart(2, '0')}`;
    const branch = sgState.activeBranch === 'ALL' ? 'G0' : sgState.activeBranch;
    const mutate = () => {
      sgState.customBeats.push({
        id,
        title: `New Beat ${id}`,
        summary: 'Author-added beat node (drag rhythm or edit in Compose).',
        branch,
        forkFrom: sgState.selectedBeatId || 'B01',
        blockId: '',
      });
      sgState.selectedBeatId = id;
      sgState.toast = `Added Beat node ${id} on ${branch}.`;
      saveLocalStore();
    };
    if (window.__noirHistory) {
      window.__noirHistory.commit(`Add Beat ${id}`, getSgSnap, (s) => applySgSnap(s, rerender), mutate);
    } else {
      mutate();
    }
    rerender();
  });

  document.getElementById('sgJumpComposeBtn')?.addEventListener('click', () => {
    playSelect();
    const { nodes } = buildBeatsFromState(state);
    const beat = nodes.find((n) => n.id === sgState.selectedBeatId);
    if (onJumpToBlock) onJumpToBlock(beat?.blockId || '', beat?.id || '');
  });

  const viewport = document.getElementById('sgViewport');
  const stage = document.getElementById('sgStage');
  const applyCam = () => {
    if (!stage) return;
    stage.style.transform = `translate(${sgState.camera.tx}px, ${sgState.camera.ty}px) scale(${sgState.camera.zoom})`;
    stage.dataset.lod = getLodLabel(sgState.camera.zoom).toLowerCase();
    const zp = document.getElementById('sgZoomPct');
    const lp = document.getElementById('sgLodPill');
    if (zp) zp.textContent = `${Math.round(sgState.camera.zoom * 100)}%`;
    if (lp) lp.textContent = `LOD: ${getLodLabel(sgState.camera.zoom)}`;
  };

  document.getElementById('sgZoomInBtn')?.addEventListener('click', () => {
    sgState.camera.zoom = Math.min(2, +(sgState.camera.zoom + 0.15).toFixed(2));
    applyCam();
  });
  document.getElementById('sgZoomOutBtn')?.addEventListener('click', () => {
    sgState.camera.zoom = Math.max(0.4, +(sgState.camera.zoom - 0.15).toFixed(2));
    applyCam();
  });
  document.getElementById('sgFitBtn')?.addEventListener('click', () => {
    sgState.camera = { tx: 28, ty: 20, zoom: 1 };
    applyCam();
  });

  viewport?.addEventListener('wheel', (e) => {
    e.preventDefault();
    const delta = e.deltaY < 0 ? 0.1 : -0.1;
    sgState.camera.zoom = Math.max(0.4, Math.min(2.0, +(sgState.camera.zoom + delta).toFixed(2)));
    applyCam();
  }, { passive: false });

  let drag = null;
  viewport?.addEventListener('pointerdown', (e) => {
    if (e.target.closest('button')) return;
    const nodeEl = e.target.closest('.sg-node');
    if (nodeEl) {
      const id = nodeEl.dataset.sgBeat;
      const pos = sgState.nodePos[id];
      if (pos) drag = { type: 'node', id, el: nodeEl, sx: e.clientX, sy: e.clientY, ox: pos.x, oy: pos.y };
      return;
    }
    drag = { type: 'pan', sx: e.clientX, sy: e.clientY, otx: sgState.camera.tx, oty: sgState.camera.ty };
    viewport.classList.add('is-panning');
  });

  window.addEventListener('pointermove', (e) => {
    if (!drag) return;
    if (drag.type === 'pan') {
      sgState.camera.tx = drag.otx + (e.clientX - drag.sx);
      sgState.camera.ty = drag.oty + (e.clientY - drag.sy);
      applyCam();
      return;
    }
    const nx = Math.round(drag.ox + (e.clientX - drag.sx) / sgState.camera.zoom);
    const ny = Math.round(drag.oy + (e.clientY - drag.sy) / sgState.camera.zoom);
    sgState.nodePos[drag.id] = { x: nx, y: ny };
    drag.el.style.left = `${nx}px`;
    drag.el.style.top = `${ny}px`;
    const { nodes } = buildBeatsFromState(state);
    const nmap = new Map(nodes.map((n) => [n.id, n]));
    document.querySelectorAll('#sgWires .sg-wire').forEach((pathEl) => {
      const fn = nmap.get(pathEl.dataset.sgFrom);
      const tn = nmap.get(pathEl.dataset.sgTo);
      if (fn && tn) pathEl.setAttribute('d', wirePath(fn, tn));
    });
  });

  window.addEventListener('pointerup', () => {
    if (drag?.type === 'pan') viewport?.classList.remove('is-panning');
    drag = null;
  });

  document.querySelectorAll('.sg-node').forEach((nodeEl) => {
    nodeEl.addEventListener('click', () => {
      const beatId = nodeEl.dataset.sgBeat;
      if (sgState.selectedBeatId === beatId) return;
      playSelect();
      sgState.selectedBeatId = beatId;
      rerender();
    });
    nodeEl.addEventListener('dblclick', () => {
      playSelect();
      sgState.selectedBeatId = nodeEl.dataset.sgBeat;
      const passage = buildBeatsFromState(store.get()).nodes.find((node) => node.id === sgState.selectedBeatId)?.passage;
      if (passage) store.emit?.('story:beat-selected', passage.id);
      sgState.level = 2;
      rerender();
    });
    nodeEl.addEventListener('dragover', (e) => {
      e.preventDefault();
      nodeEl.classList.add('is-drop');
    });
    nodeEl.addEventListener('dragleave', () => nodeEl.classList.remove('is-drop'));
    nodeEl.addEventListener('drop', async (e) => {
      e.preventDefault();
      nodeEl.classList.remove('is-drop');
      const beatId = nodeEl.dataset.sgBeat;
      const droppedFile = e.dataTransfer?.files?.[0];
      if (droppedFile) {
        await attachMediaFile(droppedFile, beatId);
        return;
      }

    });
  });

  document.querySelectorAll('[data-sg-test-asset]').forEach((chip) => {
    chip.addEventListener('dragstart', (e) => {
      e.dataTransfer.setData('text/plain', chip.dataset.sgTestAsset);
    });
  });
}
