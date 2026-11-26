/* Noir Fiction Studio v2 — G2 Pure Headless Procedural Graph Kernel (ZERO DOM / Canvas / Fetch) */

export const PORT_TYPES = Object.freeze({
  BEAT_STREAM: { id: 'BEAT_STREAM', label: 'Beat Stream', colorToken: '--accent-primary', fallbackColor: '#ffb07d' },
  CAST: { id: 'CAST', label: 'Cast Voice', colorToken: '--accent-secondary', fallbackColor: '#90e9cd' },
  FORM: { id: 'FORM', label: 'Character Form', colorToken: '--focus-ring', fallbackColor: '#6cb4ee' },
  MIND: { id: 'MIND', label: 'Mind State', colorToken: '--stripe-chrome', fallbackColor: '#b4a7e5' },
  MEDIA: { id: 'MEDIA', label: 'Media Envelope', colorToken: '--status-ok-ink', fallbackColor: '#f59e0b' },
  LAW: { id: 'LAW', label: 'World Law', colorToken: '--status-err-ink', fallbackColor: '#ef4444' },
  BOOK_CRAFT: { id: 'BOOK_CRAFT', label: '190-Book Craft', colorToken: '--stripe-chrome', fallbackColor: '#8b5cf6' },
  DIALOGUE_STREAM: { id: 'DIALOGUE_STREAM', label: 'Dialogue Stream', colorToken: '--stripe-chrome', fallbackColor: '#a78bfa' },
  ANY: { id: 'ANY', label: 'Any Stream', colorToken: '--ink-muted-on-chrome', fallbackColor: '#b6b1aa' },
});

export function isPortTypeCompatible(outType, inType) {
  if (!outType || !inType) return false;
  if (outType === 'ANY' || inType === 'ANY') return true;
  if (outType === inType) return true;
  if (outType === 'DIALOGUE_STREAM' && inType === 'BEAT_STREAM') return true;
  if (outType === 'BOOK_CRAFT' && (inType === 'BEAT_STREAM' || inType === 'DIALOGUE_STREAM' || inType === 'BOOK_CRAFT')) return true;
  if (outType === 'MIND' && (inType === 'CAST' || inType === 'FORM')) return true;
  if (outType === 'MEDIA' && (inType === 'BEAT_STREAM' || inType === 'CAST' || inType === 'MEDIA')) return true;
  return false;
}

