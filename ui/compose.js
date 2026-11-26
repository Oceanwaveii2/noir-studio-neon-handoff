/* Noir Fiction Studio v2 — M1/M2 Compose Studio, Protection & Raw-Script Splitter */
import {
  isUnprocessedEpisode,
  matchSpeakerToJunction,
  summarizeCharacterLinks,
} from './splitter.js';
import {
  displayEpisodeTitle,
} from './shelf.js';
import {
  deriveLiveStoryGraph,
  detectMentionedCharacters,
} from './live_graph_bridge.js';

import { renderActStructure } from './beat.js';

export function escapeHtml(value) {
  return String(value ?? '')
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#39;');
}

const textareaValue = (text) => text.replace(/\r\n?/g, '\n');
export function writerOptionsHtml(writers, current) {
  const options = writers || [{id:'codex-session',label:'Codex'},{id:'gemini-session',label:'Gemini'}];
  const missing = current && !options.some(writer => writer.id === current);
  return (missing ? `<option selected disabled value="${escapeHtml(current)}">Saved writer unavailable</option>` : '') +
    options.map(({id,label}) => `<option value="${escapeHtml(id)}" ${id === current ? 'selected' : ''}>${escapeHtml(label)}</option>`).join('');
}
const codePoints = (text) => [...text].length;

/** Build an O(1) Unicode code-point -> UTF-16 offset lookup table (0-mismatch across CRLF/emojis). */
export function buildCodePointMap(text) {
  const cps = Array.from(String(text || ''));
  const map = new Int32Array(cps.length + 1);
  let u16 = 0;
  for (let i = 0; i < cps.length; i += 1) {
    map[i] = u16;
    u16 += cps[i].length;
  }
  map[cps.length] = u16;
  return map;
}
const PLAY_FRAME = {25: 33, 50: 0, 75: 3, 100: 9};
const PLAY_MS = {25: 490, 50: 700, 75: 910, 100: 1330};
let playSerial = 0;
let selectionListeners;

export function renderTrack(weight, small = false) {
  const frame = PLAY_FRAME[weight] ?? 27;
  return `<span data-track class="v2-track ${small ? 'v2-track-small' : ''}" aria-hidden="true" data-frame="${frame}" style="background-position:${frame % 6 * 20}% ${Math.floor(frame / 6) * 20}%"></span>`;
}

export function animateTrack(node, weight) {
  if (!node || !PLAY_MS[weight] || matchMedia('(prefers-reduced-motion: reduce)').matches) return;
  const animation = new Image();
  animation.alt = '';
  animation.onload = () => setTimeout(() => animation.remove(), PLAY_MS[weight]+100);
  animation.onerror = () => animation.remove();
  node.replaceChildren(animation);
  animation.src = `/assets/noir-track-dial-${weight}-once.gif?play=${++playSerial}`;
}

export function composeText(blocks) {
  return blocks.map((block) => block.text || '').join('');
}

function displayedBlock(block) {
  const text = block?.text || '';
  const candidate = block?.cue_prefix;
  const cue=block?.kind==='character' && candidate && text.startsWith(candidate) ? candidate : '';
  const remaining=text.slice(cue.length);
  const separator=remaining.match(/(?:\r\n|(?<!\r)\n|\r(?!\n)){2,}$/)?.[0] || '';
  return { cue, body:remaining.slice(0,remaining.length-separator.length), separator };
}

export function revealStoryPassage(blocks, passage) {
  let offset = 0;
  let first = null;
  for (const block of blocks) {
    const points = [...block.text];
    const end = offset + points.length;
    if (offset < passage.end && passage.start < end) {
      const card = document.querySelector(`[data-block-id="${CSS.escape(block.id)}"]`);
      const editor = card?.querySelector('[data-block-text]');
      if (card && editor) {
        card.dataset.storyPassage = 'true';
        const { cue } = displayedBlock(block);
        const cueLength = codePoints(cue);
        const display = (absolute) => textareaValue(points.slice(cueLength, Math.max(cueLength, absolute - offset)).join('')).length;
        const from = Math.min(editor.value.length, display(passage.start));
        const to = Math.min(editor.value.length, display(passage.end));
        first ||= { card, editor, from, to };
      }
    }
    offset = end;
  }
  if (!first) return false;
  first.card.scrollIntoView({ block: 'center', inline: 'nearest' });
  first.editor.focus({ preventScroll: true });
  first.editor.setSelectionRange(first.from, first.to);
  return true;
}

function blockPosition(block, displayedOffset) {
  const { cue, body } = displayedBlock(block);
  return codePoints(cue + body.slice(0, sourceOffset(body, displayedOffset)));
}

function sourceOffset(text, offset) {
  let raw = 0;
  for (let visible = 0; visible < offset && raw < text.length; visible += 1) {
    raw += text.startsWith('\r\n', raw) ? 2 : 1;
  }
  return raw;
}

function retainSourceText(previous, value) {
  const display = textareaValue(previous);
  if (display === value) return previous;
  let start = 0, tail = 0;
  while (start < display.length && start < value.length && display[start] === value[start]) start += 1;
  while (tail < display.length - start && tail < value.length - start
         && display[display.length - 1 - tail] === value[value.length - 1 - tail]) tail += 1;
  const from = sourceOffset(previous, start);
  const to = sourceOffset(previous, display.length - tail);
  const newline = previous.slice(from, to).match(/\r\n|\r|\n/)?.[0]
    || previous.match(/\r\n|\r|\n/)?.[0] || '\n';
  return previous.slice(0, from) + value.slice(start, value.length - tail).replaceAll('\n', newline) + previous.slice(to);
}

function lineNumbersFor(text, first = 1) {
  const count = Math.max(1, textareaValue(String(text || '')).replace(/\n+$/, '').split('\n').length);
  return Array.from({ length: count }, (_, i) => String(i + first).padStart(3,'0')).join('\n');
}

const separatorBlock = b => /^\s*(?:\*{3,}|-{3,}|_{3,})\s*$/.test(b.text || '');

function maskedBody(body, base, masks) {
  const raw = [...body];
  const hits = masks.filter(m => m.start < base+raw.length && m.end > base);
  if (!hits.length) return escapeHtml(textareaValue(body));
  const cuts = [...new Set([0,raw.length, ...hits.flatMap(m => [Math.max(0,m.start-base), Math.min(raw.length,m.end-base)])])].sort((a,b) => a-b);
  return cuts.slice(0,-1).map((a,i) => {
    const b = cuts[i+1];
    const weight = Math.max(0,...hits.filter(m => m.start < base+b && m.end > base+a).map(m => m.value));
    const text = escapeHtml(textareaValue(raw.slice(a,b).join('')));
    return weight ? `<mark data-protect="${weight}">${text}</mark>` : text;
  }).join('');
}

function speakerName(block, state, fallback) {
  const junction = state.formGraph?.junctions?.find(j => j.character_id === block.speaker);
  const form = junction?.forms?.find(f => f.id === block.form || f.port_id === block.form);
  if (form && form.kind !== 'base' && form.label) return form.label;
  return junction?.label || state.episodeState?.imported_source?.characters?.[block.speaker]?.label || (block.speaker ? 'Character' : fallback);
}

function blockOffsetMap(blocks) {
  const offsets = [];
  let pos = 0;
  for (let i = 0; i < blocks.length; i += 1) {
    offsets.push(pos);
    pos += codePoints(blocks[i].text || '');
  }
  return offsets;
}

