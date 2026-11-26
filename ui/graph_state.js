/* Noir Fiction Studio v2 — Pure Headless Graph State & Topology Helpers (ZERO DOM / Canvas / Network) */

import { matchSpeakerToJunction } from './splitter.js';

export function getGraphData(state) {
  const nodes = state?.graphDraft?.nodes ?? state?.episodeState?.nodes ?? [];
  const edges = state?.graphDraft?.edges ?? state?.episodeState?.connections ?? [];
  return {
    nodes: Array.isArray(nodes) ? nodes : [],
    edges: Array.isArray(edges) ? edges : [],
  };
}

export function blocksForCharacter(state, characterId, junctions = []) {
  const blocks = state?.draftBlocks || state?.episodeState?.notebook?.blocks || [];
  const matches = [];
  let currentScene = 'Opening';
  blocks.forEach((block, index) => {
    if (!block) return;
    if (block.kind === 'scene-heading') {
      const heading = String(block.text || '').trim().split(/\r?\n/)[0].replace(/^#+\s*/, '').trim();
      if (heading) currentScene = heading.slice(0, 32);
      return;
    }
    if (block.kind !== 'character' || !block.speaker) return;
    const direct = String(block.speaker).toLowerCase() === String(characterId || '').toLowerCase();
    const resolved = direct ? { character_id: characterId } : matchSpeakerToJunction(block.speaker, junctions);
    if (resolved && String(resolved.character_id).toLowerCase() === String(characterId || '').toLowerCase()) {
      matches.push({ index, block, sceneLabel: currentScene });
    }
  });
  return matches;
}

export function filterJunctions(junctions = [], filterText = '') {
  const list = Array.isArray(junctions) ? junctions : [];
  const filter = String(filterText || '').trim().toLowerCase();
  if (!filter) return list;
  return list.filter((j) =>
    String(j.label || j.character_id || '').toLowerCase().includes(filter) ||
    (j.forms || []).some((f) => String(f.display_label || f.label || f.id || '').toLowerCase().includes(filter))
  );
}

export function resolveActiveJunction(junctions = [], filteredJunctions = [], selectedProfile = null, graphSelection = null) {
  const fallback = filteredJunctions[0]?.character_id || junctions[0]?.character_id || '';
  const activeCharId = selectedProfile?.character || graphSelection?.characterId || fallback;
  return junctions.find((j) => j.character_id === activeCharId) || filteredJunctions[0] || null;
}

export function nextNodeId(nodes = []) {
  const taken = new Set((nodes || []).map((n) => String(n.id)));
  let idx = (nodes || []).length + 1;
  while (taken.has(`node_${idx}`)) idx += 1;
  return `node_${idx}`;
}

export function applyNodePosition(graph, nodeId, pos) {
  const nodes = Array.isArray(graph?.nodes) ? graph.nodes : [];
  const edges = Array.isArray(graph?.edges) ? graph.edges : [];
  if (!nodeId || !pos || !Number.isFinite(Number(pos.x)) || !Number.isFinite(Number(pos.y))) {
    return { nodes: [...nodes], edges: [...edges] };
  }
  const rx = Math.round(Number(pos.x));
  const ry = Math.round(Number(pos.y));
  const nextNodes = nodes.map((n) => (n.id === nodeId ? { ...n, x: rx, y: ry } : n));
  return { nodes: nextNodes, edges: [...edges] };
}

export function applyAllNodePositions(graph, positionMap = {}) {
  const nodes = Array.isArray(graph?.nodes) ? graph.nodes : [];
  const edges = Array.isArray(graph?.edges) ? graph.edges : [];
  const nextNodes = nodes.map((n) => {
    const pos = positionMap[n.id];
    if (!pos || !Number.isFinite(Number(pos.x)) || !Number.isFinite(Number(pos.y))) return n;
    return { ...n, x: Math.round(Number(pos.x)), y: Math.round(Number(pos.y)) };
  });
  return { nodes: nextNodes, edges: [...edges] };
}

export function addStoryNode(graph, coords = null) {
  const nodes = Array.isArray(graph?.nodes) ? graph.nodes : [];
  const edges = Array.isArray(graph?.edges) ? graph.edges : [];
  const id = nextNodeId(nodes);
  const index = nodes.length;
  const x = Number.isFinite(Number(coords?.x))
    ? Math.round(Number(coords.x))
    : 120 + (index % 4) * 210;
  const y = Number.isFinite(Number(coords?.y))
    ? Math.round(Number(coords.y))
    : 110 + Math.floor(index / 4) * 110;
  const node = {
    id,
    title: `Scene ${index + 1}`,
    type: 'scene',
    x,
    y,
  };
  return {
    node,
    graph: {
      nodes: [...nodes, node],
      edges: [...edges],
    },
  };
}

export function updateStoryNode(graph, nodeId, { title, type }) {
  const nodes = Array.isArray(graph?.nodes) ? graph.nodes : [];
  const edges = Array.isArray(graph?.edges) ? graph.edges : [];
  const nextNodes = nodes.map((n) =>
    n.id === nodeId
      ? { ...n, title: title || n.title || nodeId, type: type || n.type || 'episode' }
      : n
  );
  return { nodes: nextNodes, edges: [...edges] };
}

export function removeStoryNode(graph, nodeId) {
  const nodes = (Array.isArray(graph?.nodes) ? graph.nodes : []).filter((n) => n.id !== nodeId);
  const edges = (Array.isArray(graph?.edges) ? graph.edges : []).filter((e) => e.from !== nodeId && e.to !== nodeId);
  return { nodes, edges };
}

export function wouldCreateCycle(edges = [], from, to) {
  if (!from || !to) return false;
  if (from === to) return true;
  const adj = new Map();
  for (const e of edges) {
    if (!e?.from || !e?.to) continue;
    if (!adj.has(e.from)) adj.set(e.from, []);
    adj.get(e.from).push(e.to);
  }
  const visited = new Set([to]);
  const stack = [to];
  while (stack.length) {
    const cur = stack.pop();
    if (cur === from) return true;
    for (const nxt of adj.get(cur) || []) {
      if (!visited.has(nxt)) {
        visited.add(nxt);
        stack.push(nxt);
      }
    }
  }
  return false;
}

export function addStoryEdge(graph, from, to) {
  const nodes = Array.isArray(graph?.nodes) ? graph.nodes : [];
  const edges = Array.isArray(graph?.edges) ? graph.edges : [];
  if (!from || !to || from === to) {
    return { ok: false, error: 'Source and target nodes must differ.', graph: { nodes: [...nodes], edges: [...edges] } };
  }
  const nodeIds = new Set(nodes.map((n) => n.id));
  if (!nodeIds.has(from) || !nodeIds.has(to)) {
    return { ok: false, error: 'Missing endpoint node for edge.', graph: { nodes: [...nodes], edges: [...edges] } };
  }
  if (edges.some((e) => e.from === from && e.to === to)) {
    return { ok: false, error: `Edge ${from} → ${to} already exists.`, graph: { nodes: [...nodes], edges: [...edges] } };
  }
  if (wouldCreateCycle(edges, from, to)) {
    return { ok: false, error: `Rejected cycle: ${from} → ${to} loops back to an ancestor.`, graph: { nodes: [...nodes], edges: [...edges] } };
  }
  return {
    ok: true,
    error: null,
    graph: {
      nodes: [...nodes],
      edges: [...edges, { from, to }],
    },
  };
}

export function removeStoryEdgeAt(graph, index) {
  const nodes = Array.isArray(graph?.nodes) ? graph.nodes : [];
  const edges = (Array.isArray(graph?.edges) ? graph.edges : []).filter((_, i) => i !== index);
  return { nodes: [...nodes], edges };
}

export function buildStoryCyElements(nodes = [], edges = []) {
  const hasPositions = nodes.length > 0 && nodes.every((n) => typeof n.x === 'number' && typeof n.y === 'number');
  const validIds = new Set(nodes.map((n) => n.id));
  const elements = [
    ...nodes.map((n) => ({
      data: {
        id: n.id,
        label: `${n.title || n.id}\n[${n.type || 'node'}]`,
        nodeType: n.type || 'episode',
      },
      ...(typeof n.x === 'number' && typeof n.y === 'number' ? { position: { x: n.x, y: n.y } } : {}),
    })),
    ...edges
      .filter((e) => validIds.has(e.from) && validIds.has(e.to))
      .map((e, idx) => ({
        data: {
          id: `e_${idx}_${e.from}_${e.to}`,
          source: e.from,
          target: e.to,
        },
      })),
  ];
  return { elements, hasPositions };
}

function stackYPositions(count, spacingY = 66) {
  if (count <= 0) return [];
  const start = -((count - 1) * spacingY) / 2;
  return Array.from({ length: count }, (_, i) => Math.round(start + i * spacingY));
}

export function buildCharacterTopology(activeJ, charBlocks = [], options = {}) {
  if (!activeJ) {
    return {
      elements: [],
      totalBlocks: 0,
      visibleBlocks: 0,
      clusterCount: 0,
    };
  }

  const directLimit = Number.isFinite(Number(options.directLimit)) ? Number(options.directLimit) : 12;
  const initialDirect = Number.isFinite(Number(options.initialDirect)) ? Number(options.initialDirect) : 8;
  const clusterSize = Number.isFinite(Number(options.clusterSize)) ? Number(options.clusterSize) : 10;
  const expanded = new Set(options.expandedClusters || []);

  const forms = Array.isArray(activeJ.forms) ? activeJ.forms : [];
  const formYs = stackYPositions(forms.length, 68);

  const elements = [
    {
      data: {
        id: `char:${activeJ.character_id}`,
        label: `${activeJ.label || activeJ.character_id}\n(${charBlocks.length} blocks)`,
        kind: 'junction',
      },
      position: { x: 0, y: 0 },
    },
    ...forms.map((f, idx) => ({
      data: {
        id: `form:${f.id}`,
        label: `${f.display_label || f.label || f.id}\n[${f.status || 'active'}]`,
        kind: 'form',
        formId: f.id,
        nodeId: f.port_id || activeJ.junction_id,
      },
      position: { x: -245, y: formYs[idx] ?? 0 },
    })),
    ...forms.map((f, idx) => ({
      data: {
        id: `edge:form:${idx}:${f.id}`,
        source: `form:${f.id}`,
        target: `char:${activeJ.character_id}`,
        kind: 'form-edge',
      },
    })),
    // Left-of-form input sockets (x = -485): Digital Minds, Super Characters, and Episode Chronology Gates
    ...forms.flatMap((f, idx) => {
      const y = formYs[idx] ?? 0;
      const out = [];
      if (f.link) {
        const sid = `socket:mind:${f.id}`;
        out.push({
          data: { id: sid, label: `${f.link.kind === 'digital_mind' ? '🧠 Mind' : '★ Super'}: ${f.link.node_id}`, kind: 'mind_socket' },
          position: { x: -485, y: y - 14 },
        });
        out.push({
          data: { id: `edge:socket:mind:${f.id}`, source: sid, target: `form:${f.id}`, kind: 'socket-edge' },
        });
      }
      if (f.unlock_episode || Number(f.unlock_pos || 0) > 0) {
        const lid = `socket:gate:${f.id}`;
        out.push({
          data: { id: lid, label: `🔒 Gate: ${f.unlock_episode || 'pos'} (${f.unlock_pos || 0})`, kind: 'law_socket' },
          position: { x: -485, y: y + (f.link ? 22 : 0) },
        });
        out.push({
          data: { id: `edge:socket:gate:${f.id}`, source: lid, target: `form:${f.id}`, kind: 'socket-edge' },
        });
      }
      return out;
    }),
    // Inter-character Relationship Controller nodes above the character hub
    ...Object.entries(activeJ.relationship_overrides || {}).flatMap(([targetId], rIdx) => {
      const rid = `rel:${activeJ.character_id}:${targetId}`;
      return [
        {
          data: { id: rid, label: `🔗 Rel: ${targetId}`, kind: 'relationship' },
          position: { x: (rIdx - 0.5) * 140, y: -125 },
        },
        {
          data: { id: `edge:rel:${activeJ.character_id}:${targetId}`, source: rid, target: `char:${activeJ.character_id}`, kind: 'relationship-edge' },
        },
      ];
    }),
  ];

  // Build visible block items and overflow clusters so ZERO blocks are silently dropped.
  const rightItems = [];
  if (charBlocks.length <= directLimit) {
    for (const entry of charBlocks) {
      rightItems.push({ kind: 'block', entry });
    }
  } else {
    for (const entry of charBlocks.slice(0, initialDirect)) {
      rightItems.push({ kind: 'block', entry });
    }
    const overflow = charBlocks.slice(initialDirect);
    for (let i = 0; i < overflow.length; i += clusterSize) {
      const slice = overflow.slice(i, i + clusterSize);
      const firstNum = slice[0].index + 1;
      const lastNum = slice[slice.length - 1].index + 1;
      const clusterId = `cluster:${activeJ.character_id}:${i}`;
      if (expanded.has(clusterId)) {
        rightItems.push({
          kind: 'cluster_header',
          clusterId,
          label: `Collapse #${firstNum}–#${lastNum}\n(${slice.length} blocks)`,
        });
        for (const entry of slice) {
          rightItems.push({ kind: 'block', entry });
        }
      } else {
        rightItems.push({
          kind: 'block_cluster',
          clusterId,
          slice,
          label: `+${slice.length} blocks (#${firstNum}–#${lastNum})\n${slice[0].sceneLabel || 'Tap to expand'}`,
        });
      }
    }
  }

  // Lay right-side items out into 1 or 2 tidy deterministic columns to keep aspect ratio readable.
  const colSplit = rightItems.length > 14 ? Math.ceil(rightItems.length / 2) : rightItems.length;
  const col0Ys = stackYPositions(colSplit, 60);
  const col1Ys = stackYPositions(rightItems.length - colSplit, 60);

  let visibleBlocks = 0;
  let clusterCount = 0;

  rightItems.forEach((item, idx) => {
    const col = idx < colSplit ? 0 : 1;
    const row = col === 0 ? idx : idx - colSplit;
    const x = col === 0 ? 250 : 455;
    const y = (col === 0 ? col0Ys[row] : col1Ys[row]) ?? 0;

    if (item.kind === 'block') {
      const { index, block } = item.entry;
      visibleBlocks += 1;
      const preview = String(block.text || '').trim().replace(/\s+/g, ' ').slice(0, 26);
      elements.push({
        data: {
          id: `blk:${block.id || index}`,
          label: `#${index + 1} ${preview}`,
          kind: 'block',
          blockId: block.id || '',
        },
        position: { x, y },
      });
      elements.push({
        data: {
          id: `edge:blk:${index}:${block.id || idx}`,
          source: `char:${activeJ.character_id}`,
          target: `blk:${block.id || index}`,
          kind: 'block-edge',
        },
      });
    } else if (item.kind === 'block_cluster' || item.kind === 'cluster_header') {
      clusterCount += 1;
      elements.push({
        data: {
          id: item.clusterId,
          label: item.label,
          kind: 'block_cluster',
          clusterId: item.clusterId,
        },
        position: { x, y },
      });
      elements.push({
        data: {
          id: `edge:cluster:${idx}:${item.clusterId}`,
          source: `char:${activeJ.character_id}`,
          target: item.clusterId,
          kind: 'cluster-edge',
        },
      });
    }
  });

  return {
    elements,
    totalBlocks: charBlocks.length,
    visibleBlocks,
    clusterCount,
  };
}
