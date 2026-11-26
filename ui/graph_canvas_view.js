/* Noir Fiction Studio v2 — G3/G4 Houdini-Style Canvas2D Network View (Layer 3: Pure Presentation & Hit-Testing; ZERO Direct State Mutation) */

import { PORT_TYPES, getOperatorSpec, isPortTypeCompatible } from './graph_engine.js';
import { playPortSnap, playWireCut } from './sound.js';

const NODE_W = 216;
const HEADER_H = 26;
const PORT_ROW_H = 20;
const FOOTER_H = 24;
const PORT_RADIUS = 5.5;
const FLAG_W = 18;
const FLAG_H = 15;
const FLAG_GAP = 4;
const MINIMAP_W = 152;
const MINIMAP_H = 94;
const MINIMAP_PAD = 12;

const CATEGORY_COLORS = {
  Story: '#ffb07d',
  Cast: '#90e9cd',
  Mind: '#b4a7e5',
  Modifiers: '#a78bfa',
  Constraints: '#f87171',
  Output: '#7ad1b8',
};

function clamp(v, lo, hi) {
  return Math.max(lo, Math.min(hi, v));
}

function readThemePalette() {
  const cs = getComputedStyle(document.body);
  const pick = (name, fallback) => cs.getPropertyValue(name).trim() || fallback;
  return {
    bg: pick('--surface-chrome', '#111719'),
    cardBg: pick('--surface-chrome-elevated', '#171c1d'),
    cardHoverBg: pick('--surface-chrome-hover', '#21282a'),
    border: pick('--border-chrome', '#2b3437'),
    ink: pick('--ink-on-chrome', '#f1e8d9'),
    inkMuted: pick('--ink-muted-on-chrome', '#b6b1aa'),
    stripe: pick('--stripe-chrome', '#f2a65e'),
    accent: pick('--accent-primary-strong', '#f2a65e'),
    accentSoft: pick('--accent-primary', '#ffb07d'),
    secondary: pick('--accent-secondary', '#90e9cd'),
    focus: pick('--focus-ring', '#90e9cd'),
    errInk: pick('--status-err-ink', '#f87171'),
  };
}

export function getNodeGeometry(node, dragPos = null) {
  const x = dragPos ? dragPos.x : node.x;
  const y = dragPos ? dragPos.y : node.y;
  const inputs = node.inputs || [];
  const outputs = node.outputs || [];
  const rows = Math.max(1, inputs.length, outputs.length);
  const h = HEADER_H + rows * PORT_ROW_H + FOOTER_H;

  const inPins = inputs.map((p, idx) => ({
    ...p,
    index: idx,
    cx: x,
    cy: y + HEADER_H + idx * PORT_ROW_H + PORT_ROW_H / 2,
  }));
  const outPins = outputs.map((p, idx) => ({
    ...p,
    index: idx,
    cx: x + NODE_W,
    cy: y + HEADER_H + idx * PORT_ROW_H + PORT_ROW_H / 2,
  }));

  // Corner B / R / L flags aligned right inside header
  const flagsRight = x + NODE_W - 8;
  const flagY = y + Math.round((HEADER_H - FLAG_H) / 2);
  const flagRects = {
    locked: { x: flagsRight - FLAG_W, y: flagY, w: FLAG_W, h: FLAG_H, flag: 'locked', label: 'L' },
    display: { x: flagsRight - FLAG_W * 2 - FLAG_GAP, y: flagY, w: FLAG_W, h: FLAG_H, flag: 'display', label: 'R' },
    bypass: { x: flagsRight - FLAG_W * 3 - FLAG_GAP * 2, y: flagY, w: FLAG_W, h: FLAG_H, flag: 'bypass', label: 'B' },
  };

  return { x, y, w: NODE_W, h, inPins, outPins, flagRects };
}

function cubicPoint(p0, p1, p2, p3, t) {
  const u = 1 - t;
  const tt = t * t;
  const uu = u * u;
  const uuu = uu * u;
  const ttt = tt * t;
  return {
    x: uuu * p0.x + 3 * uu * t * p1.x + 3 * u * tt * p2.x + ttt * p3.x,
    y: uuu * p0.y + 3 * uu * t * p1.y + 3 * u * tt * p2.y + ttt * p3.y,
  };
}

function computeWireBezier(x1, y1, x2, y2) {
  const dx = Math.max(46, Math.min(180, Math.abs(x2 - x1) * 0.48));
  return [
    { x: x1, y: y1 },
    { x: x1 + dx, y: y1 },
    { x: x2 - dx, y: y2 },
    { x: x2, y: y2 },
  ];
}

function distToSegmentSq(px, py, ax, ay, bx, by) {
  const vx = bx - ax;
  const vy = by - ay;
  const wx = px - ax;
  const wy = py - ay;
  const c1 = vx * wx + vy * wy;
  if (c1 <= 0) return wx * wx + wy * wy;
  const c2 = vx * vx + vy * vy;
  if (c2 <= c1) {
    const dx = px - bx;
    const dy = py - by;
    return dx * dx + dy * dy;
  }
  const b = c1 / c2;
  const qx = ax + b * vx;
  const qy = ay + b * vy;
  const dx = px - qx;
  const dy = py - qy;
  return dx * dx + dy * dy;
}

function roundRectPath(ctx, x, y, w, h, r) {
  const rr = Math.min(r, w / 2, h / 2);
  ctx.beginPath();
  ctx.moveTo(x + rr, y);
  ctx.lineTo(x + w - rr, y);
  ctx.quadraticCurveTo(x + w, y, x + w, y + rr);
  ctx.lineTo(x + w, y + h - rr);
  ctx.quadraticCurveTo(x + w, y + h, x + w - rr, y + h);
  ctx.lineTo(x + rr, y + h);
  ctx.quadraticCurveTo(x, y + h, x, y + h - rr);
  ctx.lineTo(x, y + rr);
  ctx.quadraticCurveTo(x, y, x + rr, y);
  ctx.closePath();
}

function pickTelemetryBar(node) {
  const p = node.parms || {};
  if (typeof p.influence === 'number') return { label: 'INF', ratio: clamp(p.influence, 0, 1), display: `${Math.round(p.influence * 100)}%` };
  if (typeof p.tension === 'number') return { label: 'TEN', ratio: clamp(p.tension, 0, 1), display: `${Math.round(p.tension * 100)}%` };
  if (typeof p.voice_arch === 'number') return { label: 'VOI', ratio: clamp(p.voice_arch, 0, 1), display: `${Math.round(p.voice_arch * 100)}%` };
  if (typeof p.protected_pct === 'number') return { label: 'PRT', ratio: clamp(p.protected_pct / 100, 0, 1), display: `${Math.round(p.protected_pct)}%` };
  if (typeof p.word_target === 'number') return { label: 'TGT', ratio: clamp(p.word_target / 5000, 0, 1), display: `${p.word_target}w` };
  if (typeof p.forms_count === 'number') return { label: 'FRM', ratio: clamp(p.forms_count / 8, 0, 1), display: `${Math.round(p.forms_count)}F` };
  if (typeof p.pause_sec === 'number') return { label: 'PSE', ratio: clamp(p.pause_sec / 10, 0, 1), display: `${p.pause_sec}s` };
  return null;
}