export const OPERATOR_SPECS = Object.freeze({
  episode_source: {
    type: 'episode_source',
    label: 'Episode Source',
    category: 'Story',
    inputs: [],
    outputs: [{ id: 'beats', label: 'Beat Stream', dataType: 'BEAT_STREAM' }],
    parms: [
      { key: 'title', label: 'Title', kind: 'text', default: 'Episode Source' },
      { key: 'branch', label: 'Branch', kind: 'text', default: 'main' },
    ],
  },
  scene: {
    type: 'scene',
    label: 'Scene',
    category: 'Story',
    inputs: [
      { id: 'beats_in', label: 'Prev Beats', dataType: 'BEAT_STREAM', multi: false },
      { id: 'cast', label: 'Cast', dataType: 'CAST', multi: true },
      { id: 'laws', label: 'Laws', dataType: 'LAW', multi: true },
    ],
    outputs: [{ id: 'beats_out', label: 'Scene Beats', dataType: 'BEAT_STREAM' }],
    parms: [
      { key: 'title', label: 'Title', kind: 'text', default: 'Scene' },
      { key: 'heading', label: 'Heading', kind: 'text', default: 'INT. LOCATION - NIGHT' },
      { key: 'tension', label: 'Tension', kind: 'slider', default: 0.5, min: 0, max: 1, step: 0.05 },
      { key: 'pacing', label: 'Pacing', kind: 'select', default: 'steady', options: ['slow', 'steady', 'fast'] },
    ],
  },
  beat: {
    type: 'beat',
    label: 'Story Beat',
    category: 'Story',
    inputs: [
      { id: 'in', label: 'In', dataType: 'BEAT_STREAM', multi: false },
      { id: 'cast', label: 'Speaker', dataType: 'CAST', multi: true },
      { id: 'media', label: 'Gag Media', dataType: 'MEDIA', multi: true },
      { id: 'craft', label: 'Book Craft', dataType: 'BOOK_CRAFT', multi: true },
    ],
    outputs: [{ id: 'out', label: 'Out', dataType: 'BEAT_STREAM' }],
    parms: [
      { key: 'title', label: 'Title', kind: 'text', default: 'Beat' },
      { key: 'speaker', label: 'Speaker', kind: 'text', default: '' },
      { key: 'protected_pct', label: 'Protection %', kind: 'slider', default: 50, min: 0, max: 100, step: 25 },
    ],
  },
  branch_junction: {
    type: 'branch_junction',
    label: 'Story Junction',
    category: 'Story',
    inputs: [{ id: 'in', label: 'In', dataType: 'BEAT_STREAM', multi: false }],
    outputs: [
      { id: 'branch_a', label: 'Junction 1', dataType: 'BEAT_STREAM', multi: true },
      { id: 'branch_b', label: 'Junction 2', dataType: 'BEAT_STREAM', multi: true },
    ],
    parms: [
      { key: 'title', label: 'Junction Label', kind: 'text', default: 'Story Junction' },
      { key: 'active_branch', label: 'Active Route', kind: 'select', default: 'branch_b', options: ['branch_a', 'branch_b'] },
      { key: 'ui_only_label', label: 'UI-Only Label (No Literal Prose)', kind: 'toggle', default: true },
    ],
  },
  deep_mine: {
    type: 'deep_mine',
    label: 'Deep Mining Node',
    category: 'Modifiers',
    inputs: [],
    outputs: [{ id: 'telemetry', label: 'Media Telemetry', dataType: 'MEDIA', multi: true }],
    parms: [
      { key: 'title', label: 'Clip Asset', kind: 'text', default: 'Complete Cutaway.mp4' },
      { key: 'loose_override', label: 'Override Guidance', kind: 'text', default: '' },
    ],
  },
  multi_wire_gag: {
    type: 'multi_wire_gag',
    label: 'Multi-Wire Gag',
    category: 'Modifiers',
    inputs: [{ id: 'media_in', label: 'Source Clip', dataType: 'MEDIA', multi: false }],
    outputs: [{ id: 'fan_out', label: 'Fan-Out Beats', dataType: 'MEDIA', multi: true }],
    parms: [
      { key: 'title', label: 'Gag Name', kind: 'text', default: 'Billy and Mandy Gag.mp4' },
      { key: 'loose_override', label: 'Loose Execution Override', kind: 'text', default: 'Haley treated like Ernie getting farted and defeated repeatedly' },
    ],
  },
  character_form: {
    type: 'character_form',
    label: 'Character Form',
    category: 'Cast',
    inputs: [{ id: 'laws', label: 'Laws', dataType: 'LAW', multi: true }],
    outputs: [
      { id: 'cast', label: 'Cast Voice', dataType: 'CAST' },
      { id: 'form', label: 'Form State', dataType: 'FORM' },
    ],
    parms: [
      { key: 'title', label: 'Character', kind: 'text', default: 'Character' },
      { key: 'character_id', label: 'Character ID', kind: 'text', default: '' },
      { key: 'form_id', label: 'Form ID', kind: 'text', default: 'base' },
      { key: 'voice_arch', label: 'Voice Arch', kind: 'slider', default: 0.9, min: 0, max: 1, step: 0.05 },
      { key: 'glamour', label: 'Glamour', kind: 'slider', default: 0.5, min: 0, max: 1, step: 0.05 },
      { key: 'farce', label: 'Farce', kind: 'slider', default: 0.4, min: 0, max: 1, step: 0.05 },
      { key: 'freeze_lock', label: 'Freeze Lock', kind: 'toggle', default: false },
    ],
  },
  dialogue_dial: {
    type: 'dialogue_dial',
    label: 'Dialogue Dial',
    category: 'Modifiers',
    inputs: [
      { id: 'beats', label: 'Beats', dataType: 'BEAT_STREAM', multi: false },
      { id: 'cast_1', label: 'Cast 1', dataType: 'CAST', multi: false },
      { id: 'cast_2', label: 'Cast 2', dataType: 'CAST', multi: false },
      { id: 'cast_3', label: 'Cast 3', dataType: 'CAST', multi: false },
      { id: 'cast_4', label: 'Cast 4', dataType: 'CAST', multi: false },
    ],
    outputs: [{ id: 'dialogue', label: 'Dialogue Stream', dataType: 'DIALOGUE_STREAM' }],
    parms: [
      { key: 'title', label: 'Title', kind: 'text', default: 'Dialogue Dial' },
      { key: 'influence', label: 'Influence', kind: 'slider', default: 0.85, min: 0, max: 1, step: 0.05 },
      { key: 'sarcasm', label: 'Sarcasm', kind: 'slider', default: 0.35, min: 0, max: 1, step: 0.05 },
      { key: 'banter', label: 'Banter', kind: 'slider', default: 0.6, min: 0, max: 1, step: 0.05 },
    ],
  },
  world_law: {
    type: 'world_law',
    label: 'World Law',
    category: 'Constraints',
    inputs: [],
    outputs: [{ id: 'law', label: 'World Law', dataType: 'LAW' }],
    parms: [
      { key: 'title', label: 'Law Name', kind: 'text', default: 'World Law' },
      { key: 'modality', label: 'Modality', kind: 'text', default: 'hard_invariant' },
      { key: 'valid_from_episode', label: 'Valid From Episode', kind: 'text', default: '*' },
      { key: 'rule', label: 'Constraint Rule', kind: 'text', default: '' },
      { key: 'strict', label: 'Strict Enforcement', kind: 'toggle', default: true },
    ],
  },
  morph_transition: {
    type: 'morph_transition',
    label: 'Morph Transition',
    category: 'Modifiers',
    inputs: [
      { id: 'form_a', label: 'Form A', dataType: 'FORM', multi: false },
      { id: 'form_b', label: 'Form B', dataType: 'FORM', multi: false },
      { id: 'beats', label: 'Trigger Beats', dataType: 'BEAT_STREAM', multi: false },
    ],
    outputs: [{ id: 'beats_out', label: 'Morphed Beats', dataType: 'BEAT_STREAM' }],
    parms: [
      { key: 'title', label: 'Title', kind: 'text', default: 'Morph Transition' },
      { key: 'trigger_cue', label: 'Trigger Cue', kind: 'text', default: '' },
      { key: 'preserve_voice', label: 'Preserve Core Voice', kind: 'toggle', default: true },
    ],
  },
  compile_out: {
    type: 'compile_out',
    label: 'Compile Output',
    category: 'Output',
    inputs: [{ id: 'final_in', label: 'Final Stream', dataType: 'BEAT_STREAM', multi: true }],
    outputs: [],
    parms: [
      { key: 'title', label: 'Title', kind: 'text', default: 'Manuscript Out' },
      { key: 'word_target', label: 'Word Target', kind: 'slider', default: 2500, min: 250, max: 10000, step: 250 },
    ],
  },
  subnet: {
    type: 'subnet',
    label: 'Subnet',
    category: 'Story',
    inputs: [{ id: 'in', label: 'Sub In', dataType: 'ANY', multi: true }],
    outputs: [{ id: 'out', label: 'Sub Out', dataType: 'ANY' }],
    parms: [{ key: 'title', label: 'Subnet Name', kind: 'text', default: 'Subnet' }],
  },
  note: {
    type: 'note',
    label: 'Note / Event',
    category: 'Story',
    inputs: [{ id: 'in', label: 'In', dataType: 'ANY', multi: true }],
    outputs: [{ id: 'out', label: 'Out', dataType: 'ANY' }],
    parms: [
      { key: 'title', label: 'Title', kind: 'text', default: 'Note' },
      { key: 'notes', label: 'Notes', kind: 'text', default: '' },
    ],
  },
  character_switchyard: {
    type: 'character_switchyard',
    label: 'Form Switchyard (N-Forms)',
    category: 'Cast',
    inputs: [
      { id: 'laws', label: 'Laws', dataType: 'LAW', multi: true },
      { id: 'mind', label: 'Mind', dataType: 'MIND', multi: true },
    ],
    outputs: [
      { id: 'cast', label: 'Active Cast', dataType: 'CAST' },
      { id: 'form', label: 'Active Form', dataType: 'FORM' },
    ],
    parms: [
      { key: 'title', label: 'Character', kind: 'text', default: 'Switchyard' },
      { key: 'character_id', label: 'Character ID', kind: 'text', default: 'rainee' },
      { key: 'active_form', label: 'Active Form ID', kind: 'text', default: 'base' },
      { key: 'forms_count', label: 'Forms Count (N)', kind: 'slider', default: 3, min: 1, max: 12, step: 1 },
    ],
  },
  mind_state: {
    type: 'mind_state',
    label: 'Mind State',
    category: 'Mind',
    inputs: [{ id: 'form', label: 'Form', dataType: 'FORM', multi: false }],
    outputs: [{ id: 'mind', label: 'Mind Intent', dataType: 'MIND' }],
    parms: [
      { key: 'title', label: 'Mind Label', kind: 'text', default: 'Mind State' },
      { key: 'when_pressure', label: 'When Pressure', kind: 'text', default: '' },
      { key: 'tactic', label: 'Tactic / Goal', kind: 'text', default: '' },
      { key: 'epistemic_scope', label: 'Epistemic Scope', kind: 'text', default: 'scene_only' },
    ],
  },
  media_clip: {
    type: 'media_clip',
    label: 'Media Cue / Timing',
    category: 'Output',
    inputs: [{ id: 'in', label: 'Trigger', dataType: 'ANY', multi: true }],
    outputs: [{ id: 'media', label: 'Timing Envelope', dataType: 'MEDIA' }],
    parms: [
      { key: 'title', label: 'Clip Label', kind: 'text', default: 'Media Clip' },
      { key: 'clip_id', label: 'Clip ID', kind: 'text', default: '' },
      { key: 'pause_sec', label: 'Hold Pause (s)', kind: 'slider', default: 1.5, min: 0, max: 15, step: 0.5 },
      { key: 'usage_mode', label: 'Usage Mode', kind: 'select', default: 'timing', options: ['timing', 'reference', 'preview'] },
    ],
  },
  world_law_gate: {
    type: 'world_law_gate',
    label: 'World Law Gate',
    category: 'Constraints',
    inputs: [
      { id: 'beats', label: 'Beats', dataType: 'BEAT_STREAM', multi: false },
      { id: 'laws', label: 'Laws', dataType: 'LAW', multi: true },
    ],
    outputs: [{ id: 'gated', label: 'Validated Beats', dataType: 'BEAT_STREAM' }],
    parms: [
      { key: 'title', label: 'Gate Label', kind: 'text', default: 'Canon Gate' },
      { key: 'modality', label: 'Modality', kind: 'select', default: 'hard_invariant', options: ['hard_invariant', 'soft_tendency', 'import_bleed_guard'] },
      { key: 'valid_from_episode', label: 'Valid From Episode', kind: 'text', default: '*' },
      { key: 'gate_status', label: 'Gate Status', kind: 'select', default: 'pass', options: ['pass', 'warn', 'block'] },
    ],
  },
});

