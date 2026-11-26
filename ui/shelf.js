/* Noir Fiction Studio — Unprocessed Text Shelf & Connected Gutter-Node Word Processor
 * Pure frontend UI mockup demonstrating:
 * 1) Raw Story Vault ("Text Shelf") for already-written unprocessed text
 * 2) Connected Gutter-Node + Tinted Block Word Processor (auto-formats any raw text + full font/rich editing)
 * 3) Precision Node Data Injection + WORLD_LAWS.noir & Graph-Readiness Telemetry
 */
import { noirVfx } from './vfx_engine.js';

const SHELF_STORAGE_KEY = 'noir-raw-text-shelf-v1';
const PREP_DRAFT_KEY = 'noir-prep-draft-v1';
const PREP_LAW_KEY = 'noir-prep-worldlaws-v1';

const TITLE_OVERRIDES = new Map([
  ['Antigravity 1.0 · Prequel', 'The Kidney Stays in the Picture · American Foxy Momma Prequel'],
  ['Antigravity 1.0 - Prequel', 'The Kidney Stays in the Picture · American Foxy Momma Prequel'],
  ['Hot Scoomp · Antigravity 1.0', 'Hot Scoomp · Part 3'],
  ['Hot Scoomp - Antigravity 1.0', 'Hot Scoomp · Part 3'],
]);

export function displayEpisodeTitle(titleOrId) {
  const raw = String(titleOrId || '').trim();
  return TITLE_OVERRIDES.get(raw) || raw;
}

const DEFAULT_SHELF_ITEMS = [
  {
    id: 'shelf-kidney-raw',
    title: 'The Kidney Stays in the Picture (Raw Prequel)',
    status: 'RAW',
    source: 'prequel_notes.txt',
    tags: ['Prequel', 'Button Nightclub', 'Sade'],
    excerpt:
      '[SCENE: INT. THE BUTTON NIGHTCLUB - NIGHT]\n[STAGE] Neon amber sweeps across the cracked vinyl booth. Rainee Sade slides a damp bar napkin across the table.\nThe booth had been sticky since the second set started, smelling of spilled ginger ale, cheap perfume, and static.\n[DIALOGUE: SADE] "Sign it before the DJ drops the next track, or the deal stays on your tab."\n[DIALOGUE: BECKY] "You really think she reads the fine print when the bass hits?"\n[WORLD_LAW: @law:kidney-price]\n[MIND/FORM] Sade hides her fox tail curl under the booth; Becky watches the door.',
  },
  {
    id: 'shelf-hot-scoomp-p3',
    title: 'Hot Scoomp · Part 3 (Unprocessed Pages)',
    status: 'STAGED',
    source: 'hot_scoomp_part3_draft.docx',
    tags: ['4-Part Special', 'Part 3', 'Awakening'],
    excerpt:
      '[SCENE: EXT. ICE CREAM PARLOR - NIGHT]\n[STAGE] Haley freezes mid-step as the static in her ears sharpens into voices two booths away.\n[DIALOGUE: HALEY] "Wait — did you hear what she just thought?"\n[WORLD_LAW: @law:hot-scoomp-part3-awakening]',
  },
  {
    id: 'shelf-world-laws-raw',
    title: 'Button Nightclub & Fox Heritage Rules (Notes)',
    status: 'IN GRAPH',
    source: 'world_rules_scratch.md',
    tags: ['World Laws', 'Hard Invariant'],
    excerpt:
      '@LAW id="kidney-price" status="HARD" — Any deal signed at The Button Nightclub binds physical form until repaid before dawn.',
  },
];

export const NOIR_WORD_SCHEMA = [
  { id: 'stage-direction', label: 'Stage Direction', hotkey: '1', graphTarget: 'Story DAG + Blocking', badge: 'STAGE DIRECTION', short: 'STAGE', snippet: '[STAGE] ' },
  { id: 'narrator', label: 'Narrative Block', hotkey: '2', graphTarget: 'Prose Style & Pacing', badge: 'NARRATIVE BLOCK', short: 'BODY', snippet: '[TEXT_BODY] ' },
  { id: 'character', label: 'Character Dialogue', hotkey: '3', graphTarget: 'Character Graph + 0% Lock', badge: 'CHARACTER', short: 'TALK', snippet: '[DIALOGUE: SPEAKER] "' },
  { id: 'scene-heading', label: 'Scene Header', hotkey: '4', graphTarget: 'Chronology & Spatial Node', badge: 'SCENE HEADER', short: 'SCENE', snippet: '[SCENE: INT. LOCATION - NIGHT]\n' },
  { id: 'mind-form', label: 'Mind / Form', hotkey: '5', graphTarget: 'Character Mind + Switchyard', badge: 'MIND / FORM', short: 'MIND', snippet: '[MIND/FORM] ' },
  { id: 'world-law', label: 'World Law Ref', hotkey: '6', graphTarget: 'Canon Gate (@law:id)', badge: 'WORLD LAW', short: '@LAW', snippet: '[WORLD_LAW: @law:kidney-price]\n' },
  { id: 'beat-turn', label: 'Beat Turn', hotkey: '7', graphTarget: 'Causal DAG Edge', badge: 'BEAT TURN', short: 'TURN', snippet: '[BEAT_TURN] ' },
];

