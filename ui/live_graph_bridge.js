/* Noir Fiction Studio — Milestone 8: Live Reactive Block <-> Story Graph <-> Character Graph Bridge */

const CHAR_ALIASES = [
  { id: 'rainee_peter', name: 'Rainee · Peter', re: /\b(?:rainee[\s\-·]*peter|peter\s+griffin|peter\s+variant)\b/i },
  { id: 'three_bitches', name: 'Three Little Bitches', re: /\b(?:three\s+little\s+bitches|rainee[\s\-]*split|sade|becky|clarie)\b/i },
  { id: 'francine', name: 'Francine Ling', re: /\b(?:francine|nurse\s+franny|nurse\s+pamela|franny)\b/i },
  { id: 'rainee', name: 'Rainee Ling', re: /\b(?:rainee)\b/i },
  { id: 'stella', name: 'Stella Ling', re: /\b(?:stella|big\s+tiddy\s+steve)\b/i },
  { id: 'haley', name: 'Haley Ling', re: /\b(?:haley|hayley)\b/i },
];

export function stripMarkdown(text = '') {
  return String(text || '')
    .replace(/^\s*#{1,6}\s*/gm, '')
    .replace(/\*\*([^*]+)\*\*/g, '$1')
    .replace(/\*([^*]+)\*/g, '$1')
    .replace(/`([^`]+)`/g, '$1')
    .replace(/^\s*[-*_]{3,}\s*$/gm, '')
    .replace(/\s+/g, ' ')
    .trim();
}

export function normalizeCharKey(raw = '') {
  const s = String(raw || '').trim();
  if (!s) return '';
  for (const entry of CHAR_ALIASES) {
    if (entry.re.test(s)) return entry.id;
  }
  return s.toLowerCase().replace(/[^a-z0-9]+/g, '_').replace(/^_+|_+$/g, '');
}

export function detectMentionedCharacters(text = '', sampleChars = []) {
  const s = String(text || '');
  if (!s.trim()) return [];
  const found = [];
  const seen = new Set();

  for (const entry of CHAR_ALIASES) {
    if (entry.re.test(s) && !seen.has(entry.id)) {
      seen.add(entry.id);
      const sample = (sampleChars || []).find((c) => c.id === entry.id);
      found.push({ id: entry.id, name: sample?.name || entry.name });
    }
  }
  for (const c of sampleChars || []) {
    if (seen.has(c.id)) continue;
    const first = String(c.name || c.id).split(/\s+/)[0];
    if (first.length >= 3 && new RegExp(`\\b${first.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}\\b`, 'i').test(s)) {
      seen.add(c.id);
      found.push({ id: c.id, name: c.name || c.id });
    }
  }
  return found;
}

export function deriveLiveStoryGraph(state, sampleChars = []) {
  const blocks = state?.draftBlocks || state?.episodeState?.notebook?.blocks || state?.episodeState?.blocks || [];
  const nodes = [];
  const blockToBeatId = new Map();
  const charBlockLinks = new Map();

  const recordCharLink = (charId, charName, link) => {
    if (!charId) return;
    if (!charBlockLinks.has(charId)) charBlockLinks.set(charId, []);
    const arr = charBlockLinks.get(charId);
    if (!arr.some((x) => x.blockId === link.blockId)) {
      arr.push({ ...link, charName: charName || charId });
    }
  };

  let currentBeat = null;
  let sceneSeq = 0;
  let stageSeq = 0;

  for (let i = 0; i < blocks.length; i += 1) {
    const b = blocks[i];
    const kind = b.kind || 'narrator';
    const clean = stripMarkdown(b.text || '');

    if (kind === 'scene-heading' || (!currentBeat && kind === 'narrator' && clean)) {
      sceneSeq += 1;
      const beatId = `B${String(sceneSeq).padStart(2, '0')}`;
      currentBeat = {
        id: beatId,
        nodeType: kind === 'scene-heading' ? 'SCENE' : 'BEAT',
        title: (clean || `Scene ${sceneSeq}`).slice(0, 44),
        summary: '',
        branch: 'G0',
        blockId: b.id || '',
        speakers: [],
        mentions: [],
        blockIds: b.id ? [b.id] : [],
      };
      nodes.push(currentBeat);
      if (b.id) blockToBeatId.set(b.id, beatId);
      continue;
    }

    if (kind === 'stage-direction') {
      stageSeq += 1;
      const stageId = `S${String(stageSeq).padStart(2, '0')}`;
      const mentions = detectMentionedCharacters(clean, sampleChars);
      const stageNode = {
        id: stageId,
        nodeType: 'STAGE',
        title: (clean || `Stage Direction ${stageSeq}`).slice(0, 44),
        summary: mentions.length ? `Cues: ${mentions.map((m) => m.name).join(', ')}` : 'Stage blocking & camera cue',
        branch: 'G0',
        blockId: b.id || '',
        speakers: mentions.map((m) => m.name),
        mentions,
        blockIds: b.id ? [b.id] : [],
      };
      nodes.push(stageNode);
      currentBeat = stageNode;
      if (b.id) blockToBeatId.set(b.id, stageId);
      for (const m of mentions) {
        recordCharLink(m.id, m.name, { blockId: b.id, beatId: stageId, kind: 'stage-direction', snippet: clean.slice(0, 64) });
      }
      continue;
    }

    if (!currentBeat) {
      sceneSeq += 1;
      const beatId = `B${String(sceneSeq).padStart(2, '0')}`;
      currentBeat = {
        id: beatId,
        nodeType: 'BEAT',
        title: `Opening Beat`,
        summary: '',
        branch: 'G0',
        blockId: b.id || '',
        speakers: [],
        mentions: [],
        blockIds: b.id ? [b.id] : [],
      };
      nodes.push(currentBeat);
    }

    if (b.id) {
      blockToBeatId.set(b.id, currentBeat.id);
      if (!currentBeat.blockIds.includes(b.id)) currentBeat.blockIds.push(b.id);
    }

    if (kind === 'character') {
      const rawSpk = b.speaker || (clean.match(/^([A-Z][A-Za-z0-9 .'\-]{1,28})[:—]/)?.[1] || '');
      const cid = normalizeCharKey(rawSpk) || normalizeCharKey(clean.slice(0, 24));
      const matchedSample = (sampleChars || []).find((c) => c.id === cid);
      const label = matchedSample?.name || rawSpk || 'Character';
      if (label && !currentBeat.speakers.includes(label)) currentBeat.speakers.push(label);
      if (cid) {
        recordCharLink(cid, label, { blockId: b.id, beatId: currentBeat.id, kind: 'character', snippet: clean.slice(0, 64) });
      }
      if (!currentBeat.summary && clean) currentBeat.summary = clean.slice(0, 88);
    } else if (kind === 'narrator' && clean && !currentBeat.summary) {
      currentBeat.summary = clean.slice(0, 88);
    }

    for (const m of detectMentionedCharacters(clean, sampleChars)) {
      if (!currentBeat.speakers.includes(m.name) && kind !== 'narrator') currentBeat.speakers.push(m.name);
      recordCharLink(m.id, m.name, { blockId: b.id, beatId: currentBeat.id, kind, snippet: clean.slice(0, 64) });
    }
  }

  return { nodes, blockToBeatId, charBlockLinks };
}

export function summarizeLiveCharacterLinks(state, sampleChars = []) {
  return deriveLiveStoryGraph(state, sampleChars).charBlockLinks;
}
