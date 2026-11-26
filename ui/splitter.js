/* Noir Fiction Studio v2 — M2 Unprocessed Script Onboarding & Auto-Splitter */

const SCENE_HEADING_RE =
  /^(?:#{1,6}\s+\S|(?:SECTION\s+\d+|INT\.|EXT\.|INT\/EXT\.|I\/E\.|NT\.\s+|SCENE\s+\d+|CHAPTER\s+\d+|END OF\b|POST-LANDING CHAOS\b|REVISED TRANSFORMATION SCENE\b|COMPRESSED\s+(?:BIG\s+TIDDY\s+)?NERDY\b))/i;

const STAGE_LINE_RE = /^\([^)]+\)\s*$/;

const SPEAKER_PREFIX_RE =
  /^([A-Z][A-Z0-9 .'\-]{1,42}?)(?=\s*\(|\s*—|\s*:|\s*[A-Z][a-z"']|\s*["“])/;

function makeId() {
  if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
    return crypto.randomUUID().replaceAll('-', '');
  }
  return `${Date.now().toString(16)}${Math.random().toString(16).slice(2, 14)}`;
}

function toSpeakerSlug(rawName) {
  const cleaned = rawName
    .replace(/\([^)]*\)/g, '')
    .replace(/\bCONT'D\b/gi, '')
    .replace(/\bO\.S\.\b/gi, '')
    .replace(/\bV\.O\.\b/gi, '')
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '_')
    .replace(/^_+|_+$/g, '');
  return cleaned || 'character';
}

function classifyLine(trimmed) {
  if (!trimmed) {
    return { kind: 'narrator', speaker: null };
  }
  if (SCENE_HEADING_RE.test(trimmed)) {
    return { kind: 'scene-heading', speaker: null };
  }
  if (STAGE_LINE_RE.test(trimmed)) {
    return { kind: 'stage-direction', speaker: null };
  }
  const match = trimmed.match(SPEAKER_PREFIX_RE);
  if (match) {
    const candidate = match[1].trim();
    // Avoid false positives on short ALL-CAPS words mid-prose like "WHAT" or "NO"
    if (candidate.length >= 3 && !/^(?:THE|AND|BUT|FOR|NOT|YES|NO|WHOA|WAIT|WHAT|THIS|THAT|OMG)$/.test(candidate)) {
      return { kind: 'character', speaker: toSpeakerSlug(candidate) };
    }
  }
  return { kind: 'narrator', speaker: null };
}

export function isUnprocessedEpisode(ep, blocks) {
  const list = Array.isArray(blocks) ? blocks : [];
  if (/unprocessed/i.test(ep?.title || '')) {
    return list.some((b) => b.kind === 'unresolved');
  }
  return list.length <= 2 && list.some((b) => b.kind === 'unresolved' && (b.text || '').length > 400);
}

const SPEAKER_ALIASES = {
  hayley: 'haley',
  holly_graham: 'holly',
  chief: 'chief_scientist',
  mama_ling: 'ma_ma_ling',
  ma_ma: 'ma_ma_ling',
};

export function matchSpeakerToJunction(speakerSlug, junctions = []) {
  const raw = String(speakerSlug || '').trim().toLowerCase();
  if (!raw || !Array.isArray(junctions) || !junctions.length) return null;
  const normalized = SPEAKER_ALIASES[raw] || raw;
  const normalizedSlug = toSpeakerSlug(normalized);
  const firstToken = normalizedSlug.split('_')[0];

  const byId = junctions.find((j) => {
    const cid = String(j.character_id || '').toLowerCase();
    return cid === normalized || toSpeakerSlug(cid) === normalizedSlug;
  });
  const byLabel = junctions.find((j) => toSpeakerSlug(j.label || '') === normalizedSlug);
  const byAliasToken = junctions.find((j) => {
    const cid = toSpeakerSlug(j.character_id || '');
    const lbl = toSpeakerSlug(j.label || '');
    return (firstToken && firstToken !== 'character' && (cid === firstToken || lbl === firstToken))
      || (cid && normalizedSlug.startsWith(`${cid}_`));
  });
  const match = byId || byLabel || byAliasToken;
  if (!match) return null;

  const forms = Array.isArray(match.forms) ? match.forms : [];
  const defaultForm = forms.find((f) => f.is_default) || forms[0] || null;
  return {
    character_id: match.character_id,
    junction_id: match.junction_id,
    label: match.label || match.character_id,
    form_id: defaultForm ? (defaultForm.id || defaultForm.form_id || null) : null,
    form_label: defaultForm ? (defaultForm.display_label || defaultForm.label || defaultForm.id || defaultForm.form_id) : null,
  };
}

export function summarizeCharacterLinks(blocks = [], junctions = []) {
  const bySpeaker = new Map();
  for (const block of Array.isArray(blocks) ? blocks : []) {
    if (!block || block.kind !== 'character') continue;
    const rawSpeaker = String(block.speaker || '').trim();
    const detected = rawSpeaker || (classifyLine(String(block.text || '').trim()).speaker || '');
    if (!detected) continue;
    const key = toSpeakerSlug(detected);
    if (!key) continue;
    const match = matchSpeakerToJunction(key, junctions);
    const canonicalKey = match ? match.character_id : key;
    if (!bySpeaker.has(canonicalKey)) {
      bySpeaker.set(canonicalKey, {
        key: canonicalKey,
        rawSpeaker: detected,
        label: match ? match.label : detected.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase()),
        count: 0,
        linked: Boolean(match),
        character_id: match ? match.character_id : null,
        junction_id: match ? match.junction_id : null,
        form_id: match ? match.form_id : null,
        blockIds: [],
      });
    }
    const entry = bySpeaker.get(canonicalKey);
    entry.count += 1;
    if (block.id) entry.blockIds.push(block.id);
  }
  return Array.from(bySpeaker.values()).sort((a, b) => b.count - a.count || a.label.localeCompare(b.label));
}

export function splitRawScriptIntoBlocks(blocks, junctions = []) {
  const raw = (Array.isArray(blocks) ? blocks : []).map((b) => b.text || '').join('');
  if (!raw) return blocks;

  const lines = raw.match(/[^\r\n]*(?:\r\n|\r|\n|$)/g) || [];
  const nextBlocks = [];

  for (const line of lines) {
    if (!line) continue;
    const trimmed = line.replace(/\r?\n$/, '').trim();
    const { kind, speaker } = classifyLine(trimmed);
    const matched = kind === 'character' && speaker ? matchSpeakerToJunction(speaker, junctions) : null;
    nextBlocks.push({
      id: makeId(),
      kind,
      speaker: matched ? matched.character_id : speaker,
      form: matched ? matched.form_id : null,
      text: line,
      source: null,
    });
  }

  return nextBlocks.length ? nextBlocks : blocks;
}

export function summarizeSplit(blocks) {
  const counts = { 'scene-heading': 0, character: 0, narrator: 0, 'stage-direction': 0, unresolved: 0 };
  for (const b of blocks || []) {
    counts[b.kind] = (counts[b.kind] || 0) + 1;
  }
  return counts;
}

export function extractSceneOutline(blocks) {
  const outline = [];
  (blocks || []).forEach((b, idx) => {
    if (b.kind === 'scene-heading') {
      const label = (b.text || '').trim().split(/\r?\n/)[0].slice(0, 64);
      if (label) outline.push({ index: idx, blockId: b.id, label });
    }
  });
  return outline;
}