const DEFAULT_WORLD_LAWS_DOC = `@LAW id="kidney-price" status="HARD" scope="universe"
@TITLE: The Kidney Stays in the Picture
@RULE: Any deal signed at The Button Nightclub binds the signer's physical form until repaid.
@TRIGGERS: [contract_signed, transformation_cue]
@CHARACTERS: [sade, becky, clarie]
@EXCEPTIONS: Nullified only if the original napkin contract is burned before dawn.

@LAW id="hot-scoomp-part3-awakening" status="HARD" scope="episode:hot-scoomp-p3"
@TITLE: Hot Scoomp 4-Part Special · Part 3 Awakening Gate
@RULE: Haley is already married to Jeff here; her fox awakening triggers aversion before Part 4 fallout.
@TRIGGERS: [awakening_cut_2, holly_contact]
@CHARACTERS: [haley, jeff, holly, francine]`;

function esc(value) {
  return String(value ?? '')
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;');
}

export function loadShelfItems() {
  try {
    const raw = localStorage.getItem(SHELF_STORAGE_KEY);
    if (raw) {
      const parsed = JSON.parse(raw);
      if (Array.isArray(parsed) && parsed.length) return parsed;
    }
  } catch (_) {}
  return DEFAULT_SHELF_ITEMS;
}

function saveShelfItems(items) {
  try {
    localStorage.setItem(SHELF_STORAGE_KEY, JSON.stringify(items));
  } catch (_) {}
}

function loadPrepDraft(fallback) {
  try {
    const val = localStorage.getItem(PREP_DRAFT_KEY);
    if (typeof val === 'string' && val.length) return val;
  } catch (_) {}
  return fallback;
}

function loadLawDoc() {
  try {
    const val = localStorage.getItem(PREP_LAW_KEY);
    if (typeof val === 'string' && val.length) return val;
  } catch (_) {}
  return DEFAULT_WORLD_LAWS_DOC;
}

function wordCount(text) {
  const m = String(text || '').trim().match(/\S+/g);
  return m ? m.length : 0;
}

/**
 * Automatically converts ANY raw or tagged text into Connected Gutter-Nodes.
 */