const LEGACY_TYPE_ALIASES = {
  episode: 'episode_source',
  character: 'character_form',
  event: 'note',
  'source-character': 'character_form',
  'source-form': 'character_form',
  'source-state': 'character_form',
  'source-transition': 'morph_transition',
  'source-unresolved': 'note',
};

export function getOperatorSpec(type) {
  const canonical = LEGACY_TYPE_ALIASES[type] || type;
  return OPERATOR_SPECS[canonical] || OPERATOR_SPECS.scene;
}

export function listOperators(category = '') {
  const all = Object.values(OPERATOR_SPECS);
  if (!category) return all;
  return all.filter((op) => op.category.toLowerCase() === String(category).toLowerCase());
}

function defaultParmsForSpec(spec, overrides = {}) {
  const out = {};
  for (const p of spec.parms || []) {
    out[p.key] = overrides[p.key] !== undefined ? overrides[p.key] : p.default;
  }
  return { ...out, ...overrides };
}

function cloneFlags(flags = {}) {
  return {
    bypass: Boolean(flags.bypass),
    display: Boolean(flags.display),
    template: Boolean(flags.template),
    locked: Boolean(flags.locked),
  };
}

function cloneEval(ev = {}) {
  return {
    status: ev.status || 'dirty',
    dirtyReason: ev.dirtyReason || '',
    lastCookMs: ev.lastCookMs ?? null,
    error: ev.error || null,
  };
}