function groupBlockByCharacter(block, body, defaultSpeaker) {
  const groups = new Map();
  const addLine = (speaker, line) => {
    const key = (speaker || 'NARRATOR').toUpperCase();
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key).push(line);
  };
  let curSpeaker = defaultSpeaker || (block.kind === 'stage-direction' ? 'STAGE' : 'NARRATOR');
  for (const raw of String(body || '').split(/\r?\n/)) {
    const line = raw.trim();
    if (!line) continue;
    const colonMatch = line.match(/^([A-Z][A-Z0-9 .'\-()]{1,36}):\s*(.+)$/);
    if (colonMatch) {
      curSpeaker = colonMatch[1].trim();
      addLine(curSpeaker, colonMatch[2].trim());
    } else if (/^[A-Z][A-Z0-9 .'\-()]{1,32}$/.test(line) && !/^INT\.|^EXT\./.test(line)) {
      curSpeaker = line;
    } else {
      addLine(curSpeaker, line);
    }
  }
  return Array.from(groups.entries());
}

function blockMaskWeight(nb, startOffset, endOffset) {
  const masks = nb?.masks || [];
  let maxWeight = null;
  for (const m of masks) {
    if (m.end > startOffset && m.start < endOffset) {
      maxWeight = maxWeight === null ? m.weight : Math.max(maxWeight, m.weight);
    }
  }
  return maxWeight !== null ? maxWeight : (nb?.default_protection ?? 0);
}

function blockInfluencePills(block, body, maskPct, state) {
  const pills = [];
  if ((state.worldLaws?.laws || []).length) pills.push('<span class="v2-inf-pill is-law" title="Enforced by World Laws">🔴 Law</span>');
  if (block.kind === 'character' || block.form || block.speaker) pills.push('<span class="v2-inf-pill is-mind" title="Linked Character / Mind">🔵 Mind</span>');
  if (maskPct < 100) pills.push('<span class="v2-inf-pill is-book" title="Eligible for 190-Book Craft Engine">🟣 Craft</span>');
  if (/\b(?:fart|cutaway|ernie|billy|mandy|knock|blast)\b/i.test(body || '')) pills.push('<span class="v2-inf-pill is-media" title="Gag / Media Telemetry Target">🟡 Gag</span>');
  return pills.join('');
}

export function computeClientCraftTelemetry(blocks, state) {
  const list = Array.isArray(blocks) ? blocks : [];
  const fullText = list.map((b) => String(b?.text || '')).join('\n');
  const sentences = fullText
    .split(/[.!?]+/)
    .map((s) => s.trim().split(/\s+/).filter((w) => w && !w.startsWith('*')).length)
    .filter((len) => len >= 2);

  let burstiness = 0;
  if (sentences.length >= 3) {
    const mean = sentences.reduce((a, b) => a + b, 0) / sentences.length;
    const variance = sentences.reduce((acc, len) => acc + (len - mean) ** 2, 0) / sentences.length;
    burstiness = Math.round(Math.sqrt(variance) * 100) / 100;
  }

  const slopPatterns = [
    /\b(?:because of this|due to this|as a result of this|it is worth noting that)\b/gi,
    /\b(?:not\s+(?:a|an|just\s+)?[a-z]+,\s+but\s+(?:rather\s+)?[a-z]+|less\s+[a-z]+\s+and\s+more\s+[a-z]+)\b/gi,
    /\b(?:it\s+)?(?:wasn'?t|isn'?t)\s+[^.!?\n]{2,36}(?:—|--|,)\s*(?:it\s+)?(?:was|is)\b/gi,
    /\b(?:delve[ds]?|tapestry|symphony of|labyrinthine|palpable tension|deafening silence|couldn't help but|almost as if)\b/gi,
  ];
  let slopHits = 0;
  for (const pat of slopPatterns) {
    const matches = fullText.match(pat);
    if (matches) slopHits += matches.length;
  }

  const words = Math.max(1, (fullText.match(/\b[\w'-]+\b/g) || []).length);
  const density = (slopHits / words) * 100;
  const burstPenalty = sentences.length >= 3 ? Math.max(0, 4.0 - burstiness) * 5.0 : 0;
  const slopScore = Math.min(100, Math.round((density * 9.5 + slopHits * 3.5 + burstPenalty) * 10) / 10);

  const nbMasks = state?.episodeState?.notebook?.masks || [];
  const lockedCount = nbMasks.filter((m) => Number(m?.weight) === 0 || Number(m?.weight) === 100).length
    + list.filter((b) => b?.kind === 'character' && Number(b?.protection ?? 0) === 0).length;
  const libraryBooks = Number(state?.libraryStatus?.total_books || state?.libraryStatus?.eligible_books || 190);

  return {
    slopScore,
    slopHits,
    burstiness,
    lockedCount,
    libraryBooks,
    tier: slopScore <= 12 ? 'is-clean' : slopScore <= 28 ? 'is-warn' : 'is-alert',
  };
}

export function renderComposeStage({ ep, badge, blocks, stats, state, speakerPicker }) {
  const activeDraft = state.activeDraftId
    ? (state.timelineDrafts || []).find((d) => d.id === state.activeDraftId)
    : null;
  const draftIdx = activeDraft
    ? (state.timelineDrafts || []).findIndex((d) => d.id === state.activeDraftId)
    : -1;
  const draftNum = draftIdx >= 0 ? ((state.timelineDrafts || []).length - draftIdx) : 1;

  if (activeDraft) {
    return `
      <div class="v2-compose-wrap">
        <section class="v2-compose-bar">
          <div>
            <h1>${escapeHtml(ep?.title || 'Select an episode')}</h1>
            <p class="v2-stage-sub">
              Viewing Draft Variant #${draftNum} · ${escapeHtml(activeDraft.id.slice(0, 8))}
            </p>
          </div>
          <span class="v2-pill v2-pill-draft">${escapeHtml(activeDraft.status || 'PROPOSED')}</span>
        </section>

        <section class="v2-draft-variant-banner">
          <div>
            <strong>✨ Viewing AI Draft #${draftNum} (${escapeHtml(activeDraft.status || 'PROPOSED')})</strong>
            <p class="v2-stage-sub" style="margin:2px 0 0">
              Provider: ${escapeHtml(activeDraft.provider || 'gemini-session')} · ${(activeDraft.text || '').length} characters · Created ${escapeHtml(activeDraft.created_at || 'just now')}
            </p>
          </div>
          <div class="v2-compose-actions" style="display:flex;gap:8px">
            <button type="button" class="v2-btn v2-btn-accent" id="v2ComposeApplyDraftBtn" data-draft-id="${escapeHtml(activeDraft.id)}" ${state.busy || activeDraft.status !== 'PROPOSED' ? 'disabled' : ''}>
              Apply Draft to Script
            </button>
            <button type="button" class="v2-btn" id="v2ComposeExitDraftBtn">
              Back to Current Script
            </button>
          </div>
        </section>

        <div class="v2-draft-viewer-card">
          <pre class="v2-draft-main-text">${escapeHtml(activeDraft.text || 'No text in draft.')}</pre>
        </div>
      </div>
    `;
  }

  const locked = Boolean(state.episodeState?.legacy_locked) || ep?.status !== 'draft';
  const showOnboarding = !locked && isUnprocessedEpisode(ep, blocks);
  const highlighting = Boolean(state.highlightMode) && !locked;
  const offsets = blockOffsetMap(blocks);
  const nb = state.episodeState?.notebook || null;
  const masks = nb?.masks || [];
  const sampleChars = state.sampleProjects?.[0]?.characters || [];
  const liveGraph = deriveLiveStoryGraph({ ...state, draftBlocks: blocks }, sampleChars);
  let logicalLine = 1;

  const composeFont = (() => { try { return localStorage.getItem('noir-compose-font') || 'serif'; } catch (_) { return 'serif'; } })();

  return `
    <div class="v2-compose-wrap">
      ${!highlighting && !locked ? `
        <div class="v2-quick-insert-dock" role="toolbar" aria-label="Quick insert story blocks">
          <span class="v2-quick-insert-label">INSERT NODE</span>
          <button type="button" class="v2-quick-btn is-scene" data-append-kind="scene-heading" ${state.busy ? 'disabled' : ''}>+ Scene</button>
          <button type="button" class="v2-quick-btn is-stage" data-append-kind="stage-direction" ${state.busy ? 'disabled' : ''}>+ Stage</button>
          <button type="button" class="v2-quick-btn is-char" data-append-kind="character" ${state.busy ? 'disabled' : ''}>+ Char</button>
          <button type="button" class="v2-quick-btn is-narrator" data-append-kind="narrator" ${state.busy ? 'disabled' : ''}>+ Narrator</button>
          <span class="v2-quick-sync-meta">${liveGraph.nodes.length} Nodes · ${liveGraph.charBlockLinks.size} Chars</span>
          <select id="v2ComposeFontSelect" class="v2-mini-select" aria-label="Manuscript font" title="Manuscript font">
            <option value="serif" ${composeFont === 'serif' ? 'selected' : ''}>Serif (Newsreader)</option>
            <option value="sans" ${composeFont === 'sans' ? 'selected' : ''}>Sans (Inter)</option>
            <option value="mono" ${composeFont === 'mono' ? 'selected' : ''}>Mono (Script)</option>
          </select>
          <button type="button" class="v2-btn ${state.composeSplitGraph ? 'v2-btn-accent' : ''}" id="v2ComposeSplitToggle" aria-pressed="${state.composeSplitGraph ? 'true' : 'false'}" style="margin-left:auto">
            ${state.composeSplitGraph ? '◫ Close Graph &amp; Rhythm' : '◫ Split Graph &amp; Rhythm'}
          </button>
        </div>
        ${(() => {
          const cMode = ep?.canon_tag?.mode || 'canon';
          const ttCarrier = ep?.canon_tag?.tt_carrier;
          const carriers = state.formGraph?.junctions || [];
          return `
            <div class="v2-canon-mode-strip" role="group" aria-label="Multi-draft canon tagging">
              <span class="v2-canon-strip-label">CANON TAG</span>
              ${[
                ['canon', 'Canon'],
                ['non_canon', 'Non-Canon'],
                ['alternate_canon', 'Alternate Canon'],
                ['time_travel_canon', 'Time-Travel Canon'],
              ].map(([id, lbl]) => `
                <button type="button" class="v2-canon-pill is-${id} ${cMode === id ? 'is-active' : ''}" data-set-canon-mode="${id}" aria-pressed="${cMode === id}" ${state.busy ? 'disabled' : ''}>${lbl}</button>
              `).join('')}
              ${cMode === 'time_travel_canon' ? `
                <label class="v2-tt-carrier">
                  Carrier:
                  <select id="v2TtCarrierSelect" aria-label="Time-Travel Carrier Character">
                    ${carriers.map((item) => `<option value="${escapeHtml(item.character_id)}" ${ttCarrier === item.character_id ? 'selected' : ''}>${escapeHtml(item.label || item.character_id)}</option>`).join('')}
                  </select>
                </label>
              ` : ''}
            </div>
          `;
        })()}
      ` : ''}

      ${highlighting ? '<p class="v2-highlight-instruction" role="status">Highlighter on · select across passages, then choose protection. Press Esc to return to writing.</p>' : ''}

      ${showOnboarding ? `
        <section class="v2-onboarding-card" aria-label="Unprocessed script onboarding">
          <div>
            <strong>Unprocessed raw script detected</strong>
            <p>
              Find passages and known speakers while keeping the saved text and protection settings.
            </p>
          </div>
          <button type="button" class="v2-btn v2-btn-accent" id="v2AutoSplitBtn" ${state.busy ? 'disabled' : ''}>
            Auto-Split into Typed Blocks
          </button>
        </section>
      ` : ''}

      ${(() => {
        const craft = computeClientCraftTelemetry(blocks, state);
        return `
          <div class="v2-compositor-telemetry" role="status" aria-label="5-Pass Compositor & Anti-Slop Telemetry">
            <span class="v2-comp-label">5-PASS COMPOSITOR</span>
            <span class="v2-comp-pass is-done">P1 Ingest</span>
            <span class="v2-comp-pass is-done">P2 Graph</span>
            <span class="v2-comp-pass is-done">P3 Bind</span>
            <span class="v2-comp-pass is-done">P4 Slots</span>
            <span class="v2-comp-pass is-done">P5 Splice</span>
            <span class="v2-comp-metric ${craft.tier}" title="Composite Anti-Slop Score (lower is cleaner)">Slop ${craft.slopScore}</span>
            <span class="v2-comp-metric ${craft.burstiness >= 4 ? 'is-clean' : 'is-warn'}" title="Sentence-length burstiness sigma (target >= 4.0)">σ ${craft.burstiness.toFixed(1)}</span>
            <span class="v2-comp-metric is-lib" title="Indexed Style Library Corpus">${craft.libraryBooks} Books</span>
            <span class="v2-comp-metric is-lock" title="0% LOCK Dialogue Spans Intact">0% LOCK (${craft.lockedCount})</span>
          </div>
        `;
      })()}

      <div class="v2-block-list v2-notebook-page" data-compose-font="${escapeHtml(composeFont)}" ${highlighting ? 'data-mask-surface contenteditable="plaintext-only" role="textbox" aria-readonly="true" aria-multiline="true" aria-label="Notebook passage selection" tabindex="0" spellcheck="false"' : ''}>
        ${blocks
          .map((b, i) => {
            const kind = b.kind || 'unresolved';
            const kindLabel = kind === 'scene-heading' ? 'SCENE' : kind === 'stage-direction' ? 'STAGE' : kind.toUpperCase();
            const { cue, body } = displayedBlock(b);
            const speakerLabel = cue || speakerName(b, state, kindLabel);
            const showPicker = !highlighting && speakerPicker && speakerPicker.blockId === b.id;
            const continuation = kind === 'narrator' && blocks[i-1]?.kind === 'narrator' && !separatorBlock(b) && !separatorBlock(blocks[i-1]);
            const numbers = lineNumbersFor(body, logicalLine);
            logicalLine += Math.max(1, body.replace(/(?:\r\n|\r|\n)+$/,'').split(/\r\n|\r|\n/).length);
            const blockStart = offsets[i] || 0;
            const blockEnd = blockStart + codePoints(cue) + codePoints(body);
            const maskPct = blockMaskWeight(nb, blockStart, blockEnd);
            const isExpanded = state.expandedBreakdownBlockId === b.id;
            const charGroups = isExpanded ? groupBlockByCharacter(b, body, cue ? speakerLabel : b.speaker) : [];
            const isJunctionBlock = kind === 'branch-junction' || /\b(?:junction|three little bitches|peter griffin)\b/i.test(body);
            const activeJ = state.activeJunctionRoute || 'j2';
            const infPills = blockInfluencePills(b, body, maskPct, state);
            const linkedBeatId = liveGraph.blockToBeatId.get(b.id) || '';
            const linkedNode = linkedBeatId ? liveGraph.nodes.find((n) => n.id === linkedBeatId) : null;
            const mentionedChars = (kind === 'character' || kind === 'stage-direction')
              ? detectMentionedCharacters(`${b.speaker || ''} ${speakerLabel} ${body}`, sampleChars)
              : [];
            if (separatorBlock(b)) {
              return `
                <div class="v2-node-row v2-compose-divider-row" data-block-id="${escapeHtml(b.id)}">
                  <div class="v2-node-gutter" contenteditable="false" aria-hidden="true">
                    <span class="v2-divider-node-dot"></span>
                  </div>
                  <div class="v2-compose-divider-rule"><span>SCENE BREAK</span></div>
                </div>
              `;
            }
            const rowKindCls = kind === 'stage-direction' || kind === 'scene-heading' ? 'is-stage-direction'
              : kind === 'character' ? 'is-character'
              : kind === 'unresolved' ? 'is-world-law'
              : 'is-narrator';
            const gutterLabel = kind === 'scene-heading' ? 'SCENE'
              : kind === 'stage-direction' ? 'STAGE DIR'
              : kind === 'character' ? `CHAR: ${String(speakerLabel).split(' ')[0].slice(0, 8)}`
              : kind === 'unresolved' ? 'RAW BLOCK'
              : 'NARRATIVE';
            return `
              <div class="v2-node-row v2-compose-node-row ${rowKindCls}">
                <div class="v2-node-gutter" contenteditable="false" aria-hidden="true">
                  <div class="v2-gutter-circle ${rowKindCls}"><span>${escapeHtml(gutterLabel)}</span></div>
                  <span class="v2-gutter-connector"></span>
                </div>
                <div class="v2-node-card-shell">
              <article class="v2-block-card ${continuation ? 'is-continuation' : ''} ${separatorBlock(b) ? 'is-divider' : ''}" data-kind="${escapeHtml(kind)}" data-block-id="${escapeHtml(b.id)}">
                <div class="v2-block-header" contenteditable="false" data-dblclick-breakdown="${escapeHtml(b.id)}" title="Double-click header for full script breakdown by character">
                  <span class="v2-speaker-tag" data-kind="${escapeHtml(kind)}"${cue ? ' data-source-cue' : ''}><span class="v2-speaker-slash" aria-hidden="true"></span>${escapeHtml(speakerLabel)}</span>
                  ${linkedBeatId ? `<button type="button" class="v2-gutter-node-pill" data-jump-story-beat="${escapeHtml(linkedBeatId)}" title="Inspect node in Split Story Graph">◈ ${escapeHtml(linkedBeatId)} · ${escapeHtml(linkedNode?.nodeType || 'BEAT')}</button>` : ''}
                  ${mentionedChars.map((mc) => `<button type="button" class="v2-char-node-pill" data-jump-char-graph="${escapeHtml(mc.id)}" title="Open ${escapeHtml(mc.name)} in Character Graph">◇ ${escapeHtml(mc.name.split(' ')[0])}</button>`).join('')}
                  ${infPills ? `<span class="v2-inf-strip">${infPills}</span>` : ''}
                  ${isJunctionBlock ? `<button type="button" class="v2-mini-btn v2-junc-pill" data-toggle-junction="${escapeHtml(b.id)}" title="Switch active Story Junction route">${activeJ === 'j1' ? '◇ J1 · Peter' : '◇ J2 · 3 Bitches'}</button>` : ''}
                  <button type="button" class="v2-mask-pill ${maskPct >= 100 ? 'is-locked' : ''}" data-cycle-block-lock="${escapeHtml(b.id)}" data-current-lock="${maskPct}" title="Click to cycle protection (100% -> 50% -> 25%)">${maskPct >= 100 ? '0% LOCK 🔒' : `${100 - maskPct}% UPLIFT`}</button>
                  ${highlighting ? '' : `<button type="button" class="v2-mini-btn v2-compose-add-below" data-insert-below="${escapeHtml(b.id)}" ${locked || state.busy ? 'disabled' : ''}>+ Below</button><details class="v2-block-actions"><summary aria-label="Passage actions">···</summary><div class="v2-block-menu">
                    <select class="v2-mini-select" data-block-kind="${escapeHtml(b.id)}" aria-label="Block ${i + 1} type" ${locked || state.busy ? 'disabled' : ''}>
                      ${['unresolved', 'narrator', 'scene-heading', 'character', 'stage-direction']
                        .map((k) => `<option value="${k}" ${kind === k ? 'selected' : ''}>${k}</option>`)
                        .join('')}
                    </select>
                    <button type="button" class="v2-mini-btn" data-open-speaker="${escapeHtml(b.id)}" ${locked || state.busy ? 'disabled' : ''}>Speaker</button>
                    ${kind === 'character' && b.speaker ? `<button type="button" class="v2-mini-btn" data-jump-char-graph="${escapeHtml(b.speaker)}" data-jump-char-form="${escapeHtml(b.form || '')}" title="Open character in shared graph">Graph ↗</button>` : ''}
                    <button type="button" class="v2-mini-btn" data-split-block="${escapeHtml(b.id)}" ${locked || state.busy ? 'disabled' : ''}>Split</button>
                    <button type="button" class="v2-mini-btn" data-merge-block="${escapeHtml(b.id)}" ${locked || state.busy || i === blocks.length - 1 ? 'disabled' : ''}>Merge ↓</button>
                  </div></details>`}
                </div>
                <div class="v2-block-editor-grid">
                  <div class="v2-line-gutter" contenteditable="false" data-first-line="${numbers.split('\n')[0]}" aria-hidden="true">${numbers}</div>
                  ${highlighting ? `<div class="v2-mask-body" data-mask-body="${i}">${maskedBody(body, offsets[i]+codePoints(cue), masks)}</div>` : `<textarea
                    class="v2-block-textarea"
                    data-block-text="${escapeHtml(b.id)}"
                    data-block-index="${i}"
                    aria-label="${escapeHtml(`${speakerLabel} passage ${i + 1}`)}"
                    ${locked ? 'readonly' : ''}
                  >
${escapeHtml(body)}</textarea>`}
                </div>
                ${showPicker ? renderSpeakerPicker(b, speakerPicker.options) : ''}
                ${isExpanded && charGroups.length ? `
                  <div class="v2-char-breakdown" contenteditable="false">
                    <div class="v2-char-breakdown-head">📜 Script Breakdown by Character (Double-click header to collapse)</div>
                    ${charGroups.map(([spk, lines]) => `
                      <div class="v2-char-breakdown-group">
                        <strong>${escapeHtml(spk)} (${lines.length})</strong>
                        ${lines.map((ln) => `<p>${escapeHtml(ln)}</p>`).join('')}
                      </div>
                    `).join('')}
                  </div>
                ` : ''}
              </article>
                </div>
              </div>`;
          })
          .join('')}
      </div>

      ${highlighting ? '' : `<div class="v2-append-row">
        <button type="button" class="v2-append-btn" data-append-kind="narrator" ${locked || state.busy ? 'disabled' : ''}>+ Narrator</button>
        <button type="button" class="v2-append-btn" data-append-kind="scene-heading" ${locked || state.busy ? 'disabled' : ''}>+ Scene</button>
        <button type="button" class="v2-append-btn" data-append-kind="character" ${locked || state.busy ? 'disabled' : ''}>+ Character</button>
        <button type="button" class="v2-append-btn" data-append-kind="stage-direction" ${locked || state.busy ? 'disabled' : ''}>+ Stage direction</button>
        ${!locked && !showOnboarding ? `<button type="button" class="v2-append-btn v2-prepare-btn" data-run-cook ${state.busy ? 'disabled' : ''}>Prepare structure</button>` : ''}
      </div>`}
    </div>
  `;
}

function renderSpeakerPicker(block, options) {
  const chars = options?.characters || [];
  return `
    <div class="v2-speaker-picker">
      <label>
        Character
        <select id="v2SpeakerChar">
          <option value="">None</option>
          ${chars
            .map(
              (c) => `<option value="${escapeHtml(c.id || c)}" ${(c.id || c) === block.speaker ? 'selected' : ''}>${escapeHtml(c.label || c.id || c)}</option>`
            )
            .join('')}
        </select>
      </label>
      <label>
        Form
        <input id="v2SpeakerForm" value="${escapeHtml(block.form || '')}" placeholder="optional form">
      </label>
      <button type="button" class="v2-mini-btn" data-apply-speaker="${escapeHtml(block.id)}">Apply</button>
      <button type="button" class="v2-mini-btn" data-cancel-speaker>Cancel</button>
      <div class="v2-inline-char-spawn">
        <input id="v2InlineNewCharName" type="text" placeholder="+ New character name...">
        <select id="v2InlineNewCharTier" aria-label="New character tier">
          <option value="major">Major</option>
          <option value="minor">Minor</option>
        </select>
        <button type="button" class="v2-mini-btn v2-btn-accent" data-inline-spawn-char="${escapeHtml(block.id)}">Spawn &amp; Bind</button>
      </div>
    </div>
  `;
}

export function renderProtectionInspector(nb, fullText, state) {
  const masks = nb?.masks || [];
  const stale = nb?.stale_masks || [];
  const isStale = Boolean(nb?.stale);

  return `
    ${isStale ? `
      <div class="v2-notice" data-tone="err">
        Notebook protection is out of sync with the timeline revision.
        <button type="button" class="v2-mini-btn" id="v2SyncNotebookBtn" style="margin-top:6px">Sync notebook</button>
      </div>
    ` : ''}

    <div class="v2-inspector-card">
      <h2>Selection masks (${masks.length})</h2>
      ${masks.length === 0 ? '<p class="v2-stage-sub" style="color:var(--ink-muted-on-chrome)">No selection masks saved.</p>' : ''}
      <div class="v2-mask-list">
        ${masks
          .map((m, idx) => {
            const snippet = [...fullText].slice(m.start, m.end).join('').replace(/\s+/g, ' ').trim() || `[${m.start}..${m.end}]`;
            const val = m.value ?? m.weight ?? 100;
            return `
              <div class="v2-mask-item">
                <div class="v2-mask-snippet" title="${escapeHtml(snippet)}">${escapeHtml(snippet)}</div>
                <div class="v2-mask-controls">
                  <select data-mask-weight="${idx}" aria-label="Mask ${idx + 1} protection" ${state.busy ? 'disabled' : ''}>
                    ${[25, 50, 75, 100].map((w) => `<option value="${w}" ${val === w ? 'selected' : ''}>${w}%</option>`).join('')}
                  </select>
                  <button type="button" class="v2-mini-btn" data-mask-remove="${idx}" ${state.busy ? 'disabled' : ''}>Remove</button>
                </div>
              </div>`;
          })
          .join('')}
      </div>
    </div>

    ${(() => {
      const blocks = state.draftBlocks || nb?.blocks || [];
      const junctions = state.formGraph?.junctions || [];
      const charLinks = summarizeCharacterLinks(blocks, junctions);
      const linkedCount = charLinks.filter((c) => c.linked).length;
      const missingCount = charLinks.length - linkedCount;
      return `
        <div class="v2-inspector-card">
          <h2>Stage 1 · Timing &amp; Perception</h2>
          ${renderActStructure(state, { compact: true })}
        </div>
        <div class="v2-inspector-card">
          <h2>Block ↔ Character Graph (${linkedCount}/${charLinks.length})</h2>
          <p class="v2-hint">Every character block connects to a shared character node so graph data and canon profiles inform generation.</p>
          ${missingCount > 0 ? `
            <div style="margin-top:8px">
              <button type="button" class="v2-btn v2-btn-accent" id="v2SyncAllCharsBtn" ${state.busy ? 'disabled' : ''}>+ Sync All Missing (${missingCount}) to Graph</button>
            </div>
          ` : ''}
          ${charLinks.length === 0 ? '<p class="v2-hint">No character blocks yet. Use Auto-Split or set a block type to character.</p>' : `
            <div class="v2-char-link-list">
              ${charLinks.map((c) => `
                <div class="v2-char-link-row">
                  <div class="v2-char-link-meta">
                    <strong>${escapeHtml(c.label)}</strong>
                    <span class="v2-char-link-sub">${c.count} block(s) · <span class="v2-char-link-badge ${c.linked ? '' : 'is-missing'}">${c.linked ? 'In graph' : 'Missing node'}</span></span>
                  </div>
                  ${c.linked
                    ? `<button type="button" class="v2-mini-btn" data-jump-char-graph="${escapeHtml(c.character_id)}" data-jump-char-form="${escapeHtml(c.form_id || '')}">Graph ↗</button>`
                    : `<button type="button" class="v2-mini-btn" data-add-char-to-graph="${escapeHtml(c.key)}" data-add-char-label="${escapeHtml(c.label)}" ${state.busy ? 'disabled' : ''}>+ Add to Graph</button>`}
                </div>
              `).join('')}
            </div>
          `}
        </div>
      `;
    })()}

    ${stale.length > 0 ? `
      <div class="v2-inspector-card">
        <h2>Stale masks (${stale.length})</h2>
        <div class="v2-mask-list">
          ${stale
            .map(
              (m) => `
            <div class="v2-mask-item">
              <div class="v2-mask-snippet">${escapeHtml(m.text || m.id || 'Stale range')}</div>
              <button type="button" class="v2-mini-btn" data-dismiss-stale="${escapeHtml(m.id)}" ${state.busy ? 'disabled' : ''}>Dismiss</button>
            </div>`
            )
            .join('')}
        </div>
      </div>
    ` : ''}
  `;
}

export function bindComposeEvents({ store, api, onReload, onOpenCharacterGraph, onOpenStoryBeat, onPrepare, onLiveBlocksChange }) {
  document.getElementById('v2ComposeFontSelect')?.addEventListener('change', (e) => {
    const val = e.target.value;
    try { localStorage.setItem('noir-compose-font', val); } catch (_) {}
    const page = document.querySelector('.v2-notebook-page');
    if (page) page.dataset.composeFont = val;
  });
  document.querySelectorAll('[data-dblclick-breakdown]').forEach((hdr) => {
    hdr.addEventListener('dblclick', (e) => {
      if (e.target.closest('details, button, select')) return;
      const bid = hdr.dataset.dblclickBreakdown;
      store.set({ expandedBreakdownBlockId: store.get().expandedBreakdownBlockId === bid ? null : bid });
    });
  });
  document.querySelectorAll('[data-toggle-junction]').forEach((btn) => {
    btn.addEventListener('click', (e) => {
      e.stopPropagation();
      const next = store.get().activeJunctionRoute === 'j1' ? 'j2' : 'j1';
      store.set({
        activeJunctionRoute: next,
        notice: { text: `Active Junction route switched to ${next === 'j1' ? 'J1 · Big Booty Peter Griffin' : 'J2 · Three Little Bitches'}.`, tone: 'ok' },
      });
    });
  });
  const blocks = store.get().draftBlocks || store.get().episodeState?.notebook?.blocks || [];
  const offsets = blockOffsetMap(blocks);
  const surface = document.querySelector('[data-mask-surface]');
  const mount = document.getElementById('v2MaskMount');
  selectionListeners?.abort();
  selectionListeners = new AbortController();
  const listen = { signal: selectionListeners.signal };
  let selectionOwner = null;
  let liveGraphTimer = null;
  listen.signal.addEventListener('abort', () => clearTimeout(liveGraphTimer), { once: true });

  function placeMaskPopup(popup, rect) {
    const viewport = window.visualViewport;
    const leftEdge = (viewport?.offsetLeft ?? 0) + 8;
    const topEdge = (viewport?.offsetTop ?? 0) + 8;
    const width = viewport?.width ?? innerWidth;
    const height = viewport?.height ?? innerHeight;
    popup.style.maxWidth = `${Math.max(0, width - 16)}px`;
    popup.style.maxHeight = `${Math.max(0, height - 16)}px`;
    const right = leftEdge + width - 16 - popup.offsetWidth;
    const bottom = topEdge + height - 16 - popup.offsetHeight;
    const below = rect.bottom + 8;
    const top = below <= bottom ? below : rect.top - popup.offsetHeight - 8;
    popup.style.left = `${Math.max(leftEdge, Math.min(right, rect.left))}px`;
    popup.style.top = `${Math.max(topEdge, Math.min(bottom, top))}px`;
  }

  function clearSelectionCards() {
    document.querySelectorAll('.v2-block-card.is-in-selection').forEach((card) => card.classList.remove('is-in-selection'));
  }

  function closeMaskPopup(restoreFocus = false) {
    const wasPopup = mount?.querySelector('.v2-mask-popover');
    mount?.replaceChildren();
    clearSelectionCards();
    if (restoreFocus && wasPopup && selectionOwner?.isConnected) selectionOwner.focus({ preventScroll: true });
    selectionOwner = null;
  }

  function showMaskPopup(range, rect) {
    const current = store.get();
    const nb = current.episodeState?.notebook;
    if (!mount?.isConnected || !nb || nb.stale || current.dirty || current.busy ||
        current.episodeState?.episode?.status !== 'draft' || !range || range.start >= range.end) return;
    selectionOwner = range.blockId
      ? document.querySelector(`[data-block-text="${CSS.escape(range.blockId)}"]`) : surface;
    const selection = range.blockId && selectionOwner ? [selectionOwner.selectionStart, selectionOwner.selectionEnd] : null;
    clearSelectionCards();
    if (Array.isArray(range.blockIndices)) {
      const cards = [...document.querySelectorAll('.v2-block-card')];
      range.blockIndices.forEach((idx) => cards[idx]?.classList.add('is-in-selection'));
    }
    store.setQuiet({ selectionRange: range });
    const exactly = nb.masks?.find(m => m.start === range.start && m.end === range.end);
    const charCount = range.end - range.start;
    const spanLabel = Array.isArray(range.blockIndices) && range.blockIndices.length > 1
      ? `Blocks ${range.blockIndices[0] + 1}-${range.blockIndices.at(-1) + 1} · ${charCount} chars`
      : `${charCount} chars`;
    mount.innerHTML = `<div class="v2-mask-popover" role="group" aria-label="Protect selection">
      <div class="v2-mask-title">${(current.theme === 'racing' || current.theme === 'noir-v4') ? renderTrack(exactly?.value || nb.default_protection, true) : ''}
        <strong>Protect selection</strong><button type="button" class="v2-btn" data-mask-close aria-label="Close protection popup">×</button></div>
      <div class="v2-mask-span-meta">${escapeHtml(spanLabel)}</div>
      <div class="v2-mask-choices">${[25,50,75,100].map(w => `<button type="button" class="v2-btn" data-highlight-weight="${w}" aria-label="Protect ${w}%" aria-pressed="${w === exactly?.value}">${w}%</button>`).join('')}</div>
      ${exactly ? '<button type="button" class="v2-mask-clear" data-remove-current>Use document protection</button>' : ''}
    </div>`;
    const popup = mount.firstElementChild;
    placeMaskPopup(popup, rect);
    popup.querySelector('[data-mask-close]').onclick = () => closeMaskPopup(true);
    popup.addEventListener('pointerdown', e => { if (e.target.closest('button')) e.preventDefault(); });
    async function save(weight) {
      const prefix = store.get();
      if (prefix.episodeState?.notebook !== nb || prefix.dirty) return;
      const exact = [...composeText(nb.blocks)].slice(range.start, range.end).join('');
      if (!exact) return;
      const hash = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(exact));
      const sha256 = Array.from(new Uint8Array(hash), b => b.toString(16).padStart(2,'0')).join('');
      if (store.get().episodeState?.notebook !== nb || store.get().dirty) return;
      const masks = (nb.masks || []).filter(m => !(m.start === range.start && m.end === range.end));
      if (weight) masks.push({ id: crypto.randomUUID(), start: range.start, end: range.end, value: weight, sha256 });
      await saveNotebookState(store, api, nb.blocks, nb.default_protection, masks, weight ? `Selection protected at ${weight}%.` : 'Selection uses document protection.');
      const after = store.get();
      if (after.episodeId !== current.episodeId || after.view !== current.view) return;
      const editor = selection ? document.querySelector(`[data-block-text="${CSS.escape(range.blockId)}"]`)
        : document.querySelector('[data-mask-surface]');
      editor?.focus({ preventScroll: true });
      if (selection && editor) editor.setSelectionRange(...selection);
      const saved = after.episodeState?.notebook;
      if (weight && after.theme === 'racing' && saved?.masks.some(m => m.start===range.start && m.end===range.end && m.value===weight)) {
        const status=document.getElementById('v2MaskMount');
        if (status) {
          status.innerHTML=`<div class="v2-mask-feedback" role="status">${renderTrack(weight,true)}<strong>${weight}% protection saved</strong></div>`;
          animateTrack(status.querySelector('[data-track]'),weight);
          const feedback=status.firstElementChild;
          setTimeout(()=>feedback.remove(),Math.max(1400,PLAY_MS[weight]+300));
        }
      }
    }
    popup.querySelectorAll('[data-highlight-weight]').forEach(btn => btn.onclick = () => save(Number(btn.dataset.highlightWeight)));
    const remove=popup.querySelector('[data-remove-current]');
    if (remove) remove.onclick=()=>save(0);
  }

  const reposition = () => {
    const popup = mount?.querySelector('.v2-mask-popover');
    if (!popup || !selectionOwner?.isConnected) return;
    const active = window.getSelection();
    const rect = selectionOwner === surface && active?.rangeCount && surface.contains(active.anchorNode)
      ? active.getRangeAt(0).getBoundingClientRect() : selectionOwner.getBoundingClientRect();
    placeMaskPopup(popup, rect);
  };
  window.addEventListener('resize', reposition, listen);
  window.visualViewport?.addEventListener('resize', reposition, listen);

  if (surface) {
    for (const event of ['beforeinput','paste','drop']) surface.addEventListener(event,e=>e.preventDefault());
    function measure(node, endpoint, local) {
      if (!node.contains(endpoint)) return null;
      const range = document.createRange();
      range.selectNodeContents(node);
      range.setEnd(endpoint,local);
      return range.toString().length;
    }
    const captureAcross = () => {
      if (!surface.isConnected) return;
      const selected = document.getSelection();
      if (!selected?.rangeCount || selected.isCollapsed) return;
      const range=selected.getRangeAt(0);
      if (!surface.contains(range.startContainer) || !surface.contains(range.endContainer)) return;
      const intersections = [...surface.querySelectorAll('[data-mask-body]')].filter(part=>range.intersectsNode(part));
      if (!intersections.length) return;
      const a=intersections[0], b=intersections.at(-1), ai=Number(a.dataset.maskBody), bi=Number(b.dataset.maskBody);
      const start = offsets[ai]+blockPosition(blocks[ai],measure(a,range.startContainer,range.startOffset) ?? 0);
      const end = offsets[bi]+blockPosition(blocks[bi],measure(b,range.endContainer,range.endOffset) ?? b.textContent.length);
      const rect=range.getClientRects().length ? range.getClientRects()[range.getClientRects().length-1] : range.getBoundingClientRect();
      const blockIndices = intersections.map(part => Number(part.dataset.maskBody));
      showMaskPopup({start, end, blockIndices}, rect);
    };
    surface.addEventListener('pointerup',captureAcross);
    surface.addEventListener('keyup',e=> { if (e.shiftKey || e.key.startsWith('Arrow') || e.key.toLowerCase()==='a') captureAcross(); });
  }
  document.addEventListener('keydown',e => {
    if (e.defaultPrevented || !mount?.isConnected) return;
    if ((e.ctrlKey && e.key.toLowerCase() === 'm') || (e.altKey && e.key.toLowerCase() === 'h')) {
      const tool = document.getElementById('v2HighlightTool');
      if (tool) {
        e.preventDefault();
        tool.click();
        return;
      }
    }
    const choice = mount.querySelector('[data-highlight-weight]');
    if (e.key === 'Tab' && !e.shiftKey && choice && document.activeElement === selectionOwner) {
      e.preventDefault();
      choice.focus({ preventScroll: true });
      return;
    }
    if (e.key !== 'Escape') return;
    if (mount.firstElementChild) { e.preventDefault(); closeMaskPopup(true); return; }
    if (!surface?.isConnected) return;
    store.set({ highlightMode:false,selectionRange:null });
    const tool = document.getElementById('v2HighlightTool');
    (tool?.getClientRects().length ? tool : document.getElementById('v2NavigationToggle'))?.focus({ preventScroll: true });
  },listen);
  document.addEventListener('pointerdown',e => {
    if (mount?.isConnected && !mount.contains(e.target)) closeMaskPopup();
  },listen);

  // Batch initial height calculation into a single read pass to avoid N synchronous reflows
  const textareas = [...document.querySelectorAll('.v2-block-textarea')];
  if (textareas.length) {
    function fitNotebook() {
      for (const ta of textareas) ta.style.height = 'auto';
      const heights = textareas.map((ta) => Math.max(26, ta.scrollHeight));
      textareas.forEach((ta, i) => {
        ta.style.height = `${heights[i]}px`;
      });
    }
    fitNotebook();
    let width = textareas[0].clientWidth;
    const reflow = new ResizeObserver(() => {
      if (!textareas[0].isConnected) { reflow.disconnect(); return; }
      const next = textareas[0].clientWidth;
      if (next === width) return;
      width = next;
      fitNotebook();
      reposition();
    });
    reflow.observe(textareas[0]);
    listen.signal.addEventListener('abort', () => reflow.disconnect(), { once: true });
  }

  // Live textarea edits update draftBlocks & footer stats without losing cursor focus
  textareas.forEach((ta) => {
    const syncSingleHeight = () => {
      ta.style.height = 'auto';
      ta.style.height = `${Math.max(26, ta.scrollHeight)}px`;
    };

    ta.addEventListener('input', () => {
      syncSingleHeight();
      const idx = Number(ta.dataset.blockIndex);
      const cur = store.get();
      const base = (cur.draftBlocks || cur.episodeState?.notebook?.blocks || []).map((b) => ({ ...b }));
      if (base[idx]) {
        const { cue, body, separator } = displayedBlock(base[idx]);
        base[idx].text = cue + retainSourceText(body, ta.value) + separator;
      }
      const gutter = ta.previousElementSibling;
      if (gutter) gutter.textContent = lineNumbersFor(ta.value, Number(gutter.dataset.firstLine || 1));
      store.setQuiet({ draftBlocks: base, dirty: true, selectionRange: null });
      if (onLiveBlocksChange) {
        clearTimeout(liveGraphTimer);
        liveGraphTimer = setTimeout(() => onLiveBlocksChange(), 200);
      }
      document.querySelectorAll('[data-highlight-weight]').forEach((button) => { button.disabled = true; });
      const saveBtn = document.getElementById('v2SaveBtn');
      if (saveBtn) {
        saveBtn.disabled = false;
        saveBtn.textContent = 'Save changes';
      }
    });

    const captureSelection = (event) => {
      const idx = Number(ta.dataset.blockIndex);
      if (store.get().dirty) return;
      const start = blockPosition(blocks[idx], ta.selectionStart);
      const end = blockPosition(blocks[idx], ta.selectionEnd);
      if (end > start) {
        const baseOffset = offsets[idx] || 0;
        const nextRange = {
          blockId: ta.dataset.blockText,
          localStart: start,
          localEnd: end,
          start: baseOffset + start,
          end: baseOffset + end,
        };
        const box = ta.getBoundingClientRect();
        showMaskPopup(nextRange, event.type === 'mouseup' ? {left:event.clientX,top:event.clientY,bottom:event.clientY+4} : box);
      }
    };
    ta.addEventListener('mouseup', captureSelection);
    ta.addEventListener('keyup', (event) => {
      if (event.key !== 'Escape' && event.key !== 'Tab') captureSelection(event);
    });
  });

  // Block kind change
  document.querySelectorAll('[data-block-kind]').forEach((sel) => {
    sel.addEventListener('change', async () => {
      const id = sel.dataset.blockKind;
      const { episodeState, draftBlocks } = store.get();
      const nb = episodeState?.notebook;
      if (!nb) return;
      const nextBlocks = (draftBlocks || nb.blocks).map((b) => (b.id === id ? { ...b, kind: sel.value } : b));
      await saveNotebookState(store, api, nextBlocks, nb.default_protection, nb.masks || [], `Updated block type to ${sel.value}.`);
    });
  });

  // 1-Click Block Lock Cycle (100 -> 50 -> 25 -> 100)
  document.querySelectorAll('[data-cycle-block-lock]').forEach((btn) => {
    btn.addEventListener('click', async () => {
      const bid = btn.dataset.cycleBlockLock;
      const cur = Number(btn.dataset.currentLock || 100);
      const next = cur >= 100 ? 50 : cur >= 50 ? 25 : 100;
      const s = store.get();
      const nb = s.episodeState?.notebook;
      if (!nb || s.dirty || s.busy) return;
      const list = s.draftBlocks || nb.blocks;
      const idx = list.findIndex((b) => b.id === bid);
      if (idx < 0) return;
      const off = blockOffsetMap(list);
      const start = off[idx] || 0;
      const end = start + codePoints(list[idx].text || '');
      if (end <= start) return;
      const exact = [...composeText(list)].slice(start, end).join('');
      const hash = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(exact));
      const sha256 = Array.from(new Uint8Array(hash), (b) => b.toString(16).padStart(2, '0')).join('');
      const masks = (nb.masks || []).filter((m) => !(m.start === start && m.end === end));
      if (next !== nb.default_protection) masks.push({ id: crypto.randomUUID(), start, end, value: next, sha256 });
      window.NOIR_FX?.trigger?.('LOCK_FREEZE', { el: btn, badgeText: next >= 100 ? '0% Lock' : `${100 - next}% Uplift` });
      await saveNotebookState(store, api, list, nb.default_protection, masks, `Block protection set to ${next}%.`);
    });
  });

  // 1-Click + Below Block Insert
  document.querySelectorAll('[data-insert-below]').forEach((btn) => {
    btn.addEventListener('click', async () => {
      const bid = btn.dataset.insertBelow;
      const s = store.get();
      const nb = s.episodeState?.notebook;
      if (!nb || s.busy) return;
      const list = s.draftBlocks || nb.blocks;
      const idx = list.findIndex((b) => b.id === bid);
      if (idx < 0) return;
      const newBlock = { id: crypto.randomUUID(), kind: 'narrator', text: '\n\n' };
      const nextBlocks = [...list.slice(0, idx + 1), newBlock, ...list.slice(idx + 1)];
      window.NOIR_FX?.trigger?.('EXECUTE_CONFIRM', { el: btn, badgeText: '+ Block' });
      await saveNotebookState(store, api, nextBlocks, nb.default_protection, nb.masks || [], 'Inserted narrator block below.');
    });
  });

  // Split block at cursor
  document.querySelectorAll('[data-split-block]').forEach((btn) => {
    btn.addEventListener('click', async () => {
      const blockId = btn.dataset.splitBlock;
      const ta = document.querySelector(`.v2-block-textarea[data-block-text="${CSS.escape(blockId)}"]`);
      const block = blocks.find((item) => item.id === blockId);
      const source = block?.text || '';
      const offset = ta ? blockPosition(block, ta.selectionStart) : 0;
      const { episodeState } = store.get();
      const nb = episodeState?.notebook;
      if (!nb || offset <= 0 || offset >= codePoints(source)) {
        store.set({ notice: { text: 'Place the cursor inside the block text (not at start/end) to split.', tone: 'err' } });
        return;
      }
      await runNotebookOp(store, () =>
        api.notebookAction({ action: 'split', episode: episodeState.episode.id, revision: nb.revision, timeline_revision: nb.timeline_revision, block: blockId, offset }),
        'Split block at cursor.'
      );
    });
  });

  // Merge block with next
  document.querySelectorAll('[data-merge-block]').forEach((btn) => {
    btn.addEventListener('click', async () => {
      const firstId = btn.dataset.mergeBlock;
      const { episodeState } = store.get();
      const nb = episodeState?.notebook;
      if (!nb) return;
      const idx = nb.blocks.findIndex((b) => b.id === firstId);
      const second = nb.blocks[idx + 1];
      if (!second) return;
      await runNotebookOp(store, () =>
        api.notebookAction({ action: 'merge', episode: episodeState.episode.id, revision: nb.revision, timeline_revision: nb.timeline_revision, first: firstId, second: second.id }),
        'Merged blocks.'
      );
    });
  });

  // Append block (auto-wires Story Graph node + Character Graph link live)
  document.querySelectorAll('[data-append-kind]').forEach((btn) => {
    btn.addEventListener('click', async () => {
      const kind = btn.dataset.appendKind;
      const { episodeState } = store.get();
      const nb = episodeState?.notebook;
      if (!nb) return;
      const syncMsg = kind === 'stage-direction'
        ? 'Created Stage Direction → auto-wired vertical STAGE node in Story Graph.'
        : kind === 'character'
        ? 'Created Character block → linked to Story Graph & Character Graph.'
        : kind === 'scene-heading'
        ? 'Created Scene Heading → spawned vertical SCENE node in Story Graph.'
        : 'Created Narrator block → attached to active Story Graph Beat.';
      const updatedNb = await runNotebookOp(store, () =>
        api.notebookAction({ action: 'append-block', episode: episodeState.episode.id, revision: nb.revision, timeline_revision: nb.timeline_revision, kind }),
        syncMsg
      );
      if (updatedNb?.blocks?.length) {
        const created = updatedNb.blocks[updatedNb.blocks.length - 1];
        if (kind === 'character' && created?.id) {
          try {
            const options = await api.notebookAction({ action: 'speaker-options', episode: episodeState.episode.id, block: created.id });
            store.set({ speakerPicker: { blockId: created.id, options } });
          } catch (_) {}
        }
        requestAnimationFrame(() => {
          const card = created?.id ? document.querySelector(`.v2-block-card[data-block-id="${CSS.escape(created.id)}"]`) : null;
          if (!card) return;
          card.scrollIntoView({ behavior: 'smooth', block: 'center' });
          card.classList.add('is-sync-pulse');
          setTimeout(() => card.classList.remove('is-sync-pulse'), 1800);
          const speakerSel = document.getElementById('v2SpeakerChar');
          if (kind === 'character' && speakerSel) {
            speakerSel.focus();
          } else {
            card.querySelector('.v2-block-textarea')?.focus();
          }
        });
      }
    });
  });

  document.querySelectorAll('[data-jump-story-beat]').forEach((btn) => {
    btn.addEventListener('click', () => {
      onOpenStoryBeat?.(btn.dataset.jumpStoryBeat);
    });
  });

  // Speaker options & bind
  document.querySelectorAll('[data-open-speaker]').forEach((btn) => {
    btn.addEventListener('click', async () => {
      const blockId = btn.dataset.openSpeaker;
      const { episodeState } = store.get();
      try {
        const options = await api.notebookAction({ action: 'speaker-options', episode: episodeState.episode.id, block: blockId });
        store.set({ speakerPicker: { blockId, options } });
      } catch (err) {
        store.set({ notice: { text: err.message, tone: 'err' } });
      }
    });
  });

  document.querySelector('[data-cancel-speaker]')?.addEventListener('click', () => {
    store.set({ speakerPicker: null });
  });

  document.querySelector('[data-apply-speaker]')?.addEventListener('click', async (e) => {
    const blockId = e.currentTarget.dataset.applySpeaker;
    const character = document.getElementById('v2SpeakerChar')?.value || null;
    const form = document.getElementById('v2SpeakerForm')?.value?.trim() || null;
    const { episodeState } = store.get();
    const nb = episodeState?.notebook;
    if (!nb) return;
    await runNotebookOp(store, async () => {
      const res = await api.notebookAction({
        action: 'bind-speaker',
        episode: episodeState.episode.id,
        revision: nb.revision,
        timeline_revision: nb.timeline_revision,
        block: blockId,
        character,
        form,
      });
      store.setQuiet({ speakerPicker: null });
      return res;
    }, 'Updated block speaker.');
  });

  // Inline + New Major/Minor Character Spawn & Bind (Strict Referential Integrity)
  document.querySelector('[data-inline-spawn-char]')?.addEventListener('click', async (e) => {
    const blockId = e.currentTarget.dataset.inlineSpawnChar;
    const rawName = document.getElementById('v2InlineNewCharName')?.value?.trim();
    const tier = document.getElementById('v2InlineNewCharTier')?.value || 'minor';
    const cur = store.get();
    const ep = cur.episodeState?.episode;
    const nb = cur.episodeState?.notebook;
    const fg = cur.formGraph;
    if (!rawName || !ep || !nb || !fg) {
      store.set({ notice: { text: 'Enter a character name to spawn into Character Graph.', tone: 'warn' } });
      return;
    }
    store.set({ busy: true });
    try {
      const label = `${rawName} (${tier === 'major' ? 'Major' : 'Minor'})`;
      const nextFg = await api.formGraphAction({
        action: 'add_character',
        episode: ep.id,
        revision: fg.revision,
        label,
      });
      const created = (nextFg.junctions || []).find((j) => (j.label || '').toLowerCase() === label.toLowerCase())
        || (nextFg.junctions || [])[nextFg.junctions.length - 1];
      store.setQuiet({ formGraph: nextFg, speakerPicker: null });
      await runNotebookOp(store, () => api.notebookAction({
        action: 'bind-speaker',
        episode: ep.id,
        revision: nb.revision,
        timeline_revision: nb.timeline_revision,
        block: blockId,
        character: created?.character_id || rawName,
        form: created?.forms?.[0]?.id || null,
      }), `Spawned ${rawName} (${tier}) in Character Graph & bound to block.`);
    } catch (err) {
      store.set({ busy: false, notice: { text: err.message, tone: 'err' } });
    }
  });

  const saveCanonTag = async (mode, carrier = null) => {
    const current = store.get();
    const { episode, scope } = current.episodeState || {};
    if (!episode || current.busy) return;
    const ttCarrier = mode === 'time_travel_canon'
      ? carrier || episode.canon_tag?.tt_carrier || current.formGraph?.junctions?.[0]?.character_id : null;
    if (mode === 'time_travel_canon' && !ttCarrier) {
      store.set({ notice: { text: 'Choose a saved character for the time-travel carrier.', tone: 'warn' } });
      return;
    }
    store.set({ busy: true });
    try {
      const { canon_tag } = await api.episodeCommand({ action: 'canon.tag.save', episode: episode.id,
        project: scope?.project_id, universe: scope?.universe_id, timeline_revision: episode.head,
        canon_revision: episode.canon_tag?.revision ?? 0, mode, tt_carrier: ttCarrier });
      const latest = store.get();
      if (latest.episodeId === episode.id && latest.episodeState?.episode?.head === episode.head) {
        store.set({ busy: false, episodeState: { ...latest.episodeState, episode: { ...latest.episodeState.episode, canon_tag } },
          notice: { text: 'Saved canon mode.', tone: 'ok' } });
      }
    } catch (error) {
      if (store.get().episodeId === episode.id) store.set({ busy: false, notice: { text: error.message, tone: 'err' } });
    }
  };
  document.querySelectorAll('[data-set-canon-mode]').forEach((btn) => {
    btn.addEventListener('click', () => void saveCanonTag(btn.dataset.setCanonMode));
  });
  document.getElementById('v2TtCarrierSelect')?.addEventListener('change', (event) => {
    void saveCanonTag('time_travel_canon', event.target.value);
  });

  // Mask weight / remove / dismiss stale / sync
  document.querySelectorAll('[data-mask-weight]').forEach((sel) => {
    sel.addEventListener('change', async () => {
      const idx = Number(sel.dataset.maskWeight);
      const { episodeState } = store.get();
      const nb = episodeState?.notebook;
      if (!nb) return;
      const masks = (nb.masks || []).map((m, i) => (i === idx ? { ...m, value: Number(sel.value) } : m));
      await saveNotebookState(store, api, nb.blocks, nb.default_protection, masks, 'Updated selection mask.');
    });
  });

  document.querySelectorAll('[data-mask-remove]').forEach((btn) => {
    btn.addEventListener('click', async () => {
      const idx = Number(btn.dataset.maskRemove);
      const { episodeState } = store.get();
      const nb = episodeState?.notebook;
      if (!nb) return;
      const masks = (nb.masks || []).filter((_, i) => i !== idx);
      await saveNotebookState(store, api, nb.blocks, nb.default_protection, masks, 'Removed selection mask.');
    });
  });

  document.querySelectorAll('[data-dismiss-stale]').forEach((btn) => {
    btn.addEventListener('click', async () => {
      const mask = btn.dataset.dismissStale;
      const { episodeState } = store.get();
      const nb = episodeState?.notebook;
      if (!nb) return;
      await runNotebookOp(store, () =>
        api.notebookAction({ action: 'dismiss-stale', episode: episodeState.episode.id, revision: nb.revision, timeline_revision: nb.timeline_revision, mask }),
        'Dismissed stale mask.'
      );
    });
  });

  document.getElementById('v2SyncNotebookBtn')?.addEventListener('click', () => onReload());

  document.getElementById('v2AutoSplitBtn')?.addEventListener('click', () => onPrepare?.());

  // Jump from a character block or Block <-> Character Graph panel to Character Junctions
  document.querySelectorAll('[data-jump-char-graph]').forEach((btn) => {
    btn.addEventListener('click', () => {
      onOpenCharacterGraph?.(btn.dataset.jumpCharGraph, btn.dataset.jumpCharForm || null);
    });
  });

  // Add missing script character to shared form graph and bind matching blocks
  document.querySelectorAll('[data-add-char-to-graph]').forEach((btn) => {
    btn.addEventListener('click', async () => {
      const cur = store.get();
      const nb = cur.episodeState?.notebook;
      if (!cur.episodeId || !cur.formGraph) return;
      const label = btn.dataset.addCharLabel || btn.dataset.addCharToGraph;
      const key = btn.dataset.addCharToGraph;
      store.set({ busy: true });
      try {
        const nextGraph = await api.formGraphAction({
          action: 'add_character',
          episode: cur.episodeId,
          revision: cur.formGraph.revision,
          label,
        });
        store.set({ busy: false, formGraph: nextGraph });
        const junctions = nextGraph.junctions || [];
        const match = matchSpeakerToJunction(key, junctions) || matchSpeakerToJunction(label, junctions);
        if (nb && match) {
          const baseBlocks = cur.draftBlocks || nb.blocks || [];
          let changed = false;
          const nextBlocks = baseBlocks.map((b) => {
            if (b.kind !== 'character') return b;
            const bKey = String(b.speaker || '').toLowerCase();
            if (bKey === key || bKey === match.character_id) {
              changed = true;
              return { ...b, speaker: match.character_id, form: b.form || match.form_id };
            }
            return b;
          });
          if (changed) {
            await saveNotebookState(
              store,
              api,
              nextBlocks,
              nb.default_protection,
              nb.masks || [],
              `Added ${match.label} to shared character graph & linked blocks.`
            );
            return;
          }
        }
        store.set({ notice: { text: `Added ${label} to shared character graph.`, tone: 'ok' } });
      } catch (err) {
        store.set({ busy: false, notice: { text: err.message, tone: 'err' } });
      }
    });
  });

  // Sync all unrepresented script characters into shared form graph and bind blocks
  document.getElementById('v2SyncAllCharsBtn')?.addEventListener('click', async () => {
    const cur = store.get();
    const nb = cur.episodeState?.notebook;
    if (!cur.episodeId || !cur.formGraph || !nb) return;
    const baseBlocks = cur.draftBlocks || nb.blocks || [];
    const missing = summarizeCharacterLinks(baseBlocks, cur.formGraph.junctions || []).filter((c) => !c.linked);
    if (!missing.length) return;
    store.set({ busy: true });
    try {
      let fg = cur.formGraph;
      for (const item of missing) {
        fg = await api.formGraphAction({
          action: 'add_character',
          episode: cur.episodeId,
          revision: fg.revision,
          label: item.label,
        });
      }
      store.set({ formGraph: fg });
      const junctions = fg.junctions || [];
      let changed = false;
      const nextBlocks = baseBlocks.map((b) => {
        if (b.kind !== 'character' || !b.speaker) return b;
        const match = matchSpeakerToJunction(b.speaker, junctions);
        if (match && (b.speaker !== match.character_id || !b.form)) {
          changed = true;
          return { ...b, speaker: match.character_id, form: b.form || match.form_id };
        }
        return b;
      });
      if (changed) {
        await saveNotebookState(
          store,
          api,
          nextBlocks,
          nb.default_protection,
          nb.masks || [],
          `Synced ${missing.length} character(s) to shared character graph.`
        );
      } else {
        store.set({ busy: false, notice: { text: `Synced ${missing.length} character(s) to shared character graph.`, tone: 'ok' } });
      }
    } catch (err) {
      store.set({ busy: false, notice: { text: err.message, tone: 'err' } });
    }
  });

  document.getElementById('v2ComposeApplyDraftBtn')?.addEventListener('click', async () => {
    const s = store.get();
    const ep = s.episodeState?.episode;
    const nb = s.episodeState?.notebook;
    const draftId = s.activeDraftId;
    if (!ep || !nb || !draftId) return;
    store.set({ busy: true });
    try {
      await api.draftsAction({
        action: 'use',
        episode: ep.id,
        branch: ep.branch,
        draft: draftId,
        revision: nb.revision,
        timeline_revision: nb.timeline_revision,
      });
      await onReload(ep.id);
      store.set({ busy: false, activeDraftId: null, notice: { text: 'Applied draft to current script.', tone: 'ok' } });
    } catch (err) {
      store.set({ busy: false, notice: { text: err.message, tone: 'err' } });
    }
  });

  document.getElementById('v2ComposeExitDraftBtn')?.addEventListener('click', () => {
    store.set({ activeDraftId: null });
  });
}

export async function saveNotebookState(store, api, blocks, defaultProtection, masks, okMessage) {
  const { episodeState } = store.get();
  const nb = episodeState?.notebook;
  if (!nb) return;
  await runNotebookOp(store, () =>
    api.notebookAction({
      action: 'save',
      episode: episodeState.episode.id,
      revision: nb.revision,
      timeline_revision: nb.timeline_revision,
      blocks,
      default_protection: defaultProtection,
      masks,
    }),
    okMessage
  );
}

async function runNotebookOp(store, fn, okMessage) {
  if (store.get().dirty) {
    store.set({ notice: { text: 'Save your text edits before changing the notebook structure or protection.', tone: 'warn' } });
    return null;
  }
  store.set({ busy: true });
  try {
    const nb = await fn();
    const cur = store.get();
    store.set({
      busy: false,
      dirty: false,
      draftBlocks: null,
      selectionRange: null,
      episodeState: { ...cur.episodeState, notebook: nb },
      notice: { text: `${okMessage} (nb r${nb.revision})`, tone: 'ok' },
    });
    return nb;
  } catch (err) {
    store.set({ busy: false, notice: { text: err.message, tone: 'err' } });
    return null;
  }
}