export function parseTextToPrepNodes(rawText) {
  const lines = String(rawText || '').replace(/\r\n?/g, '\n').split('\n');
  const nodes = [];
  let idx = 0;
  for (const rawLine of lines) {
    const line = rawLine.trim();
    if (!line) continue;
    idx += 1;
    const id = `pnode-${idx}`;
    const sceneTag = line.match(/^\[SCENE:\s*(.+?)\]$/i);
    if (sceneTag || /^(INT\.|EXT\.|INT\/EXT\.)\s+/i.test(line)) {
      nodes.push({ id, kind: 'scene-heading', speaker: '', text: (sceneTag ? sceneTag[1] : line).toUpperCase() });
      continue;
    }
    const stageTag = line.match(/^\[STAGE\]\s*(.+)$/i);
    if (stageTag || (/^\[.+\]$/.test(line) && !/^\[(TEXT_BODY|DIALOGUE|MIND|WORLD_LAW|BEAT_TURN|SCENE)/i.test(line)) || /^\(.+\)$/.test(line)) {
      const cleaned = stageTag ? stageTag[1] : line;
      nodes.push({ id, kind: 'stage-direction', speaker: '', text: cleaned.startsWith('[') ? cleaned : `[${cleaned.replace(/^\(|\)$/g, '')}]` });
      continue;
    }
    const dlgTag = line.match(/^\[DIALOGUE:\s*([^\]]+)\]\s*(.+)$/i) || line.match(/^([A-Z][A-Z0-9 .'-]{1,22}):\s*(.+)$/);
    if (dlgTag) {
      nodes.push({ id, kind: 'character', speaker: dlgTag[1].trim().toUpperCase(), text: dlgTag[2].trim() });
      continue;
    }
    const mindTag = line.match(/^\[MIND\/FORM\]\s*(.+)$/i);
    if (mindTag) {
      nodes.push({ id, kind: 'mind-form', speaker: '', text: mindTag[1].trim() });
      continue;
    }
    const lawTag = line.match(/^\[WORLD_LAW:\s*(.+?)\]$/i) || line.match(/^(@LAW\b.*)$/i);
    if (lawTag) {
      nodes.push({ id, kind: 'world-law', speaker: '', text: lawTag[1].trim() });
      continue;
    }
    const turnTag = line.match(/^\[BEAT_TURN\]\s*(.+)$/i);
    if (turnTag) {
      nodes.push({ id, kind: 'beat-turn', speaker: '', text: turnTag[1].trim() });
      continue;
    }
    const bodyTag = line.match(/^\[TEXT_BODY\]\s*(.+)$/i);
    nodes.push({ id, kind: 'narrator', speaker: '', text: (bodyTag ? bodyTag[1] : line).trim() });
  }
  if (!nodes.length) {
    nodes.push({ id: 'pnode-1', kind: 'scene-heading', speaker: '', text: 'INT. NEW SCENE - NIGHT' });
    nodes.push({ id: 'pnode-2', kind: 'stage-direction', speaker: '', text: '[Click here to write stage directions...]' });
    nodes.push({ id: 'pnode-3', kind: 'narrator', speaker: '', text: 'Write or paste any raw story text, then click Auto-Format.' });
  }
  return nodes;
}

export function serializePrepNodesToText(nodes) {
  return (nodes || []).map((n) => {
    const t = String(n.text || '').trim();
    if (n.kind === 'scene-heading') return `[SCENE: ${t}]`;
    if (n.kind === 'stage-direction') return `[STAGE] ${t.replace(/^\[|\]$/g, '')}`;
    if (n.kind === 'character') return `[DIALOGUE: ${n.speaker || 'SPEAKER'}] ${t}`;
    if (n.kind === 'mind-form') return `[MIND/FORM] ${t}`;
    if (n.kind === 'world-law') return `[WORLD_LAW: ${t}]`;
    if (n.kind === 'beat-turn') return `[BEAT_TURN] ${t}`;
    return t;
  }).join('\n');
}

function analyzePrepSignals(nodes, lawDoc) {
  const count = (k) => nodes.filter((n) => n.kind === k).length;
  const lawDefs = (String(lawDoc || '').match(/@LAW\s+id="([^"]+)"/g) || []).length;
  const words = wordCount(nodes.map((n) => `${n.speaker || ''} ${n.text || ''}`).join(' '));
  return {
    scenes: count('scene-heading'),
    stages: count('stage-direction'),
    dialogues: count('character'),
    minds: count('mind-form'),
    lawRefs: count('world-law'),
    turns: count('beat-turn'),
    lawDefs,
    words,
  };
}

export function renderLeftRailShelf(state) {
  const items = loadShelfItems();
  const activeId = state.activeShelfId || items[0]?.id || '';
  const addOpen = Boolean(state.shelfAddOpen);
  return `
    <div class="v2-shelf-wrap">
      <div class="v2-shelf-actions">
        <button type="button" class="v2-btn v2-btn-accent" id="v2ShelfAddToggleBtn" aria-expanded="${addOpen}">
          ${addOpen ? '− Close' : '+ Store Raw Text'}
        </button>
      </div>
      ${addOpen ? `
        <form id="v2ShelfAddForm" class="v2-shelf-add-form">
          <input type="text" id="v2ShelfTitleInput" placeholder="Story or scene title..." required maxlength="80">
          <textarea id="v2ShelfTextInput" rows="4" placeholder="Paste already-written unprocessed text here..." required></textarea>
          <button type="submit" class="v2-btn v2-btn-accent">Save to Text Shelf</button>
        </form>
      ` : ''}
      <div class="v2-shelf-list" role="list" aria-label="Unprocessed Text Shelf">
        ${items.map((item) => {
          const active = item.id === activeId;
          const statusCls = item.status === 'IN GRAPH' ? 'is-graph' : item.status === 'STAGED' ? 'is-staged' : 'is-raw';
          return `
            <article class="v2-shelf-card ${active ? 'is-active' : ''}" role="listitem" data-shelf-id="${esc(item.id)}">
              <div class="v2-shelf-card-head">
                <strong>${esc(item.title)}</strong>
                <span class="v2-shelf-pill ${statusCls}">${esc(item.status)}</span>
              </div>
              <div class="v2-shelf-meta">${esc(item.source || 'pasted-draft.txt')} · ${wordCount(item.excerpt)}w</div>
              <p class="v2-shelf-excerpt">${esc(item.excerpt)}</p>
              <div class="v2-shelf-card-btns">
                <button type="button" class="v2-mini-btn" data-shelf-open="${esc(item.id)}">Open in Word Prep →</button>
                <button type="button" class="v2-mini-btn" data-shelf-law="${esc(item.id)}">Tag @LAW</button>
              </div>
            </article>
          `;
        }).join('')}
      </div>
    </div>
  `;
}

function nodeBadgeLabel(node) {
  if (node.kind === 'stage-direction') return 'STAGE\nDIRECTION';
  if (node.kind === 'narrator') return 'NARRATIVE\nBLOCK';
  if (node.kind === 'character') return `CHARACTER:\n${node.speaker || 'SPEAKER'}`;
  if (node.kind === 'mind-form') return 'MIND /\nFORM';
  if (node.kind === 'world-law') return 'WORLD\nLAW';
  if (node.kind === 'beat-turn') return 'BEAT\nTURN';
  return 'SCENE\nHEADER';
}

export function renderWordPrepWorkspace(state) {
  const items = loadShelfItems();
  const activeItem = state.loadedShelfSnippet || items.find((x) => x.id === state.activeShelfId) || items[0];
  const prepText = state.prepDraftText ?? loadPrepDraft(activeItem?.excerpt || '');
  const nodes = Array.isArray(state.prepNodes) ? state.prepNodes : parseTextToPrepNodes(prepText);
  const lawDoc = state.prepLawDoc ?? loadLawDoc();
  const prepMode = state.prepViewMode || 'visual'; // 'visual' | 'raw'
  const fontFam = state.prepFontFamily || 'serif';
  const fontSize = state.prepFontSize || '15';
  const selectedId = state.selectedPrepNodeId || nodes.find((n) => n.kind !== 'scene-heading')?.id || nodes[0]?.id || '';
  const selectedNode = nodes.find((n) => n.id === selectedId) || nodes[0];
  const addKind = state.prepAddKind || 'stage-direction';
  const sig = analyzePrepSignals(nodes, lawDoc);

  return `
    <div class="v2-prep-studio">
      <header class="v2-prep-hero">
        <div>
          <span class="v2-word-eyebrow">NOIR WORD PROCESSOR · CONNECTED GUTTER-NODE SCRIPT PREP</span>
          <h1>Prepare Any Text into Story &amp; Character Graph Nodes</h1>
          <p>Paste raw prose or click any node in the left gutter to inject World Laws, Character Mind/Form state, or Noise Locks directly on that beat.</p>
        </div>
        <div class="v2-prep-hero-stats">
          <div><span>WORDS</span><strong>${sig.words}</strong></div>
          <div><span>NODES</span><strong>${nodes.length}</strong></div>
          <div><span>DIALOGUE</span><strong>${sig.dialogues}</strong></div>
          <div><span>@LAW REFS</span><strong>${sig.lawRefs}</strong></div>
        </div>
      </header>

      <div class="v2-prep-grid">
        <section class="v2-prep-editor-col" aria-label="Connected Gutter-Node Word Processor">
          <div class="v2-prep-font-toolbar" role="toolbar" aria-label="Font and node formatting">
            <select id="v2PrepFontFamily" aria-label="Font family">
              <option value="serif" ${fontFam === 'serif' ? 'selected' : ''}>Serif (Newsreader)</option>
              <option value="sans" ${fontFam === 'sans' ? 'selected' : ''}>Sans (Inter / Segoe)</option>
              <option value="mono" ${fontFam === 'mono' ? 'selected' : ''}>Screenplay Mono</option>
            </select>
            <select id="v2PrepFontSize" aria-label="Font size">
              <option value="13" ${fontSize === '13' ? 'selected' : ''}>13px</option>
              <option value="15" ${fontSize === '15' ? 'selected' : ''}>15px</option>
              <option value="17" ${fontSize === '17' ? 'selected' : ''}>17px</option>
            </select>
            <button type="button" class="v2-fmt-btn" data-fmt-cmd="bold" title="Bold (Ctrl+B)"><strong>B</strong></button>
            <button type="button" class="v2-fmt-btn" data-fmt-cmd="italic" title="Italic (Ctrl+I)"><em>I</em></button>
            <button type="button" class="v2-fmt-btn" data-fmt-cmd="underline" title="Underline (Ctrl+U)"><u>U</u></button>
            <span class="v2-fmt-sep" aria-hidden="true"></span>
            <select id="v2PrepAddKindSelect" aria-label="Choose node type to add">
              ${NOIR_WORD_SCHEMA.map((t) => `<option value="${esc(t.id)}" ${addKind === t.id ? 'selected' : ''}>+ ${esc(t.label)}</option>`).join('')}
            </select>
            <button type="button" class="v2-btn v2-btn-accent" id="v2PrepAddNodeBtn">+ Add Node</button>
            <button type="button" class="v2-btn" id="v2PrepAutoFormatBtn" title="Automatically format any pasted text into connected nodes">✨ Auto-Format</button>
            <div class="v2-prep-mode-switch" role="group" aria-label="Editor view mode">
              <button type="button" class="v2-mini-btn" data-prep-mode="visual" aria-pressed="${prepMode === 'visual'}">Visual Nodes</button>
              <button type="button" class="v2-mini-btn" data-prep-mode="raw" aria-pressed="${prepMode === 'raw'}">Raw .noir</button>
            </div>
          </div>

          <div class="v2-prep-sheet v2-prep-paper-canvas" data-font="${esc(fontFam)}" style="--prep-font-size:${esc(fontSize)}px">
            <div class="v2-prep-sheet-bar">
              <span><strong>Active Source:</strong> ${esc(activeItem?.title || 'Untitled Raw Draft')}</span>
              <div class="v2-word-head-btns">
                <button type="button" class="v2-btn" id="v2PrepSaveShelfBtn">Save to Shelf</button>
                <button type="button" class="v2-btn v2-btn-accent" id="v2PrepSendComposeBtn">Send Prepped → Compose / Graph</button>
              </div>
            </div>

            ${prepMode === 'raw' ? `
              <textarea
                id="v2PrepEditorText"
                class="v2-prep-textarea"
                spellcheck="true"
                aria-label="Raw script text for auto-formatting"
                placeholder="Paste any raw prose, screenplay, or notes here, then click ✨ Auto-Format or switch to Visual Nodes..."
              >${esc(prepText)}</textarea>
            ` : `
              <div class="v2-node-flow" id="v2PrepNodeFlow">
                ${nodes.map((node, index) => {
                  const isSelected = node.id === selectedId;
                  if (node.kind === 'scene-heading') {
                    return `
                      <div class="v2-node-scene-row ${isSelected ? 'is-selected' : ''}" data-prep-node="${esc(node.id)}">
                        <div class="v2-node-scene-head" contenteditable="true" data-node-edit="${esc(node.id)}">${esc(node.text)}</div>
                        <div class="v2-node-row-tools">
                          <button type="button" class="v2-mini-btn" data-insert-after="${index}" title="Add node below">+ Node</button>
                          <button type="button" class="v2-mini-btn" data-delete-node="${esc(node.id)}" title="Remove">✕</button>
                        </div>
                      </div>
                    `;
                  }
                  const motif = node.kind === 'stage-direction'
                    ? '>>> STAGE'
                    : node.kind === 'narrator'
                    ? '◆ R&D PROSE'
                    : node.kind === 'character'
                    ? `◉ COMMS · ${esc(node.speaker || 'CAST')}`
                    : node.kind === 'world-law'
                    ? '⛨ HARD LAW'
                    : node.kind === 'mind-form'
                    ? '◎ OVERDRIVE MIND'
                    : '⚑ BEAT TURN';
                  return `
                    <div class="v2-node-row is-${esc(node.kind)} ${isSelected ? 'is-selected' : ''}" data-prep-node="${esc(node.id)}" data-node-kind-row="${esc(node.kind)}">
                      <div class="v2-node-gutter">
                        <button type="button" class="v2-gutter-circle is-${esc(node.kind)}" data-select-node="${esc(node.id)}" aria-pressed="${isSelected}" title="Click for precision data injection">
                          <span>${esc(nodeBadgeLabel(node)).replaceAll('\n', '<br>')}</span>
                        </button>
                        <span class="v2-gutter-connector" aria-hidden="true"></span>
                      </div>
                      <div class="v2-node-card-shell">
                        <div class="v2-node-card is-${esc(node.kind)}">
                          <div class="v2-node-card-controls">
                            <span class="v2-node-motif">${motif}</span>
                            <select class="v2-node-kind-select" data-node-kind="${esc(node.id)}" aria-label="Block node type">
                              ${NOIR_WORD_SCHEMA.map((t) => `<option value="${esc(t.id)}" ${node.kind === t.id ? 'selected' : ''}>${esc(t.label)}</option>`).join('')}
                            </select>
                            ${node.kind === 'character' ? `<input type="text" class="v2-node-speaker-input" data-node-speaker="${esc(node.id)}" value="${esc(node.speaker || '')}" placeholder="CHARACTER NAME">` : ''}
                            ${node.noise_mode ? `<span class="v2-node-inj-pill">${esc(node.noise_mode)}% NOISE</span>` : ''}
                            ${node.injected_law ? `<span class="v2-node-inj-pill is-law">@${esc(node.injected_law)}</span>` : ''}
                            <div class="v2-node-row-tools">
                              <button type="button" class="v2-mini-btn" data-insert-after="${index}" title="Add chosen node below">+ Below</button>
                              <button type="button" class="v2-mini-btn" data-delete-node="${esc(node.id)}" title="Remove node">✕</button>
                            </div>
                          </div>
                          <div class="v2-node-body" contenteditable="true" data-node-edit="${esc(node.id)}">${esc(node.text)}</div>
                        </div>
                      </div>
                    </div>
                  `;
                }).join('')}
              </div>
            `}
          </div>
        </section>

        <aside class="v2-prep-laws-col" aria-label="Precision Data Injection &amp; World Laws">
          <div class="v2-prep-card">
            <div class="v2-worldlaw-doc-head">
              <strong>PRECISION DATA INJECTION</strong>
              <span class="v2-shelf-pill is-staged">${esc(selectedNode?.kind || 'none')}</span>
            </div>
            <p class="v2-prep-inject-sub">Selected node: <strong>${esc(selectedNode?.speaker ? `CHARACTER: ${selectedNode.speaker}` : (selectedNode?.kind || 'None'))}</strong></p>
            <div class="v2-prep-inject-btns">
              <button type="button" class="v2-mini-btn" data-inject-noise="0">Inject 0% Lock</button>
              <button type="button" class="v2-mini-btn" data-inject-noise="50">Inject 50% Bal</button>
              <button type="button" class="v2-mini-btn" data-inject-law="kidney-price">+ Bind @kidney-price</button>
              <button type="button" class="v2-mini-btn" data-inject-law="hot-scoomp-part3-awakening">+ Bind @awakening</button>
            </div>
          </div>

          <div class="v2-prep-card">
            <div class="v2-worldlaw-doc-head">
              <strong>GRAPH READINESS TELEMETRY</strong>
              <span class="v2-shelf-pill is-graph">${sig.scenes + sig.stages + sig.dialogues + sig.turns} Signals</span>
            </div>
            <div class="v2-prep-signals">
              ${[
                ['scenes', 'Scene Headers', sig.scenes],
                ['stages', 'Stage Directions', sig.stages],
                ['dialogues', 'Dialogue Lines', sig.dialogues],
                ['minds', 'Mind / Form Shifts', sig.minds],
                ['lawRefs', 'World Law Refs', sig.lawRefs],
                ['turns', 'Causal Beat Turns', sig.turns],
              ].map(([key, label, val]) => {
                const lit = Math.min(6, Math.max(0, Number(val) || 0));
                return `
                  <div class="v2-prep-signal-cell" data-telemetry-key="${key}">
                    <div class="v2-prep-signal-row">
                      <span>${label}</span>
                      <strong>${val}<em class="v2-prep-signal-delta">+1</em></strong>
                    </div>
                    <div class="v2-seg-bar" aria-hidden="true">
                      ${[0, 1, 2, 3, 4, 5].map((i) => `<i class="v2-seg-pip ${i < lit ? 'is-lit' : ''}"></i>`).join('')}
                    </div>
                  </div>
                `;
              }).join('')}
            </div>
          </div>

          <div class="v2-prep-card">
            <div class="v2-worldlaw-doc-head">
              <strong>WORLD_LAWS.noir (${sig.lawDefs} Rules)</strong>
            </div>
            <textarea
              id="v2PrepLawDocText"
              class="v2-prep-law-textarea"
              spellcheck="false"
              aria-label="Tagged WORLD_LAWS.noir document"
            >${esc(lawDoc)}</textarea>
          </div>
        </aside>
      </div>
    </div>
  `;
}

export function bindShelfAndWordMockup({ store, api, changeView, onPromoted }) {
  const syncNodes = (nextNodes, quiet = false) => {
    const serialized = serializePrepNodesToText(nextNodes);
    try { localStorage.setItem(PREP_DRAFT_KEY, serialized); } catch (_) {}
    const patch = { prepNodes: nextNodes, prepDraftText: serialized };
    if (quiet) store.setQuiet(patch);
    else store.set(patch);
  };

  document.querySelectorAll('[data-rail-tab]').forEach((btn) => {
    btn.addEventListener('click', () => store.set({ railTab: btn.dataset.railTab || 'episodes' }));
  });

  document.getElementById('v2ShelfAddToggleBtn')?.addEventListener('click', () => {
    store.set({ shelfAddOpen: !store.get().shelfAddOpen });
  });

  document.getElementById('v2ShelfAddForm')?.addEventListener('submit', (e) => {
    e.preventDefault();
    const title = document.getElementById('v2ShelfTitleInput')?.value?.trim();
    const excerpt = document.getElementById('v2ShelfTextInput')?.value?.trim();
    if (!title || !excerpt) return;
    const items = loadShelfItems();
    const created = { id: `shelf-${Date.now()}`, title, status: 'RAW', source: 'pasted-raw.txt', tags: ['Unprocessed'], excerpt };
    saveShelfItems([created, ...items]);
    const parsed = parseTextToPrepNodes(excerpt);
    try { localStorage.setItem(PREP_DRAFT_KEY, excerpt); } catch (_) {}
    store.set({
      shelfAddOpen: false,
      activeShelfId: created.id,
      loadedShelfSnippet: created,
      prepDraftText: excerpt,
      prepNodes: parsed,
      notice: { text: `Stored "${title}" & auto-formatted ${parsed.length} nodes.`, tone: 'ok' },
    });
  });

  document.querySelectorAll('[data-shelf-open]').forEach((btn) => {
    btn.addEventListener('click', () => {
      const item = loadShelfItems().find((x) => x.id === btn.dataset.shelfOpen);
      if (!item) return;
      const parsed = parseTextToPrepNodes(item.excerpt || '');
      try { localStorage.setItem(PREP_DRAFT_KEY, item.excerpt || ''); } catch (_) {}
      store.set({
        activeShelfId: item.id,
        loadedShelfSnippet: item,
        prepDraftText: item.excerpt || '',
        prepNodes: parsed,
        prepViewMode: 'visual',
        notice: { text: `Auto-formatted "${item.title}" into ${parsed.length} connected nodes.`, tone: 'ok' },
      });
      if (store.get().view !== 'prep' && typeof changeView === 'function') changeView('prep');
    });
  });

  document.querySelectorAll('[data-shelf-law]').forEach((btn) => {
    btn.addEventListener('click', () => {
      store.set({ activeShelfId: btn.dataset.shelfLaw, notice: { text: 'Focused WORLD_LAWS.noir tagger.', tone: 'ok' } });
      if (store.get().view !== 'prep' && typeof changeView === 'function') changeView('prep');
    });
  });

  document.getElementById('v2PrepFontFamily')?.addEventListener('change', (e) => store.set({ prepFontFamily: e.target.value }));
  document.getElementById('v2PrepFontSize')?.addEventListener('change', (e) => store.set({ prepFontSize: e.target.value }));
  document.getElementById('v2PrepAddKindSelect')?.addEventListener('change', (e) => store.setQuiet({ prepAddKind: e.target.value }));

  document.querySelectorAll('[data-fmt-cmd]').forEach((btn) => {
    btn.addEventListener('mousedown', (e) => {
      e.preventDefault();
      document.execCommand(btn.dataset.fmtCmd, false, null);
    });
  });

  document.querySelectorAll('[data-prep-mode]').forEach((btn) => {
    btn.addEventListener('click', () => {
      const mode = btn.dataset.prepMode || 'visual';
      const cur = store.get();
      if (mode === 'visual' && cur.prepDraftText) {
        store.set({ prepViewMode: mode, prepNodes: parseTextToPrepNodes(cur.prepDraftText) });
      } else {
        store.set({ prepViewMode: mode });
      }
    });
  });

  document.getElementById('v2PrepAutoFormatBtn')?.addEventListener('click', () => {
    const cur = store.get();
    const raw = document.getElementById('v2PrepEditorText')?.value ?? cur.prepDraftText ?? loadPrepDraft('');
    const parsed = parseTextToPrepNodes(raw);
    store.set({ prepViewMode: 'visual', prepNodes: parsed, prepDraftText: raw, notice: { text: `Auto-formatted into ${parsed.length} connected nodes.`, tone: 'ok' } });
    requestAnimationFrame(() => {
      const flow = document.getElementById('v2PrepNodeFlow');
      if (flow) noirVfx.playEnergySweep(flow, `Auto-Formatted: ${parsed.length} Nodes · 100%`);
      noirVfx.flashTelemetryDelta('stages', '+1');
      noirVfx.flashTelemetryDelta('dialogues', '+2');
    });
  });

  // Hover metallic sheen on gutter-node cards
  document.querySelectorAll('.v2-node-row').forEach((row) => {
    row.addEventListener('mouseenter', () => {
      const card = row.querySelector('.v2-node-card');
      if (card) noirVfx.playNodeHoverSheen(card);
    });
  });

  const addNodeAt = (afterIndex = null) => {
    const cur = store.get();
    const kind = document.getElementById('v2PrepAddKindSelect')?.value || cur.prepAddKind || 'stage-direction';
    const currentNodes = Array.isArray(cur.prepNodes) ? [...cur.prepNodes] : parseTextToPrepNodes(cur.prepDraftText || '');
    const id = `pnode-${Date.now()}`;
    const newNode = {
      id,
      kind,
      speaker: kind === 'character' ? 'SADE' : '',
      text: kind === 'stage-direction' ? '[New stage direction...]' : kind === 'scene-heading' ? 'INT. NEW LOCATION - NIGHT' : 'New block text...',
    };
    if (afterIndex === null || afterIndex < 0 || afterIndex >= currentNodes.length) currentNodes.push(newNode);
    else currentNodes.splice(afterIndex + 1, 0, newNode);
    syncNodes(currentNodes, false);
    store.set({ selectedPrepNodeId: id, prepViewMode: 'visual' });
  };

  document.getElementById('v2PrepAddNodeBtn')?.addEventListener('click', () => addNodeAt(null));
  document.querySelectorAll('[data-insert-after]').forEach((btn) => {
    btn.addEventListener('click', () => addNodeAt(Number(btn.dataset.insertAfter)));
  });

  document.querySelectorAll('[data-select-node]').forEach((btn) => {
    btn.addEventListener('click', () => {
      const nodeId = btn.dataset.selectNode;
      store.set({ selectedPrepNodeId: nodeId });
      requestAnimationFrame(() => {
        const badge = document.querySelector(`[data-select-node="${CSS.escape(nodeId)}"]`);
        if (badge) noirVfx.playOverdriveCharge(badge);
      });
    });
  });

  document.querySelectorAll('[data-delete-node]').forEach((btn) => {
    btn.addEventListener('click', () => {
      const cur = store.get();
      const currentNodes = (Array.isArray(cur.prepNodes) ? cur.prepNodes : parseTextToPrepNodes(cur.prepDraftText || ''))
        .filter((n) => n.id !== btn.dataset.deleteNode);
      syncNodes(currentNodes, false);
    });
  });

  document.querySelectorAll('[data-node-kind]').forEach((sel) => {
    sel.addEventListener('change', () => {
      const cur = store.get();
      const currentNodes = (Array.isArray(cur.prepNodes) ? cur.prepNodes : parseTextToPrepNodes(cur.prepDraftText || ''))
        .map((n) => (n.id === sel.dataset.nodeKind ? { ...n, kind: sel.value, speaker: sel.value === 'character' ? (n.speaker || 'SADE') : '' } : n));
      syncNodes(currentNodes, false);
    });
  });

  document.querySelectorAll('[data-node-speaker]').forEach((inp) => {
    inp.addEventListener('input', () => {
      const cur = store.get();
      const currentNodes = (Array.isArray(cur.prepNodes) ? cur.prepNodes : parseTextToPrepNodes(cur.prepDraftText || ''))
        .map((n) => (n.id === inp.dataset.nodeSpeaker ? { ...n, speaker: inp.value.toUpperCase() } : n));
      syncNodes(currentNodes, true);
    });
  });

  document.querySelectorAll('[data-node-edit]').forEach((el) => {
    el.addEventListener('input', () => {
      const cur = store.get();
      const currentNodes = (Array.isArray(cur.prepNodes) ? cur.prepNodes : parseTextToPrepNodes(cur.prepDraftText || ''))
        .map((n) => (n.id === el.dataset.nodeEdit ? { ...n, text: el.innerText.trim() } : n));
      syncNodes(currentNodes, true);
    });
  });

  document.querySelectorAll('[data-inject-noise]').forEach((btn) => {
    btn.addEventListener('click', () => {
      const cur = store.get();
      const nodes = Array.isArray(cur.prepNodes) ? cur.prepNodes : parseTextToPrepNodes(cur.prepDraftText || '');
      const targetId = cur.selectedPrepNodeId || nodes[0]?.id;
      const targetNode = nodes.find((n) => n.id === targetId);
      const weight = btn.dataset.injectNoise;
      const isLock = weight === '0';
      const next = nodes.map((n) => (n.id === targetId ? { ...n, noise_mode: weight } : n));
      syncNodes(next, false);
      store.set({ notice: { text: `Injected ${weight}% Noise lock onto node.`, tone: 'ok' } });
      requestAnimationFrame(() => {
        const row = targetId ? document.querySelector(`.v2-node-row[data-prep-node="${CSS.escape(targetId)}"]`) : null;
        const badge = row?.querySelector('.v2-gutter-circle');
        if (row) {
          noirVfx.playEnergySweep(row, `Optimizing Node: ${targetNode?.kind || 'block'} ${weight}%`);
          noirVfx.playSparkBurst(row, isLock ? '0% LOCK ARMED' : `${weight}% BALANCED`, isLock);
        }
        if (badge && isLock) noirVfx.playOverdriveCharge(badge);
        noirVfx.flashTelemetryDelta(targetNode?.kind === 'character' ? 'dialogues' : 'stages', '+1');
      });
    });
  });

  document.querySelectorAll('[data-inject-law]').forEach((btn) => {
    btn.addEventListener('click', () => {
      const cur = store.get();
      const nodes = Array.isArray(cur.prepNodes) ? cur.prepNodes : parseTextToPrepNodes(cur.prepDraftText || '');
      const targetId = cur.selectedPrepNodeId || nodes[0]?.id;
      const lawId = btn.dataset.injectLaw;
      const next = nodes.map((n) => (n.id === targetId ? { ...n, injected_law: lawId } : n));
      syncNodes(next, false);
      store.set({ notice: { text: `Bound @law:${lawId} onto selected node.`, tone: 'ok' } });
      requestAnimationFrame(() => {
        const row = targetId ? document.querySelector(`.v2-node-row[data-prep-node="${CSS.escape(targetId)}"]`) : null;
        const badge = row?.querySelector('.v2-gutter-circle');
        if (row) {
          noirVfx.playEnergySweep(row, `Binding Hard Law: @${lawId} 100%`);
          noirVfx.playSparkBurst(row, '+1 LAW BOUND', true);
        }
        if (badge) noirVfx.playOverdriveCharge(badge);
        noirVfx.flashTelemetryDelta('lawRefs', '+1');
        noirVfx.showLawInterceptToast({
          title: 'WORLD LAW INTERCEPT · HARD GUARD',
          message: `@law:${lawId} locked onto active node — canon enforcement active across Compose & Story Graph.`,
          badge: '⛨ LAW',
          accent: 'law',
        });
      });
    });
  });

  document.getElementById('v2PrepEditorText')?.addEventListener('input', (e) => {
    const val = e.target.value;
    try { localStorage.setItem(PREP_DRAFT_KEY, val); } catch (_) {}
    store.setQuiet({ prepDraftText: val });
  });

  document.getElementById('v2PrepLawDocText')?.addEventListener('input', (e) => {
    const val = e.target.value;
    try { localStorage.setItem(PREP_LAW_KEY, val); } catch (_) {}
    store.setQuiet({ prepLawDoc: val });
  });

  document.getElementById('v2PrepSaveShelfBtn')?.addEventListener('click', () => {
    const cur = store.get();
    const items = loadShelfItems();
    const text = cur.prepDraftText || loadPrepDraft('');
    const activeId = cur.activeShelfId || items[0]?.id;
    saveShelfItems(items.map((x) => (x.id === activeId ? { ...x, status: 'STAGED', excerpt: text } : x)));
    store.set({ notice: { text: 'Saved staged node script back to Text Shelf.', tone: 'ok' } });
    const btn = document.getElementById('v2PrepSaveShelfBtn');
    if (btn) noirVfx.playSparkBurst(btn, 'STAGED TO SHELF', false);
  });

  document.getElementById('v2PrepSendComposeBtn')?.addEventListener('click', async () => {
    const state = store.get();
    const { episode, notebook, scope } = state.episodeState || {};
    if (state.busy) return;
    if (!episode || !notebook || state.dirty) {
      store.set({ notice: { text: 'Open a saved episode and save any Compose changes first.', tone: 'warn' } });
      return;
    }
    const prepText = state.prepDraftText ?? loadPrepDraft('');
    if (!prepText.trim()) {
      store.set({ notice: { text: 'Write or paste the text to send first.', tone: 'warn' } });
      return;
    }
    const nodes = state.prepNodes || parseTextToPrepNodes(prepText);
    store.set({ busy: true });
    try {
      await api.promoteWordPrep({ episode: episode.id, project: scope?.project_id, universe: scope?.universe_id,
        timeline_revision: episode.head, notebook_revision: notebook.revision, nodes });
      if (state.activeShelfId) {
        saveShelfItems(loadShelfItems().map((item) => item.id === state.activeShelfId
          ? { ...item, status: 'IN GRAPH', excerpt: prepText } : item));
      }
      if (store.get().episodeId !== episode.id || !await onPromoted(episode.id)) return;
      store.set({ notice: { text: 'Saved Word Prep to Compose and the episode graph.', tone: 'ok' } });
      changeView('compose');
    } catch (error) {
      store.set({ busy: false, notice: { text: error.message, tone: 'err' } });
    }
  });
}