function cloneSnapshot(snap) {
  return {
    subnetId: snap.subnetId ?? null,
    nodes: snap.nodes.map((n) => ({
      ...n,
      inputs: (n.inputs || []).map((p) => ({ ...p })),
      outputs: (n.outputs || []).map((p) => ({ ...p })),
      parms: { ...(n.parms || {}) },
      flags: cloneFlags(n.flags),
      eval: cloneEval(n.eval),
    })),
    edges: snap.edges.map((e) => ({ ...e })),
    networkBoxes: (snap.networkBoxes || []).map((b) => ({ ...b, nodeIds: [...(b.nodeIds || [])] })),
  };
}

function nextUniqueId(items, prefix) {
  const taken = new Set(items.map((x) => String(x.id)));
  let n = items.length + 1;
  while (taken.has(`${prefix}_${n}`)) n += 1;
  return `${prefix}_${n}`;
}

export function wouldCreateCycle(edges = [], fromNode, toNode) {
  if (!fromNode || !toNode) return false;
  if (fromNode === toNode) return true;
  const adj = new Map();
  for (const e of edges) {
    if (!adj.has(e.fromNode)) adj.set(e.fromNode, []);
    adj.get(e.fromNode).push(e.toNode);
  }
  const visited = new Set([toNode]);
  const stack = [toNode];
  while (stack.length) {
    const cur = stack.pop();
    if (cur === fromNode) return true;
    for (const nxt of adj.get(cur) || []) {
      if (!visited.has(nxt)) {
        visited.add(nxt);
        stack.push(nxt);
      }
    }
  }
  return false;
}

export function canConnectPorts(snapshot, { fromNode, fromPort, toNode, toPort }) {
  if (!fromNode || !toNode) return { ok: false, reason: 'Missing source or target node.' };
  if (fromNode === toNode) return { ok: false, reason: 'Cannot connect a node to itself.' };

  const src = snapshot.nodes.find((n) => n.id === fromNode);
  const dst = snapshot.nodes.find((n) => n.id === toNode);
  if (!src || !dst) return { ok: false, reason: 'Source or target node does not exist.' };
  if ((src.parentSubnetId ?? null) !== (dst.parentSubnetId ?? null)) {
    return { ok: false, reason: 'Cannot wire across different subnet levels.' };
  }

  const outPin = (src.outputs || []).find((p) => p.id === fromPort) || src.outputs?.[0];
  const inPin = (dst.inputs || []).find((p) => p.id === toPort) || dst.inputs?.[0];
  if (!outPin) return { ok: false, reason: `Node "${src.title}" has no compatible output port.` };
  if (!inPin) return { ok: false, reason: `Node "${dst.title}" has no compatible input port.` };

  if (!isPortTypeCompatible(outPin.dataType, inPin.dataType)) {
    return {
      ok: false,
      reason: `Incompatible port types: ${outPin.dataType} → ${inPin.dataType}.`,
    };
  }

  const duplicate = snapshot.edges.find(
    (e) =>
      e.fromNode === src.id &&
      e.fromPort === outPin.id &&
      e.toNode === dst.id &&
      e.toPort === inPin.id
  );
  if (duplicate) return { ok: false, reason: 'Connection already exists.' };

  if (wouldCreateCycle(snapshot.edges, src.id, dst.id)) {
    return { ok: false, reason: `Cycle rejected: ${src.id} → ${dst.id}.` };
  }

  const existingSingle = !inPin.multi
    ? snapshot.edges.find((e) => e.toNode === dst.id && e.toPort === inPin.id)
    : null;

  return {
    ok: true,
    reason: null,
    fromPort: outPin.id,
    toPort: inPin.id,
    dataType: outPin.dataType,
    replaceEdgeId: existingSingle ? existingSingle.id : null,
  };
}

export function topologicalSort(snapshot, targetNodeId = null) {
  const nodes = snapshot.nodes || [];
  const edges = snapshot.edges || [];
  const byId = new Map(nodes.map((n) => [n.id, n]));

  let relevantIds;
  if (targetNodeId && byId.has(targetNodeId)) {
    relevantIds = new Set([targetNodeId]);
    const back = new Map();
    for (const e of edges) {
      if (!back.has(e.toNode)) back.set(e.toNode, []);
      back.get(e.toNode).push(e.fromNode);
    }
    const stack = [targetNodeId];
    while (stack.length) {
      const cur = stack.pop();
      for (const prev of back.get(cur) || []) {
        if (!relevantIds.has(prev) && byId.has(prev)) {
          relevantIds.add(prev);
          stack.push(prev);
        }
      }
    }
  } else {
    relevantIds = new Set(nodes.map((n) => n.id));
  }

  const inDeg = new Map();
  const adj = new Map();
  for (const id of relevantIds) {
    inDeg.set(id, 0);
    adj.set(id, []);
  }
  for (const e of edges) {
    if (relevantIds.has(e.fromNode) && relevantIds.has(e.toNode)) {
      adj.get(e.fromNode).push(e.toNode);
      inDeg.set(e.toNode, inDeg.get(e.toNode) + 1);
    }
  }

  const queue = Array.from(relevantIds).filter((id) => inDeg.get(id) === 0).sort();
  const order = [];
  while (queue.length) {
    const id = queue.shift();
    order.push(id);
    for (const nxt of adj.get(id) || []) {
      const deg = inDeg.get(nxt) - 1;
      inDeg.set(nxt, deg);
      if (deg === 0) queue.push(nxt);
    }
  }
  return order;
}