export function mountHoudiniCanvasView({
  canvas,
  initialModel,
  savedCamera = null,
  onSelectNode,
  onSelectEdge,
  onMoveNode,
  onToggleFlag,
  onConnectPorts,
  onSpliceNodeOnEdge,
  onCutEdges,
  onRequestTabMenu,
  onDuplicateNode,
  onEnterSubnet,
  onCameraChange,
  onHoverHint,
}) {
  const ctx = canvas.getContext('2d');
  let viewModel = initialModel || { snapshot: { subnetId: null, nodes: [], edges: [], networkBoxes: [] }, selectedNodeId: '', selectedEdgeId: '' };
  let palette = readThemePalette();

  let width = 640;
  let height = 480;
  let dpr = window.devicePixelRatio || 1;
  let camera = savedCamera && Number.isFinite(savedCamera.zoom)
    ? { panX: savedCamera.panX, panY: savedCamera.panY, zoom: savedCamera.zoom }
    : { panX: 60, panY: 60, zoom: 1 };

  let needsRedraw = true;
  let rafId = 0;
  let destroyed = false;

  // Ephemeral UI interaction state only (never mutates kernel snapshot directly)
  const dragOverrides = new Map();
  const multiSelectedIds = new Set();
  let hoveredHit = null;
  let pointerState = null;
  let spaceHeld = false;
  let yHeld = false;
  let spliceTargetEdgeId = '';
  let hasAutoFitOnce = Boolean(savedCamera && Number.isFinite(savedCamera.zoom));
  let cachedMinimap = null;

  function scheduleDraw() {
    needsRedraw = true;
    if (!rafId && !destroyed) {
      rafId = requestAnimationFrame(renderFrame);
    }
  }

  function refreshTheme() {
    palette = readThemePalette();
    scheduleDraw();
  }

  function screenToWorld(sx, sy) {
    return {
      x: (sx - camera.panX) / camera.zoom,
      y: (sy - camera.panY) / camera.zoom,
    };
  }

  function worldToScreen(wx, wy) {
    return {
      x: wx * camera.zoom + camera.panX,
      y: wy * camera.zoom + camera.panY,
    };
  }

  function scopedNodes() {
    const sub = viewModel.snapshot?.subnetId ?? null;
    return (viewModel.snapshot?.nodes || []).filter((n) => (n.parentSubnetId ?? null) === sub);
  }

  function scopedEdges(nodes) {
    const ids = new Set(nodes.map((n) => n.id));
    return (viewModel.snapshot?.edges || []).filter((e) => ids.has(e.fromNode) && ids.has(e.toNode));
  }

  function fitBounds(targetNodes, padding = 52) {
    if (!targetNodes.length || width < 40 || height < 40) return;
    let minX = Infinity;
    let minY = Infinity;
    let maxX = -Infinity;
    let maxY = -Infinity;
    for (const n of targetNodes) {
      const g = getNodeGeometry(n, dragOverrides.get(n.id));
      minX = Math.min(minX, g.x);
      minY = Math.min(minY, g.y);
      maxX = Math.max(maxX, g.x + g.w);
      maxY = Math.max(maxY, g.y + g.h);
    }
    const bw = Math.max(120, maxX - minX);
    const bh = Math.max(90, maxY - minY);
    const nextZoom = clamp(Math.min((width - padding * 2) / bw, (height - padding * 2) / bh), 0.25, 1.35);
    camera = {
      zoom: nextZoom,
      panX: Math.round((width - bw * nextZoom) / 2 - minX * nextZoom),
      panY: Math.round((height - bh * nextZoom) / 2 - minY * nextZoom),
    };
    hasAutoFitOnce = true;
    onCameraChange?.({ ...camera });
    scheduleDraw();
  }

  function fitAll() {
    fitBounds(scopedNodes(), 56);
  }

  function frameSelected() {
    const nodes = scopedNodes();
    const sel = nodes.filter((n) => n.id === viewModel.selectedNodeId);
    fitBounds(sel.length ? sel : nodes, 70);
  }

  function getViewportCenterWorld() {
    return screenToWorld(width / 2, height / 2);
  }

  function buildGeometryMap(nodes) {
    const geomMap = new Map();
    for (const n of nodes) {
      geomMap.set(n.id, getNodeGeometry(n, dragOverrides.get(n.id)));
    }
    return geomMap;
  }

  function resolveEdgeEndpoints(edge, geomMap) {
    const srcG = geomMap.get(edge.fromNode);
    const dstG = geomMap.get(edge.toNode);
    if (!srcG || !dstG) return null;
    const outPin = srcG.outPins.find((p) => p.id === edge.fromPort) || srcG.outPins[0];
    const inPin = dstG.inPins.find((p) => p.id === edge.toPort) || dstG.inPins[0];
    if (!outPin || !inPin) return null;
    return {
      x1: outPin.cx,
      y1: outPin.cy,
      x2: inPin.cx,
      y2: inPin.cy,
      dataType: edge.dataType || outPin.dataType || 'ANY',
    };
  }

  function hitTest(sx, sy) {
    // 1. Check Mini-Map radar rectangle in bottom-right corner
    if (cachedMinimap && sx >= cachedMinimap.x && sx <= cachedMinimap.x + cachedMinimap.w && sy >= cachedMinimap.y && sy <= cachedMinimap.y + cachedMinimap.h) {
      return { kind: 'minimap', minimap: cachedMinimap, sx, sy };
    }

    const { x: wx, y: wy } = screenToWorld(sx, sy);
    const nodes = scopedNodes();
    const geomMap = buildGeometryMap(nodes);

    // 2. Check nodes front-to-back (selected/last rendered first)
    for (let i = nodes.length - 1; i >= 0; i -= 1) {
      const n = nodes[i];
      const g = geomMap.get(n.id);

      // Port hit tests (generous radius scaled lightly)
      const pinHitR = Math.max(9, PORT_RADIUS + 4);
      for (const p of g.outPins) {
        if ((wx - p.cx) ** 2 + (wy - p.cy) ** 2 <= pinHitR ** 2) {
          return { kind: 'port_out', nodeId: n.id, portId: p.id, port: p };
        }
      }
      for (const p of g.inPins) {
        if ((wx - p.cx) ** 2 + (wy - p.cy) ** 2 <= pinHitR ** 2) {
          return { kind: 'port_in', nodeId: n.id, portId: p.id, port: p };
        }
      }

      // Header flags (when zoomed in enough to show crisp flags)
      if (camera.zoom >= 0.48) {
        for (const key of ['bypass', 'display', 'locked']) {
          const r = g.flagRects[key];
          if (wx >= r.x && wx <= r.x + r.w && wy >= r.y && wy <= r.y + r.h) {
            return { kind: 'flag', flag: r.flag, nodeId: n.id };
          }
        }
      }

      if (wx >= g.x && wx <= g.x + g.w && wy >= g.y && wy <= g.y + g.h) {
        return { kind: 'node', nodeId: n.id, node: n, geom: g };
      }
    }

    // 3. Check Bezier wires
    const edges = scopedEdges(nodes);
    const tolSq = Math.max(8, 10 / camera.zoom) ** 2;
    for (let i = edges.length - 1; i >= 0; i -= 1) {
      const e = edges[i];
      const ep = resolveEdgeEndpoints(e, geomMap);
      if (!ep) continue;
      const [p0, p1, p2, p3] = computeWireBezier(ep.x1, ep.y1, ep.x2, ep.y2);
      let prev = p0;
      for (let step = 1; step <= 14; step += 1) {
        const pt = cubicPoint(p0, p1, p2, p3, step / 14);
        if (distToSegmentSq(wx, wy, prev.x, prev.y, pt.x, pt.y) <= tolSq) {
          return { kind: 'edge', edgeId: e.id, edge: e };
        }
        prev = pt;
      }
    }

    return { kind: 'canvas' };
  }

  function drawDotGrid(viewLeft, viewTop, viewRight, viewBottom) {
    const step = 25;
    const majorEvery = 5;
    const showMinor = camera.zoom >= 0.45;
    const startX = Math.floor(viewLeft / step) * step;
    const startY = Math.floor(viewTop / step) * step;

    if (showMinor) {
      ctx.fillStyle = 'rgba(255, 244, 228, 0.08)';
      for (let gx = startX; gx <= viewRight; gx += step) {
        for (let gy = startY; gy <= viewBottom; gy += step) {
          if (Math.round(gx / step) % majorEvery === 0 && Math.round(gy / step) % majorEvery === 0) continue;
          ctx.fillRect(gx - 0.7, gy - 0.7, 1.4, 1.4);
        }
      }
    }

    const majorStep = step * majorEvery;
    const mStartX = Math.floor(viewLeft / majorStep) * majorStep;
    const mStartY = Math.floor(viewTop / majorStep) * majorStep;
    ctx.fillStyle = 'rgba(255, 244, 228, 0.22)';
    for (let gx = mStartX; gx <= viewRight; gx += majorStep) {
      for (let gy = mStartY; gy <= viewBottom; gy += majorStep) {
        ctx.fillRect(gx - 1.2, gy - 1.2, 2.4, 2.4);
      }
    }
  }

  function drawNetworkBoxes(geomMap) {
    const sub = viewModel.snapshot?.subnetId ?? null;
    const boxes = (viewModel.snapshot?.networkBoxes || []).filter((b) => (b.parentSubnetId ?? null) === sub);
    for (const box of boxes) {
      let minX = Infinity;
      let minY = Infinity;
      let maxX = -Infinity;
      let maxY = -Infinity;
      for (const nid of box.nodeIds || []) {
        const g = geomMap.get(nid);
        if (!g) continue;
        minX = Math.min(minX, g.x);
        minY = Math.min(minY, g.y);
        maxX = Math.max(maxX, g.x + g.w);
        maxY = Math.max(maxY, g.y + g.h);
      }
      if (!Number.isFinite(minX)) continue;
      const pad = 22;
      const bx = minX - pad;
      const by = minY - pad - 20;
      const bw = maxX - minX + pad * 2;
      const bh = maxY - minY + pad * 2 + 20;

      ctx.save();
      roundRectPath(ctx, bx, by, bw, bh, 10);
      ctx.fillStyle = 'rgba(57, 221, 197, 0.06)';
      ctx.fill();
      ctx.lineWidth = 1.5;
      ctx.strokeStyle = 'rgba(57, 221, 197, 0.35)';
      ctx.stroke();

      ctx.font = '700 11px sans-serif';
      ctx.fillStyle = palette.accent;
      ctx.textBaseline = 'top';
      ctx.fillText(String(box.label || 'GROUP').toUpperCase(), bx + 10, by + 6);
      ctx.restore();
    }
  }

  function drawEdges(edges, nodesById, geomMap, viewRect) {
    const simplified = camera.zoom < 0.45;
    for (const edge of edges) {
      const ep = resolveEdgeEndpoints(edge, geomMap);
      if (!ep) continue;

      const minX = Math.min(ep.x1, ep.x2) - 60;
      const maxX = Math.max(ep.x1, ep.x2) + 60;
      const minY = Math.min(ep.y1, ep.y2) - 40;
      const maxY = Math.max(ep.y1, ep.y2) + 40;
      if (maxX < viewRect.left || minX > viewRect.right || maxY < viewRect.top || minY > viewRect.bottom) {
        continue;
      }

      const srcNode = nodesById.get(edge.fromNode);
      const bypassed = Boolean(srcNode?.flags?.bypass);
      const isSelected = viewModel.selectedEdgeId === edge.id;
      const isHovered = hoveredHit?.kind === 'edge' && hoveredHit.edgeId === edge.id;
      const isConnectedToSelected =
        viewModel.selectedNodeId &&
        (edge.fromNode === viewModel.selectedNodeId || edge.toNode === viewModel.selectedNodeId);

      const portMeta = PORT_TYPES[ep.dataType] || PORT_TYPES.ANY;
      const wireColor = portMeta.fallbackColor;
      const [p0, p1, p2, p3] = computeWireBezier(ep.x1, ep.y1, ep.x2, ep.y2);

      ctx.save();
      if (bypassed) {
        ctx.globalAlpha = 0.45;
        ctx.setLineDash([6, 5]);
      }

      // Soft dark casing behind wire for readability on crossings
      if (!simplified) {
        ctx.beginPath();
        ctx.moveTo(p0.x, p0.y);
        ctx.bezierCurveTo(p1.x, p1.y, p2.x, p2.y, p3.x, p3.y);
        ctx.lineWidth = isSelected || isHovered ? 8 : 5;
        ctx.strokeStyle = 'rgba(8, 10, 12, 0.72)';
        ctx.stroke();
      }

      ctx.beginPath();
      ctx.moveTo(p0.x, p0.y);
      ctx.bezierCurveTo(p1.x, p1.y, p2.x, p2.y, p3.x, p3.y);
      ctx.lineWidth = isSelected ? 3.8 : isHovered || isConnectedToSelected ? 3.2 : 2.3;
      ctx.strokeStyle = isSelected || isHovered ? palette.secondary : wireColor;
      ctx.stroke();

      // Mid-wire directional chevron
      if (!simplified) {
        const mid = cubicPoint(p0, p1, p2, p3, 0.5);
        const midNext = cubicPoint(p0, p1, p2, p3, 0.53);
        const angle = Math.atan2(midNext.y - mid.y, midNext.x - mid.x);
        ctx.setLineDash([]);
        ctx.translate(mid.x, mid.y);
        ctx.rotate(angle);
        ctx.beginPath();
        ctx.moveTo(6, 0);
        ctx.lineTo(-4, -4.5);
        ctx.lineTo(-4, 4.5);
        ctx.closePath();
        ctx.fillStyle = isSelected || isHovered ? palette.secondary : wireColor;
        ctx.fill();
      }
      ctx.restore();
    }
  }

  function drawNode(node, geom, viewRect) {
    if (
      geom.x + geom.w < viewRect.left ||
      geom.x > viewRect.right ||
      geom.y + geom.h < viewRect.top ||
      geom.y > viewRect.bottom
    ) {
      return;
    }

    const spec = getOperatorSpec(node.type);
    const catColor = CATEGORY_COLORS[spec.category] || palette.stripe;
    const isSelected = viewModel.selectedNodeId === node.id;
    const isHovered = hoveredHit?.kind === 'node' && hoveredHit.nodeId === node.id;
    const isDisplay = Boolean(node.flags?.display);
    const isBypass = Boolean(node.flags?.bypass);
    const isLocked = Boolean(node.flags?.locked);
    const isDirty = node.eval?.status === 'dirty';
    const isError = node.eval?.status === 'error';
    const simplified = camera.zoom < 0.48;

    ctx.save();
    if (isBypass) ctx.globalAlpha = 0.62;

    // Halo glow for Display (R), Selected, or Error
    if (isSelected || isDisplay || isError) {
      ctx.save();
      roundRectPath(ctx, geom.x - 3, geom.y - 3, geom.w + 6, geom.h + 6, 11);
      ctx.lineWidth = isSelected ? 3 : 2;
      ctx.strokeStyle = isError ? palette.errInk : isSelected ? palette.focus : palette.accent;
      ctx.stroke();
      ctx.restore();
    }

    // Card base
    roundRectPath(ctx, geom.x, geom.y, geom.w, geom.h, 8);
    ctx.fillStyle = isHovered ? palette.cardHoverBg : palette.cardBg;
    ctx.fill();
    ctx.lineWidth = isSelected ? 2.2 : 1.3;
    ctx.strokeStyle = isSelected ? palette.focus : isDirty ? palette.stripe : palette.border;
    ctx.stroke();

    // Header band (top rounded strip)
    ctx.save();
    ctx.beginPath();
    ctx.rect(geom.x + 1, geom.y + 1, geom.w - 2, HEADER_H - 1);
    ctx.clip();
    roundRectPath(ctx, geom.x, geom.y, geom.w, HEADER_H + 8, 8);
    ctx.fillStyle = isBypass ? '#3f4448' : catColor;
    ctx.fill();
    ctx.restore();

    if (simplified) {
      // Low-zoom LOD: high contrast title + socket dots only
      ctx.font = '700 13px sans-serif';
      ctx.fillStyle = palette.ink;
      ctx.textBaseline = 'middle';
      ctx.fillText(String(node.title || node.id).slice(0, 22), geom.x + 10, geom.y + geom.h / 2 + 6);

      for (const pin of [...geom.inPins, ...geom.outPins]) {
        const pm = PORT_TYPES[pin.dataType] || PORT_TYPES.ANY;
        ctx.beginPath();
        ctx.arc(pin.cx, pin.cy, PORT_RADIUS + 1.5, 0, Math.PI * 2);
        ctx.fillStyle = pm.fallbackColor;
        ctx.fill();
      }
      ctx.restore();
      return;
    }

    // Header title + B/R/L Houdini flag pills
    ctx.font = '700 11.5px sans-serif';
    ctx.fillStyle = '#111619';
    ctx.textBaseline = 'middle';
    const maxTitleW = geom.w - 84;
    let label = String(node.title || node.id);
    if (ctx.measureText(label).width > maxTitleW) {
      while (label.length > 3 && ctx.measureText(`${label}…`).width > maxTitleW) {
        label = label.slice(0, -1);
      }
      label = `${label}…`;
    }
    ctx.fillText(label, geom.x + 9, geom.y + HEADER_H / 2 + 0.5);

    const flagStyles = {
      bypass: { active: isBypass, fill: '#f59e0b', text: '#14110c' },
      display: { active: isDisplay, fill: '#10b981', text: '#091f18' },
      locked: { active: isLocked, fill: '#94a3b8', text: '#0f172a' },
    };
    for (const key of ['bypass', 'display', 'locked']) {
      const r = geom.flagRects[key];
      const st = flagStyles[key];
      const hovFlag = hoveredHit?.kind === 'flag' && hoveredHit.nodeId === node.id && hoveredHit.flag === key;
      roundRectPath(ctx, r.x, r.y, r.w, r.h, 3.5);
      ctx.fillStyle = st.active ? st.fill : hovFlag ? 'rgba(17,22,25,0.65)' : 'rgba(17,22,25,0.34)';
      ctx.fill();
      ctx.font = '700 9.5px monospace';
      ctx.fillStyle = st.active ? st.text : '#f7eee2';
      ctx.textAlign = 'center';
      ctx.textBaseline = 'middle';
      ctx.fillText(r.label, r.x + r.w / 2, r.y + r.h / 2 + 0.5);
    }
    ctx.textAlign = 'left';

    // Port pins & labels
    ctx.font = '600 10px sans-serif';
    for (const p of geom.inPins) {
      const pm = PORT_TYPES[p.dataType] || PORT_TYPES.ANY;
      const hovPin = hoveredHit?.kind === 'port_in' && hoveredHit.nodeId === node.id && hoveredHit.portId === p.id;
      ctx.beginPath();
      ctx.arc(p.cx, p.cy, hovPin ? PORT_RADIUS + 2 : PORT_RADIUS, 0, Math.PI * 2);
      ctx.fillStyle = pm.fallbackColor;
      ctx.fill();
      ctx.lineWidth = 1.6;
      ctx.strokeStyle = palette.bg;
      ctx.stroke();

      ctx.fillStyle = palette.inkMuted;
      ctx.textBaseline = 'middle';
      ctx.fillText(p.label, geom.x + 10, p.cy);
    }

    ctx.textAlign = 'right';
    for (const p of geom.outPins) {
      const pm = PORT_TYPES[p.dataType] || PORT_TYPES.ANY;
      const hovPin = hoveredHit?.kind === 'port_out' && hoveredHit.nodeId === node.id && hoveredHit.portId === p.id;
      ctx.beginPath();
      ctx.arc(p.cx, p.cy, hovPin ? PORT_RADIUS + 2 : PORT_RADIUS, 0, Math.PI * 2);
      ctx.fillStyle = pm.fallbackColor;
      ctx.fill();
      ctx.lineWidth = 1.6;
      ctx.strokeStyle = palette.bg;
      ctx.stroke();

      ctx.fillStyle = palette.ink;
      ctx.textBaseline = 'middle';
      ctx.fillText(p.label, geom.x + geom.w - 10, p.cy);
    }
    ctx.textAlign = 'left';

    // Footer bar: operator type + inline telemetry bar or eval badge
    const fy = geom.y + geom.h - FOOTER_H;
    ctx.fillStyle = 'rgba(0, 0, 0, 0.22)';
    ctx.fillRect(geom.x + 1, fy, geom.w - 2, FOOTER_H - 1);

    ctx.font = '600 9.5px monospace';
    ctx.fillStyle = palette.inkMuted;
    ctx.textBaseline = 'middle';
    ctx.fillText(spec.type.toUpperCase(), geom.x + 8, fy + FOOTER_H / 2);

    const bar = pickTelemetryBar(node);
    if (bar) {
      const bx = geom.x + geom.w - 78;
      const by = fy + Math.round((FOOTER_H - 5) / 2);
      ctx.fillStyle = 'rgba(255,255,255,0.12)';
      ctx.fillRect(bx, by, 44, 5);
      ctx.fillStyle = catColor;
      ctx.fillRect(bx, by, Math.round(44 * bar.ratio), 5);
      ctx.textAlign = 'right';
      ctx.fillStyle = palette.ink;
      ctx.fillText(bar.display, geom.x + geom.w - 7, fy + FOOTER_H / 2);
      ctx.textAlign = 'left';
    } else {
      const statusText = isLocked ? 'LOCKED' : isBypass ? 'BYPASS' : isDirty ? 'DIRTY' : 'CLEAN';
      const statusCol = isLocked ? '#94a3b8' : isBypass ? '#f59e0b' : isDirty ? palette.stripe : palette.accent;
      ctx.textAlign = 'right';
      ctx.fillStyle = statusCol;
      ctx.fillText(statusText, geom.x + geom.w - 8, fy + FOOTER_H / 2);
      ctx.textAlign = 'left';
    }

    ctx.restore();
  }

  function drawMinimap(nodes, geomMap) {
    if (!nodes.length || width < 320 || height < 240) {
      cachedMinimap = null;
      return;
    }

    const mx = width - MINIMAP_W - MINIMAP_PAD;
    const my = height - MINIMAP_H - MINIMAP_PAD;
    cachedMinimap = { x: mx, y: my, w: MINIMAP_W, h: MINIMAP_H, minX: 0, minY: 0, scale: 1 };

    let minX = Infinity;
    let minY = Infinity;
    let maxX = -Infinity;
    let maxY = -Infinity;
    for (const n of nodes) {
      const g = geomMap.get(n.id);
      minX = Math.min(minX, g.x);
      minY = Math.min(minY, g.y);
      maxX = Math.max(maxX, g.x + g.w);
      maxY = Math.max(maxY, g.y + g.h);
    }
    const worldSpanX = Math.max(400, maxX - minX + 120);
    const worldSpanY = Math.max(260, maxY - minY + 120);
    const ox = minX - 60;
    const oy = minY - 60;
    const scale = Math.min((MINIMAP_W - 12) / worldSpanX, (MINIMAP_H - 12) / worldSpanY);
    cachedMinimap = { x: mx, y: my, w: MINIMAP_W, h: MINIMAP_H, ox, oy, scale };

    ctx.save();
    roundRectPath(ctx, mx, my, MINIMAP_W, MINIMAP_H, 6);
    ctx.fillStyle = 'rgba(12, 15, 18, 0.86)';
    ctx.fill();
    ctx.lineWidth = 1;
    ctx.strokeStyle = palette.border;
    ctx.stroke();

    for (const n of nodes) {
      const g = geomMap.get(n.id);
      const spec = getOperatorSpec(n.type);
      const rx = mx + 6 + (g.x - ox) * scale;
      const ry = my + 6 + (g.y - oy) * scale;
      const rw = Math.max(4, g.w * scale);
      const rh = Math.max(3, g.h * scale);
      ctx.fillStyle = n.id === viewModel.selectedNodeId ? palette.focus : (CATEGORY_COLORS[spec.category] || palette.stripe);
      ctx.fillRect(rx, ry, rw, rh);
    }

    // Current viewport frame inside minimap
    const tl = screenToWorld(0, 0);
    const br = screenToWorld(width, height);
    const vx = mx + 6 + (tl.x - ox) * scale;
    const vy = my + 6 + (tl.y - oy) * scale;
    const vw = (br.x - tl.x) * scale;
    const vh = (br.y - tl.y) * scale;
    ctx.strokeStyle = palette.ink;
    ctx.lineWidth = 1.2;
    ctx.strokeRect(
      clamp(vx, mx + 2, mx + MINIMAP_W - 6),
      clamp(vy, my + 2, my + MINIMAP_H - 6),
      clamp(vw, 8, MINIMAP_W - 4),
      clamp(vh, 8, MINIMAP_H - 4)
    );
    ctx.restore();
  }

  function renderFrame() {
    rafId = 0;
    if (destroyed) return;
    if (!needsRedraw) return;
    needsRedraw = false;

    const nodes = scopedNodes();
    const edges = scopedEdges(nodes);
    const nodesById = new Map(nodes.map((n) => [n.id, n]));
    const geomMap = buildGeometryMap(nodes);

    if (!hasAutoFitOnce && nodes.length) {
      fitBounds(nodes, 56);
      return;
    }

    ctx.save();
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.fillStyle = palette.bg;
    ctx.fillRect(0, 0, width, height);

    const topLeft = screenToWorld(0, 0);
    const botRight = screenToWorld(width, height);
    const viewRect = { left: topLeft.x, top: topLeft.y, right: botRight.x, bottom: botRight.y };

    ctx.translate(camera.panX, camera.panY);
    ctx.scale(camera.zoom, camera.zoom);

    drawDotGrid(viewRect.left, viewRect.top, viewRect.right, viewRect.bottom);
    drawNetworkBoxes(geomMap);
    drawEdges(edges, nodesById, geomMap, viewRect);

    // Draw selected node last so focus halo always sits cleanly on top
    const orderedNodes = [...nodes].sort((a, b) =>
      a.id === viewModel.selectedNodeId ? 1 : b.id === viewModel.selectedNodeId ? -1 : 0
    );
    for (const n of orderedNodes) {
      drawNode(n, geomMap.get(n.id), viewRect);
      if (multiSelectedIds.has(n.id) && n.id !== viewModel.selectedNodeId) {
        const g = geomMap.get(n.id);
        if (g) {
          ctx.save();
          ctx.strokeStyle = palette.focus;
          ctx.lineWidth = 2;
          roundRectPath(ctx, g.x - 2, g.y - 2, g.w + 4, g.h + 4, 10);
          ctx.stroke();
          ctx.restore();
        }
      }
    }

    if (spliceTargetEdgeId) {
      const se = edges.find((e) => e.id === spliceTargetEdgeId);
      const ep = se ? resolveEdgeEndpoints(se, geomMap) : null;
      if (ep) {
        const [p0, p1, p2, p3] = computeWireBezier(ep.x1, ep.y1, ep.x2, ep.y2);
        ctx.save();
        ctx.strokeStyle = '#f59e0b';
        ctx.lineWidth = 5;
        ctx.beginPath();
        ctx.moveTo(p0.x, p0.y);
        ctx.bezierCurveTo(p1.x, p1.y, p2.x, p2.y, p3.x, p3.y);
        ctx.stroke();
        ctx.restore();
      }
    }

    if (pointerState?.mode === 'wire_drag') {
      const tx = pointerState.snapTarget ? pointerState.snapTarget.x : pointerState.curWx;
      const ty = pointerState.snapTarget ? pointerState.snapTarget.y : pointerState.curWy;
      const isFromOut = pointerState.fromKind === 'port_out';
      const [p0, p1, p2, p3] = isFromOut
        ? computeWireBezier(pointerState.startX, pointerState.startY, tx, ty)
        : computeWireBezier(tx, ty, pointerState.startX, pointerState.startY);
      ctx.save();
      ctx.strokeStyle = pointerState.snapTarget
        ? (pointerState.snapTarget.valid ? '#10b981' : '#ef4444')
        : (PORT_TYPES[pointerState.port?.dataType]?.fallbackColor || palette.accent);
      ctx.lineWidth = 2.6;
      ctx.setLineDash([6, 4]);
      ctx.beginPath();
      ctx.moveTo(p0.x, p0.y);
      ctx.bezierCurveTo(p1.x, p1.y, p2.x, p2.y, p3.x, p3.y);
      ctx.stroke();
      ctx.setLineDash([]);
      if (pointerState.snapTarget) {
        ctx.beginPath();
        ctx.arc(tx, ty, PORT_RADIUS + 4, 0, Math.PI * 2);
        ctx.strokeStyle = pointerState.snapTarget.valid ? '#10b981' : '#ef4444';
        ctx.lineWidth = 2.5;
        ctx.stroke();
      }
      ctx.restore();
    }

    if (pointerState?.mode === 'y_cut' && pointerState.points.length > 1) {
      ctx.save();
      ctx.strokeStyle = '#ef4444';
      ctx.lineWidth = 2.5;
      ctx.setLineDash([5, 3]);
      ctx.beginPath();
      ctx.moveTo(pointerState.points[0].x, pointerState.points[0].y);
      for (let i = 1; i < pointerState.points.length; i += 1) {
        ctx.lineTo(pointerState.points[i].x, pointerState.points[i].y);
      }
      ctx.stroke();
      ctx.setLineDash([]);
      ctx.restore();
    }

    if (pointerState?.mode === 'marquee') {
      const rx = Math.min(pointerState.startWx, pointerState.curWx);
      const ry = Math.min(pointerState.startWy, pointerState.curWy);
      const rw = Math.abs(pointerState.curWx - pointerState.startWx);
      const rh = Math.abs(pointerState.curWy - pointerState.startWy);
      ctx.save();
      ctx.fillStyle = 'rgba(57, 221, 197, 0.14)';
      ctx.strokeStyle = '#39ddc5';
      ctx.lineWidth = 1.5;
      ctx.setLineDash([5, 3]);
      ctx.fillRect(rx, ry, rw, rh);
      ctx.strokeRect(rx, ry, rw, rh);
      ctx.setLineDash([]);
      ctx.restore();
    }
    ctx.restore();

    ctx.save();
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    drawMinimap(nodes, geomMap);
    ctx.restore();
  }

  function panMinimapTo(sx, sy, mm) {
    const wx = mm.ox + (sx - mm.x - 6) / mm.scale;
    const wy = mm.oy + (sy - mm.y - 6) / mm.scale;
    camera = {
      ...camera,
      panX: Math.round(width / 2 - wx * camera.zoom),
      panY: Math.round(height / 2 - wy * camera.zoom),
    };
    onCameraChange?.({ ...camera });
    scheduleDraw();
  }

  function findNearestOppositePort(wx, wy, fromKind, originNodeId, originPort) {
    const nodes = scopedNodes();
    const geomMap = buildGeometryMap(nodes);
    const maxDistSq = (24 / camera.zoom) ** 2;
    let best = null;
    let bestDistSq = maxDistSq;
    for (const n of nodes) {
      if (n.id === originNodeId) continue;
      const g = geomMap.get(n.id);
      if (!g) continue;
      const pins = fromKind === 'port_out' ? g.inPins : g.outPins;
      for (const p of pins) {
        const d2 = (wx - p.x) ** 2 + (wy - p.y) ** 2;
        if (d2 <= bestDistSq) {
          bestDistSq = d2;
          const valid = fromKind === 'port_out'
            ? isPortTypeCompatible(originPort.dataType, p.port.dataType)
            : isPortTypeCompatible(p.port.dataType, originPort.dataType);
          best = { nodeId: n.id, port: p.port, x: p.x, y: p.y, valid };
        }
      }
    }
    return best;
  }

  function segmentsIntersect(ax, ay, bx, by, cx, cy, dx, dy) {
    const ccw = (p1x, p1y, p2x, p2y, p3x, p3y) => (p3y - p1y) * (p2x - p1x) > (p2y - p1y) * (p3x - p1x);
    return ccw(ax, ay, cx, cy, dx, dy) !== ccw(bx, by, cx, cy, dx, dy) &&
           ccw(ax, ay, bx, by, cx, cy) !== ccw(ax, ay, bx, by, dx, dy);
  }

  function findSpliceableEdge(nodeId, wx, wy) {
    const nodes = scopedNodes();
    const node = nodes.find((n) => n.id === nodeId);
    if (!node || !node.inputs?.length || !node.outputs?.length) return '';
    const geomMap = buildGeometryMap(nodes);
    const edges = scopedEdges(nodes);
    const tolSq = (32 / camera.zoom) ** 2;
    for (const e of edges) {
      if (e.fromNode === nodeId || e.toNode === nodeId) continue;
      const ep = resolveEdgeEndpoints(e, geomMap);
      if (!ep) continue;
      const [p0, p1, p2, p3] = computeWireBezier(ep.x1, ep.y1, ep.x2, ep.y2);
      let prev = p0;
      for (let step = 1; step <= 12; step += 1) {
        const pt = cubicPoint(p0, p1, p2, p3, step / 12);
        if (distToSegmentSq(wx, wy, prev.x, prev.y, pt.x, pt.y) <= tolSq) {
          return e.id;
        }
        prev = pt;
      }
    }
    return '';
  }

  function onPointerDown(e) {
    const rect = canvas.getBoundingClientRect();
    const sx = e.clientX - rect.left;
    const sy = e.clientY - rect.top;
    canvas.setPointerCapture?.(e.pointerId);

    if (e.button === 1 || (e.button === 0 && spaceHeld)) {
      pointerState = { mode: 'pan', startX: sx, startY: sy, startPanX: camera.panX, startPanY: camera.panY };
      canvas.style.cursor = 'grabbing';
      return;
    }

    if (yHeld && e.button === 0) {
      const { x: wx, y: wy } = screenToWorld(sx, sy);
      pointerState = { mode: 'y_cut', points: [{ x: wx, y: wy }], hitEdgeIds: new Set() };
      canvas.style.cursor = 'crosshair';
      return;
    }

    const hit = hitTest(sx, sy);
    if (hit.kind === 'minimap') {
      pointerState = { mode: 'minimap', minimap: hit.minimap };
      panMinimapTo(sx, sy, hit.minimap);
      return;
    }

    if (hit.kind === 'port_out' || hit.kind === 'port_in') {
      const { x: wx, y: wy } = screenToWorld(sx, sy);
      pointerState = {
        mode: 'wire_drag',
        fromKind: hit.kind,
        nodeId: hit.nodeId,
        port: hit.port,
        startX: hit.x,
        startY: hit.y,
        curWx: wx,
        curWy: wy,
        snapTarget: null,
      };
      canvas.style.cursor = 'crosshair';
      scheduleDraw();
      return;
    }

    if (hit.kind === 'flag') {
      onToggleFlag?.(hit.nodeId, hit.flag);
      return;
    }

    if (hit.kind === 'node') {
      if (e.altKey && onDuplicateNode) {
        onDuplicateNode(hit.nodeId, hit.node.x + 36, hit.node.y + 36);
        return;
      }
      if (viewModel.selectedNodeId !== hit.nodeId) {
        onSelectNode?.(hit.nodeId);
      }
      const { x: wx, y: wy } = screenToWorld(sx, sy);
      pointerState = {
        mode: 'drag_node',
        nodeId: hit.nodeId,
        offsetX: wx - hit.geom.x,
        offsetY: wy - hit.geom.y,
        origX: hit.node.x,
        origY: hit.node.y,
        moved: false,
      };
      return;
    }

    if (hit.kind === 'edge') {
      onSelectEdge?.(hit.edgeId);
      return;
    }

    if (e.shiftKey && e.button === 0) {
      const { x: wx, y: wy } = screenToWorld(sx, sy);
      pointerState = { mode: 'marquee', startWx: wx, startWy: wy, curWx: wx, curWy: wy };
      canvas.style.cursor = 'crosshair';
      return;
    }

    // Background click starts canvas pan (and clears selection if no drag)
    pointerState = { mode: 'pan_or_clear', startX: sx, startY: sy, startPanX: camera.panX, startPanY: camera.panY, moved: false };
    canvas.style.cursor = 'grabbing';
  }

  function onPointerMove(e) {
    const rect = canvas.getBoundingClientRect();
    const sx = e.clientX - rect.left;
    const sy = e.clientY - rect.top;

    if (pointerState) {
      if (pointerState.mode === 'minimap') {
        panMinimapTo(sx, sy, pointerState.minimap);
        return;
      }
      if (pointerState.mode === 'pan' || pointerState.mode === 'pan_or_clear') {
        const dx = sx - pointerState.startX;
        const dy = sy - pointerState.startY;
        if (Math.hypot(dx, dy) > 3) pointerState.moved = true;
        camera = {
          ...camera,
          panX: pointerState.startPanX + dx,
          panY: pointerState.startPanY + dy,
        };
        onCameraChange?.({ ...camera });
        scheduleDraw();
        return;
      }
      if (pointerState.mode === 'wire_drag') {
        const { x: wx, y: wy } = screenToWorld(sx, sy);
        pointerState.curWx = wx;
        pointerState.curWy = wy;
        const prevSnap = pointerState.snapTarget;
        pointerState.snapTarget = findNearestOppositePort(wx, wy, pointerState.fromKind, pointerState.nodeId, pointerState.port);
        if (pointerState.snapTarget?.valid && (!prevSnap || prevSnap.nodeId !== pointerState.snapTarget.nodeId)) {
          playPortSnap();
        }
        scheduleDraw();
        return;
      }
      if (pointerState.mode === 'y_cut') {
        const { x: wx, y: wy } = screenToWorld(sx, sy);
        const prevPt = pointerState.points[pointerState.points.length - 1];
        pointerState.points.push({ x: wx, y: wy });
        const nodes = scopedNodes();
        const geomMap = buildGeometryMap(nodes);
        for (const edge of scopedEdges(nodes)) {
          const ep = resolveEdgeEndpoints(edge, geomMap);
          if (!ep) continue;
          const [p0, p1, p2, p3] = computeWireBezier(ep.x1, ep.y1, ep.x2, ep.y2);
          let cPrev = p0;
          for (let step = 1; step <= 12; step += 1) {
            const pt = cubicPoint(p0, p1, p2, p3, step / 12);
            if (segmentsIntersect(prevPt.x, prevPt.y, wx, wy, cPrev.x, cPrev.y, pt.x, pt.y)) {
              pointerState.hitEdgeIds.add(edge.id);
              break;
            }
            cPrev = pt;
          }
        }
        scheduleDraw();
        return;
      }
      if (pointerState.mode === 'marquee') {
        const { x: wx, y: wy } = screenToWorld(sx, sy);
        pointerState.curWx = wx;
        pointerState.curWy = wy;
        const rx1 = Math.min(pointerState.startWx, wx);
        const ry1 = Math.min(pointerState.startWy, wy);
        const rx2 = Math.max(pointerState.startWx, wx);
        const ry2 = Math.max(pointerState.startWy, wy);
        multiSelectedIds.clear();
        const geomMap = buildGeometryMap(scopedNodes());
        for (const [nid, g] of geomMap.entries()) {
          if (g.x + g.w >= rx1 && g.x <= rx2 && g.y + g.h >= ry1 && g.y <= ry2) {
            multiSelectedIds.add(nid);
          }
        }
        scheduleDraw();
        return;
      }
      if (pointerState.mode === 'drag_node') {
        const { x: wx, y: wy } = screenToWorld(sx, sy);
        const nx = Math.round(wx - pointerState.offsetX);
        const ny = Math.round(wy - pointerState.offsetY);
        if (Math.hypot(nx - pointerState.origX, ny - pointerState.origY) > 2) {
          pointerState.moved = true;
        }
        dragOverrides.set(pointerState.nodeId, { x: nx, y: ny });
        spliceTargetEdgeId = pointerState.moved ? findSpliceableEdge(pointerState.nodeId, nx + NODE_W / 2, ny + 32) : '';
        scheduleDraw();
        return;
      }
    }

    const hit = hitTest(sx, sy);
    hoveredHit = hit;
    if (hit.kind === 'flag' || hit.kind === 'port_in' || hit.kind === 'port_out' || hit.kind === 'edge' || hit.kind === 'minimap') {
      canvas.style.cursor = 'pointer';
    } else if (hit.kind === 'node') {
      canvas.style.cursor = 'grab';
    } else {
      canvas.style.cursor = spaceHeld ? 'grab' : 'default';
    }

    if (hit.kind === 'port_in' || hit.kind === 'port_out') {
      onHoverHint?.(`Port ${hit.port.label} (${hit.port.dataType})`);
    } else if (hit.kind === 'flag') {
      onHoverHint?.(`Click to toggle ${hit.flag.toUpperCase()} flag`);
    } else if (hit.kind === 'edge') {
      onHoverHint?.(`Wire ${hit.edge.fromNode}.${hit.edge.fromPort} → ${hit.edge.toNode}.${hit.edge.toPort} [${hit.edge.dataType}]`);
    } else {
      onHoverHint?.('');
    }
    scheduleDraw();
  }

  function onPointerUp(e) {
    canvas.releasePointerCapture?.(e.pointerId);
    if (!pointerState) return;
    if (pointerState.mode === 'wire_drag') {
      const snap = pointerState.snapTarget;
      if (snap?.valid) {
        const payload = pointerState.fromKind === 'port_out'
          ? { fromNode: pointerState.nodeId, fromPort: pointerState.port.id, toNode: snap.nodeId, toPort: snap.port.id }
          : { fromNode: snap.nodeId, fromPort: snap.port.id, toNode: pointerState.nodeId, toPort: pointerState.port.id };
        onConnectPorts?.(payload);
      } else if (!snap) {
        onRequestTabMenu?.({
          screenX: e.clientX,
          screenY: e.clientY,
          worldX: pointerState.curWx,
          worldY: pointerState.curWy,
          pendingWire: {
            fromKind: pointerState.fromKind,
            nodeId: pointerState.nodeId,
            port: pointerState.port,
          },
        });
      }
      scheduleDraw();
    } else if (pointerState.mode === 'y_cut') {
      if (pointerState.hitEdgeIds.size > 0) {
        playWireCut();
        onCutEdges?.(Array.from(pointerState.hitEdgeIds));
      }
      scheduleDraw();
    } else if (pointerState.mode === 'marquee') {
      const firstId = Array.from(multiSelectedIds)[0];
      if (firstId) onSelectNode?.(firstId);
      scheduleDraw();
    } else if (pointerState.mode === 'drag_node') {
      const finalPos = dragOverrides.get(pointerState.nodeId);
      const spliceId = spliceTargetEdgeId;
      dragOverrides.delete(pointerState.nodeId);
      spliceTargetEdgeId = '';
      if (pointerState.moved && finalPos) {
        onMoveNode?.(pointerState.nodeId, finalPos.x, finalPos.y);
        if (spliceId) {
          onSpliceNodeOnEdge?.(pointerState.nodeId, spliceId);
        }
      }
      scheduleDraw();
    } else if (pointerState.mode === 'pan_or_clear' && !pointerState.moved) {
      multiSelectedIds.clear();
      if (viewModel.selectedNodeId || viewModel.selectedEdgeId) {
        onSelectNode?.('');
      }
    }
    canvas.style.cursor = spaceHeld ? 'grab' : yHeld ? 'crosshair' : 'default';
    pointerState = null;
  }

  function onWheel(e) {
    e.preventDefault();
    const rect = canvas.getBoundingClientRect();
    const sx = e.clientX - rect.left;
    const sy = e.clientY - rect.top;
    const factor = e.deltaY < 0 ? 1.11 : 0.9;
    const nextZoom = clamp(camera.zoom * factor, 0.2, 2.5);
    const wx = (sx - camera.panX) / camera.zoom;
    const wy = (sy - camera.panY) / camera.zoom;
    camera = {
      zoom: nextZoom,
      panX: sx - wx * nextZoom,
      panY: sy - wy * nextZoom,
    };
    onCameraChange?.({ ...camera });
    scheduleDraw();
  }

  function syncCanvasSize() {
    const rect = canvas.getBoundingClientRect();
    if (!rect.width || !rect.height) return;
    dpr = window.devicePixelRatio || 1;
    width = rect.width;
    height = rect.height;
    canvas.width = Math.round(width * dpr);
    canvas.height = Math.round(height * dpr);
    scheduleDraw();
  }

  const ro = typeof ResizeObserver === 'function' ? new ResizeObserver(syncCanvasSize) : null;
  ro?.observe(canvas);
  syncCanvasSize();

  function onContextMenu(e) {
    e.preventDefault();
    const rect = canvas.getBoundingClientRect();
    const { x: wx, y: wy } = screenToWorld(e.clientX - rect.left, e.clientY - rect.top);
    onRequestTabMenu?.({
      screenX: e.clientX,
      screenY: e.clientY,
      worldX: wx,
      worldY: wy,
      pendingWire: null,
    });
  }

  function onDblClick(e) {
    const rect = canvas.getBoundingClientRect();
    const hit = hitTest(e.clientX - rect.left, e.clientY - rect.top);
    if (hit.kind === 'node' && hit.node?.type === 'subnet') {
      onEnterSubnet?.(hit.nodeId);
    }
  }

  canvas.addEventListener('pointerdown', onPointerDown);
  canvas.addEventListener('pointermove', onPointerMove);
  canvas.addEventListener('pointerup', onPointerUp);
  canvas.addEventListener('pointercancel', onPointerUp);
  canvas.addEventListener('dblclick', onDblClick);
  canvas.addEventListener('contextmenu', onContextMenu);
  canvas.addEventListener('wheel', onWheel, { passive: false });

  function onKeyDown(e) {
    if (e.code === 'Space') spaceHeld = true;
    if (e.key.toLowerCase() === 'y') yHeld = true;
  }
  function onKeyUp(e) {
    if (e.code === 'Space') spaceHeld = false;
    if (e.key.toLowerCase() === 'y') yHeld = false;
  }
  window.addEventListener('keydown', onKeyDown);
  window.addEventListener('keyup', onKeyUp);

  return {
    updateModel(nextModel) {
      viewModel = nextModel;
      scheduleDraw();
    },
    refreshTheme,
    fitAll,
    frameSelected,
    getCamera: () => ({ ...camera }),
    getViewportCenterWorld,
    getSelectedNodeIds: () => Array.from(new Set([...multiSelectedIds, ...(viewModel.selectedNodeId ? [viewModel.selectedNodeId] : [])])),
    renderImmediateForBenchmark() {
      needsRedraw = true;
      renderFrame();
    },
    destroy() {
      destroyed = true;
      if (rafId) cancelAnimationFrame(rafId);
      ro?.disconnect();
      canvas.removeEventListener('pointerdown', onPointerDown);
      canvas.removeEventListener('pointermove', onPointerMove);
      canvas.removeEventListener('pointerup', onPointerUp);
      canvas.removeEventListener('pointercancel', onPointerUp);
      canvas.removeEventListener('dblclick', onDblClick);
      canvas.removeEventListener('contextmenu', onContextMenu);
      canvas.removeEventListener('wheel', onWheel);
      window.removeEventListener('keydown', onKeyDown);
      window.removeEventListener('keyup', onKeyUp);
    },
  };
}