export function markDownstreamDirty(snapshot, startNodeIds = [], reason = 'upstream_changed') {
  const byId = new Map(snapshot.nodes.map((n) => [n.id, n]));
  const adj = new Map();
  for (const e of snapshot.edges) {
    if (!adj.has(e.fromNode)) adj.set(e.fromNode, []);
    adj.get(e.fromNode).push(e.toNode);
  }

  const visited = new Set();
  const stack = [...startNodeIds];
  while (stack.length) {
    const id = stack.pop();
    if (visited.has(id)) continue;
    visited.add(id);
    const node = byId.get(id);
    if (!node) continue;
    if (node.flags?.locked) {
      // Locked nodes freeze their cached output and shield themselves from re-cook,
      // while downstream unlocked nodes still mark dirty from upstream edits.
      continue;
    }
    node.eval = { ...node.eval, status: 'dirty', dirtyReason: reason };
    for (const nxt of adj.get(id) || []) {
      stack.push(nxt);
    }
  }
  return snapshot;
}

export function computeDirtySet(snapshot, targetNodeId = null) {
  const order = topologicalSort(snapshot, targetNodeId);
  const byId = new Map((snapshot.nodes || []).map((n) => [n.id, n]));
  return order.filter((id) => {
    const n = byId.get(id);
    if (!n) return false;
    if (n.flags?.bypass || n.flags?.locked) return false;
    return n.eval?.status !== 'clean' || id === targetNodeId;
  });
}

export function computeDagLayout(snapshot, { parentSubnetId = null, colWidth = 250, rowHeight = 120, originX = 120, originY = 120 } = {}) {
  const scopeNodes = snapshot.nodes.filter((n) => (n.parentSubnetId ?? null) === parentSubnetId);
  const scopeIds = new Set(scopeNodes.map((n) => n.id));
  const scopeEdges = snapshot.edges.filter((e) => scopeIds.has(e.fromNode) && scopeIds.has(e.toNode));

  const order = topologicalSort({ nodes: scopeNodes, edges: scopeEdges });
  const rank = new Map(scopeNodes.map((n) => [n.id, 0]));
  const preds = new Map(scopeNodes.map((n) => [n.id, []]));
  for (const e of scopeEdges) {
    preds.get(e.toNode)?.push(e.fromNode);
  }

  for (const id of order) {
    let r = 0;
    for (const p of preds.get(id) || []) {
      r = Math.max(r, (rank.get(p) ?? 0) + 1);
    }
    rank.set(id, r);
  }

  const columns = new Map();
  for (const n of scopeNodes) {
    const r = rank.get(n.id) ?? 0;
    if (!columns.has(r)) columns.set(r, []);
    columns.get(r).push(n);
  }

  const maxRowsPerCol = scopeNodes.length > 24 ? 10 : scopeNodes.length;
  const positions = {};
  let cursorCol = 0;
  for (const [, colNodes] of Array.from(columns.entries()).sort((a, b) => a[0] - b[0])) {
    colNodes.sort((a, b) => (a.y ?? 0) - (b.y ?? 0) || a.id.localeCompare(b.id));
    const subCols = Math.max(1, Math.ceil(colNodes.length / maxRowsPerCol));
    colNodes.forEach((n, idx) => {
      const subCol = Math.floor(idx / maxRowsPerCol);
      const row = idx % maxRowsPerCol;
      positions[n.id] = {
        x: Math.round(originX + (cursorCol + subCol) * colWidth),
        y: Math.round(originY + row * rowHeight),
      };
    });
    cursorCol += subCols;
  }
  return positions;
}

export function fromBackendGraph(backendGraph = {}) {
  const rawNodes = Array.isArray(backendGraph.nodes) ? backendGraph.nodes : [];
  const rawEdges = Array.isArray(backendGraph.edges)
    ? backendGraph.edges
    : Array.isArray(backendGraph.connections)
    ? backendGraph.connections
    : [];

  const nodes = rawNodes.map((raw, idx) => {
    const spec = getOperatorSpec(raw.type || 'scene');
    return {
      id: String(raw.id || `node_${idx + 1}`),
      type: spec.type,
      legacyType: raw.type || spec.type,
      title: String(raw.title || raw.id || spec.label),
      x: Number.isFinite(Number(raw.x)) ? Math.round(Number(raw.x)) : 120 + (idx % 4) * 240,
      y: Number.isFinite(Number(raw.y)) ? Math.round(Number(raw.y)) : 120 + Math.floor(idx / 4) * 120,
      parentSubnetId: raw.parentSubnetId ?? null,
      inputs: (spec.inputs || []).map((p) => ({ ...p })),
      outputs: (spec.outputs || []).map((p) => ({ ...p })),
      parms: defaultParmsForSpec(spec, { title: raw.title || raw.id || spec.label, ...(raw.parms || {}) }),
      flags: cloneFlags(raw.flags),
      eval: cloneEval(raw.eval || { status: 'clean' }),
    };
  });

  const byId = new Map(nodes.map((n) => [n.id, n]));
  const edges = [];
  rawEdges.forEach((raw, idx) => {
    const fromNode = String(raw.fromNode || raw.from || '');
    const toNode = String(raw.toNode || raw.to || '');
    const src = byId.get(fromNode);
    const dst = byId.get(toNode);
    if (!src || !dst || fromNode === toNode) return;
    const fromPort = raw.fromPort || src.outputs[0]?.id || 'out';
    const toPort = raw.toPort || dst.inputs[0]?.id || 'in';
    const outPin = src.outputs.find((p) => p.id === fromPort) || src.outputs[0];
    edges.push({
      id: String(raw.id || `edge_${idx + 1}`),
      fromNode,
      fromPort,
      toNode,
      toPort,
      dataType: raw.dataType || outPin?.dataType || 'ANY',
    });
  });

  if (nodes.length > 6 && new Set(nodes.map((n) => n.y)).size <= 1) {
    const posMap = computeDagLayout({ nodes, edges });
    for (const n of nodes) {
      if (posMap[n.id]) {
        n.x = posMap[n.id].x;
        n.y = posMap[n.id].y;
      }
    }
  }

  return {
    subnetId: null,
    nodes,
    edges,
    networkBoxes: Array.isArray(backendGraph.networkBoxes)
      ? backendGraph.networkBoxes.map((b) => ({ ...b, nodeIds: [...(b.nodeIds || [])] }))
      : [],
  };
}

export function toBackendGraph(snapshot) {
  return {
    nodes: (snapshot.nodes || []).map((n) => ({
      id: n.id,
      title: n.title,
      type: n.legacyType || n.type,
      x: Math.round(n.x),
      y: Math.round(n.y),
      ...(n.parentSubnetId ? { parentSubnetId: n.parentSubnetId } : {}),
      parms: { ...(n.parms || {}) },
      flags: cloneFlags(n.flags),
    })),
    edges: (snapshot.edges || []).map((e) => ({
      id: e.id,
      from: e.fromNode,
      to: e.toNode,
      fromPort: e.fromPort,
      toPort: e.toPort,
      dataType: e.dataType,
    })),
    ...(snapshot.networkBoxes?.length ? { networkBoxes: snapshot.networkBoxes.map((b) => ({ ...b, nodeIds: [...b.nodeIds] })) } : {}),
  };
}

export function createGraphKernel(initialBackendGraph = {}, { maxHistory = 100 } = {}) {
  let current = fromBackendGraph(initialBackendGraph);
  const undoStack = [];
  const redoStack = [];
  const listeners = new Set();

  function emit() {
    const snap = getSnapshot();
    for (const fn of listeners) fn(snap);
  }

  function pushUndo(prev) {
    undoStack.push(cloneSnapshot(prev));
    if (undoStack.length > maxHistory) undoStack.shift();
    redoStack.length = 0;
  }

  function getSnapshot() {
    return cloneSnapshot(current);
  }

  function dispatch(action) {
    if (!action || !action.type) return { ok: false, error: 'Missing action type.' };

    if (action.type === 'UNDO') {
      if (!undoStack.length) return { ok: false, error: 'Nothing to undo.' };
      redoStack.push(cloneSnapshot(current));
      current = undoStack.pop();
      emit();
      return { ok: true, snapshot: getSnapshot() };
    }

    if (action.type === 'REDO') {
      if (!redoStack.length) return { ok: false, error: 'Nothing to redo.' };
      undoStack.push(cloneSnapshot(current));
      current = redoStack.pop();
      emit();
      return { ok: true, snapshot: getSnapshot() };
    }

    if (action.type === 'SET_COOK_STATE') {
      const updates = action.updates || {};
      current = {
        ...current,
        nodes: current.nodes.map((n) =>
          updates[n.id] ? { ...n, eval: { ...n.eval, ...updates[n.id] } } : n
        ),
      };
      emit();
      return { ok: true, snapshot: getSnapshot() };
    }

    if (action.type === 'ENTER_SUBNET') {
      current = { ...current, subnetId: action.subnetId ?? null };
      emit();
      return { ok: true, snapshot: getSnapshot() };
    }

    const prev = cloneSnapshot(current);
    const next = cloneSnapshot(current);

    switch (action.type) {
      case 'ADD_NODE': {
        const spec = getOperatorSpec(action.nodeType || action.operatorType || 'scene');
        const id = action.id || nextUniqueId(next.nodes, 'node');
        const title = action.title || `${spec.label} ${next.nodes.length + 1}`;
        const node = {
          id,
          type: spec.type,
          legacyType: action.nodeType || spec.type,
          title,
          x: Math.round(Number.isFinite(Number(action.x)) ? Number(action.x) : 140 + (next.nodes.length % 4) * 240),
          y: Math.round(Number.isFinite(Number(action.y)) ? Number(action.y) : 140 + Math.floor(next.nodes.length / 4) * 120),
          parentSubnetId: action.parentSubnetId !== undefined ? action.parentSubnetId : next.subnetId,
          inputs: (spec.inputs || []).map((p) => ({ ...p })),
          outputs: (spec.outputs || []).map((p) => ({ ...p })),
          parms: defaultParmsForSpec(spec, { title, ...(action.parms || {}) }),
          flags: cloneFlags(action.flags),
          eval: cloneEval({ status: 'dirty', dirtyReason: 'created' }),
        };
        next.nodes.push(node);
        pushUndo(prev);
        current = next;
        emit();
        return { ok: true, nodeId: id, snapshot: getSnapshot() };
      }

      case 'MOVE_NODES': {
        const moves = Array.isArray(action.moves) ? action.moves : [];
        let changed = false;
        const moveMap = new Map(moves.map((m) => [m.id, m]));
        for (const n of next.nodes) {
          const m = moveMap.get(n.id);
          if (!m) continue;
          const rx = Math.round(Number(m.x));
          const ry = Math.round(Number(m.y));
          if (Number.isFinite(rx) && Number.isFinite(ry) && (rx !== n.x || ry !== n.y)) {
            n.x = rx;
            n.y = ry;
            changed = true;
          }
        }
        if (!changed) return { ok: true, snapshot: getSnapshot() };
        pushUndo(prev);
        current = next;
        emit();
        return { ok: true, snapshot: getSnapshot() };
      }

      case 'REMOVE_SELECTION': {
        const rmNodes = new Set(action.nodeIds || []);
        const rmEdges = new Set(action.edgeIds || []);
        const affectedDownstream = [];
        for (const e of next.edges) {
          if (rmNodes.has(e.fromNode) || rmEdges.has(e.id)) {
            affectedDownstream.push(e.toNode);
          }
        }
        next.nodes = next.nodes.filter((n) => !rmNodes.has(n.id));
        next.edges = next.edges.filter(
          (e) => !rmEdges.has(e.id) && !rmNodes.has(e.fromNode) && !rmNodes.has(e.toNode)
        );
        next.networkBoxes = next.networkBoxes.map((b) => ({
          ...b,
          nodeIds: b.nodeIds.filter((id) => !rmNodes.has(id)),
        }));
        markDownstreamDirty(next, affectedDownstream, 'input_removed');
        pushUndo(prev);
        current = next;
        emit();
        return { ok: true, snapshot: getSnapshot() };
      }

      case 'CONNECT_PORTS': {
        const check = canConnectPorts(next, action);
        if (!check.ok) return { ok: false, error: check.reason };
        if (check.replaceEdgeId) {
          next.edges = next.edges.filter((e) => e.id !== check.replaceEdgeId);
        }
        const edge = {
          id: nextUniqueId(next.edges, 'edge'),
          fromNode: action.fromNode,
          fromPort: check.fromPort,
          toNode: action.toNode,
          toPort: check.toPort,
          dataType: check.dataType,
        };
        next.edges.push(edge);
        markDownstreamDirty(next, [action.toNode], 'edge_connected');
        pushUndo(prev);
        current = next;
        emit();
        return { ok: true, edgeId: edge.id, snapshot: getSnapshot() };
      }

      case 'DISCONNECT_EDGE': {
        const rm = new Set(action.edgeIds || (action.edgeId ? [action.edgeId] : []));
        const affected = next.edges.filter((e) => rm.has(e.id)).map((e) => e.toNode);
        if (!affected.length) return { ok: false, error: 'Edge not found.' };
        next.edges = next.edges.filter((e) => !rm.has(e.id));
        markDownstreamDirty(next, affected, 'edge_disconnected');
        pushUndo(prev);
        current = next;
        emit();
        return { ok: true, snapshot: getSnapshot() };
      }

      case 'SPLICE_NODE_ON_EDGE': {
        const edge = next.edges.find((e) => e.id === action.edgeId);
        const midNode = next.nodes.find((n) => n.id === action.nodeId);
        if (!edge || !midNode) return { ok: false, error: 'Edge or node not found for splice.' };
        if (!midNode.inputs.length || !midNode.outputs.length) {
          return { ok: false, error: 'Node must have at least one input and one output to splice.' };
        }
        const inPin = midNode.inputs.find((p) => isPortTypeCompatible(edge.dataType, p.dataType));
        const outPin = midNode.outputs.find((p) => {
          const dst = next.nodes.find((n) => n.id === edge.toNode);
          const dstPin = dst?.inputs.find((dp) => dp.id === edge.toPort);
          return dstPin && isPortTypeCompatible(p.dataType, dstPin.dataType);
        });
        if (!inPin || !outPin) return { ok: false, error: 'Node ports are incompatible with target wire.' };

        next.edges = next.edges.filter((e) => e.id !== edge.id);
        next.edges.push({
          id: nextUniqueId(next.edges, 'edge'),
          fromNode: edge.fromNode,
          fromPort: edge.fromPort,
          toNode: midNode.id,
          toPort: inPin.id,
          dataType: edge.dataType,
        });
        next.edges.push({
          id: nextUniqueId(next.edges, 'edge'),
          fromNode: midNode.id,
          fromPort: outPin.id,
          toNode: edge.toNode,
          toPort: edge.toPort,
          dataType: outPin.dataType,
        });
        markDownstreamDirty(next, [midNode.id], 'spliced');
        pushUndo(prev);
        current = next;
        emit();
        return { ok: true, snapshot: getSnapshot() };
      }

      case 'SET_PARAM': {
        const node = next.nodes.find((n) => n.id === action.nodeId);
        if (!node) return { ok: false, error: 'Node not found.' };
        if (node.flags.locked && action.key !== 'title') {
          return { ok: false, error: `Node "${node.title}" is locked (L). Unlock before editing.` };
        }
        node.parms = { ...node.parms, [action.key]: action.value };
        if (action.key === 'title') node.title = String(action.value || node.id);
        markDownstreamDirty(next, [node.id], `param:${action.key}`);
        pushUndo(prev);
            node.legacyType = action.nodeType || spec.type;
        node.inputs = (sshot() };
      }

      case 'SET_NODE_TYPE': {
        const node = next.nodes.find((n) => n.id === action.nodeId);
        if (!node) return { ok: false, error: 'Node not found.' };
        if (node.flags.locked) {
          return { ok: false, error: `Node "${node.title}" is locked (L). Unlock before changing type.` };
        }
        const spec = getOperatorSpec(action.nodeType || 'scene');
        node.type = spec.type;
        node.legacyType = action.nodeType || spec.type;
        node.inputs = (spec.inputs || []).map((p) => ({ ...p }));
        node.outputs = (spec.outputs || []).map((p) => ({ ...p }));
        node.parms = defaultParmsForSpec(spec, { ...(node.parms || {}), title: node.title });
        markDownstreamDirty(next, [node.id], 'type_changed');
        pushUndo(prev);
        current = next;
        emit();
        return { ok: true, snapshot: getSnapshot() };
      }

      case 'TOGGLE_FLAG': {
        const node = next.nodes.find((n) => n.id === action.nodeId);
        if (!node) return { ok: false, error: 'Node not found.' };
        const flag = action.flag;
        if (!['bypass', 'display', 'template', 'locked'].includes(flag)) {
          return { ok: false, error: `Unknown flag: ${flag}` };
        }
        const nextVal = action.value !== undefined ? Boolean(action.value) : !node.flags[flag];
        if (flag === 'display' && nextVal) {
          // Single active display flag per subnet level (Houdini R flag semantics)
          for (const other of next.nodes) {
            if ((other.parentSubnetId ?? null) === (node.parentSubnetId ?? null)) {
              other.flags.display = other.id === node.id;
            }
          }
        } else {
          node.flags[flag] = nextVal;
        }
        if (flag === 'bypass') {
          markDownstreamDirty(next, [node.id], 'flag:bypass');
        }
        pushUndo(prev);
        current = next;
        emit();
        return { ok: true, snapshot: getSnapshot() };
      }

      case 'GROUP_NETWORK_BOX': {
        const ids = Array.from(new Set(action.nodeIds || [])).filter((id) =>
          next.nodes.some((n) => n.id === id)
        );
        if (!ids.length) return { ok: false, error: 'Select nodes to group into a Network Box.' };
        const box = {
          id: nextUniqueId(next.networkBoxes, 'box'),
          label: action.label || `Group ${next.networkBoxes.length + 1}`,
          color: action.color || 'amber',
          parentSubnetId: next.subnetId ?? null,
          nodeIds: ids,
        };
        next.networkBoxes.push(box);
        pushUndo(prev);
        current = next;
        emit();
        return { ok: true, boxId: box.id, snapshot: getSnapshot() };
      }

      case 'CREATE_SUBNET': {
        const ids = new Set(action.nodeIds || []);
        const targets = next.nodes.filter((n) => ids.has(n.id));
        if (!targets.length) return { ok: false, error: 'Select nodes to collapse into a Subnet.' };
        const avgX = Math.round(targets.reduce((acc, n) => acc + n.x, 0) / targets.length);
        const avgY = Math.round(targets.reduce((acc, n) => acc + n.y, 0) / targets.length);
        const spec = OPERATOR_SPECS.subnet;
        const subnetId = nextUniqueId(next.nodes, 'subnet');
        const subnetNode = {
          id: subnetId,
          type: 'subnet',
          legacyType: 'subnet',
          title: action.label || `Subnet ${next.nodes.length + 1}`,
          x: avgX,
          y: avgY,
          parentSubnetId: next.subnetId ?? null,
          inputs: spec.inputs.map((p) => ({ ...p })),
          outputs: spec.outputs.map((p) => ({ ...p })),
          parms: defaultParmsForSpec(spec, { title: action.label || 'Subnet' }),
          flags: cloneFlags(),
          eval: cloneEval({ status: 'dirty', dirtyReason: 'subnet_created' }),
        };
        for (const t of targets) {
          t.parentSubnetId = subnetId;
        }
        // Re-route boundary crossing wires onto subnet ports
        next.edges = next.edges.map((e) => {
          const fromIn = ids.has(e.fromNode);
          const toIn = ids.has(e.toNode);
          if (!fromIn && toIn) {
            return { ...e, toNode: subnetId, toPort: 'in' };
          }
          if (fromIn && !toIn) {
            return { ...e, fromNode: subnetId, fromPort: 'out' };
          }
          return e;
        });
        next.nodes.push(subnetNode);
        pushUndo(prev);
        current = next;
        emit();
        return { ok: true, subnetId, snapshot: getSnapshot() };
      }

      case 'APPLY_DAG_LAYOUT': {
        const posMap = computeDagLayout(next, { parentSubnetId: action.subnetId ?? next.subnetId ?? null });
        for (const n of next.nodes) {
          if (posMap[n.id]) {
            n.x = posMap[n.id].x;
            n.y = posMap[n.id].y;
          }
        }
        pushUndo(prev);
        current = next;
        emit();
        return { ok: true, snapshot: getSnapshot() };
      }

      default:
        return { ok: false, error: `Unknown graph action: ${action.type}` };
    }
  }

  return {
    getSnapshot,
    dispatch,
    canUndo: () => undoStack.length > 0,
    canRedo: () => redoStack.length > 0,
    subscribe(fn) {
      listeners.add(fn);
      return () => listeners.delete(fn);
    },
  };
}
