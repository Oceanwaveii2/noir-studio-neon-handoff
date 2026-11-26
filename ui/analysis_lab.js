/* Noir Fiction Studio — V7 Parallel Analysis Lab (CN-4)
 * Implements immutable chained What-If branching (G0 -> G1 -> G2 -> ...),
 * live World-Laws conflict validation, MAP-Elites 2x2 contrast ideas,
 * Epistemic Minds (ToM), and 1-click promotion into Word Prep Gutter-Nodes.
 */

import { parseTextToPrepNodes, serializePrepNodesToText } from './shelf.js';

const PREP_DRAFT_KEY = 'noir-prep-draft-v1';

const DEFAULT_SPELLCHECK_DRAFT =
  'Francine checks her watch in the kitchen while Stan Smith argues by the doorway. Upstairs, Haley texts her husband Jeff that the party is starting early, right as Rainee farts and splits into The Plastics in the hallway.';

function scanDraftWorldLawErrors(draftText, laws, ignoredIds) {
  const active = new Set((laws || []).filter((l) => l.active).map((l) => l.id));
  const ignored = new Set(ignoredIds || []);
  const errors = [];
  if (active.has('LAW_ZERO_SMITH') && !ignored.has('ERR_SMITH') && /\bStan Smith\b/i.test(draftText)) {
    errors.push({
      id: 'ERR_SMITH',
      lawId: 'LAW_ZERO_SMITH',
      phrase: 'Stan Smith',
      replacement: 'Rainee Ling',
      reason: 'Zero Smith Household: Stan Smith is not Francine\'s spouse in the Ling house.',
      canEnableLaw: false,
    });
  }
  if (active.has('LAW_HALEY_PRE_FOX') && !ignored.has('ERR_HUSBAND_JEFF') && /\bhusband Jeff\b/i.test(draftText)) {
    errors.push({
      id: 'ERR_HUSBAND_JEFF',
      lawId: 'LAW_HALEY_PRE_FOX',
      phrase: 'husband Jeff',
      replacement: 'boyfriend Jeff',
      reason: 'S04E16 Timeline Law: Haley is still dating Jeff here (not married until later).',
      canEnableLaw: false,
    });
  }
  if (!active.has('LAW_SHAPESHIFT') && !ignored.has('ERR_NO_MORPH') && /(splits into The Plastics|Peter-Rainee)/i.test(draftText)) {
    const match = draftText.match(/(splits into The Plastics|Peter-Rainee)/i)[0];
    errors.push({
      id: 'ERR_NO_MORPH',
      lawId: 'LAW_SHAPESHIFT',
      phrase: match,
      replacement: 'walks out into the driveway',
      reason: 'Parallel No-Morph AU: Shapeshifting / clone-splitting is disabled in this world.',
      canEnableLaw: true,
    });
  }
  return errors;
}

function highlightDraftErrorsHtml(draftText, errors) {
  let html = esc(draftText);
  for (const err of errors) {
    const safePhrase = esc(err.phrase);
    html = html.replaceAll(safePhrase, `<mark class="v2-law-wavy" title="${esc(err.reason)}">${safePhrase}</mark>`);
  }
  return html;
}

const WORLD_LAW_PRESETS = {
  afm_canon: [
    { id: 'LAW_ZERO_SMITH', title: 'Zero Smith Household (Ling Canon)', desc: 'Francine is married to Rainee Ling; Stan lives next door with Christmas family.', active: true },
    { id: 'LAW_SHAPESHIFT', title: 'Rainee Celestial Fox Shapeshifting', desc: 'Rainee can morph into Peter-Rainee or split forms; gas emits French floral perfume.', active: true },
    { id: 'LAW_HALEY_PRE_FOX', title: 'Haley Pre-Activation (S04E16)', desc: 'Haley is human and dating boyfriend Jeff (not married yet).', active: true },
    { id: 'LAW_NO_IMPLANT_DEATH', title: 'Stella Likes Carmen Aesthetic', desc: 'Breaks original Steve implant-objection -> Carmen death dependency.', active: true },
  ],
  parallel_human: [
    { id: 'LAW_ZERO_SMITH', title: 'Zero Smith Household (Ling Canon)', desc: 'Francine is married to Rainee Ling; Stan lives next door.', active: true },
    { id: 'LAW_SHAPESHIFT', title: 'Rainee Celestial Fox Shapeshifting', desc: 'DISABLED in No-Morph Parallel World — morph beats fail validation.', active: false },
    { id: 'LAW_HALEY_PRE_FOX', title: 'Haley Pre-Activation (S04E16)', desc: 'Haley is human and dating boyfriend Jeff.', active: true },
    { id: 'LAW_NO_IMPLANT_DEATH', title: 'Stella Likes Carmen Aesthetic', desc: 'Carmen keeps implants and survives stage collapse.', active: true },
  ],
  plastics_split: [
    { id: 'LAW_ZERO_SMITH', title: 'Zero Smith Household (Ling Canon)', desc: 'Francine is married to Rainee Ling.', active: true },
    { id: 'LAW_SHAPESHIFT', title: 'Rainee Tri-Split Instability Law', desc: 'Unstable Peter-Rainee gas blast splits Rainee into 3 Mean Girls facets (Sade, Becky, Clarie).', active: true },
    { id: 'LAW_HALEY_PRE_FOX', title: 'Haley Pre-Activation (S04E16)', desc: 'Haley reacts to 3 clones in the hallway.', active: true },
    { id: 'LAW_NO_IMPLANT_DEATH', title: 'Stella Likes Carmen Aesthetic', desc: 'Plastics clones amplify Spring Break social hierarchy chaos.', active: true },
  ],
};

const DEFAULT_BRANCHES = [
  {
    id: 'G0',
    parent: null,
    label: 'G₀ · Source Baseline (S04E16)',
    question: 'Ingested from American Dad! - S04E16 - Spring Breakup - HDTV-1080ph265 AAC.mp4 (286 lines · 14 speakers · 26 beats)',
    beats: [
      { id: 'E01', status: 'base', text: 'Francine leaves to care for Bah-Bah; Stan stays home with Roger.', requires: [] },
      { id: 'E02', status: 'base', text: 'Roger turns the house into MTV Spring Break HQ with Carmen Selectra.', requires: [] },
      { id: 'E03', status: 'base', text: "Steve objects to Carmen's implants -> Carmen removes them -> dies in stage collapse.", requires: [] },
    ],
    qd: [
      { axis: 'Baseline Canon', title: 'Original S04E16 Spine', pitch: 'No AU intervention applied yet. Fork G₁ to remove Stan and add Rainee.', scores: [95, 20, 99] },
      { axis: 'Suggested Swap', title: 'Swap Spouse: Stan -> Rainee', pitch: 'Remove Stan from domestic opening and test Peter-Rainee B-plot.', scores: [92, 85, 96] },
    ],
    epistemic: [
      { holder: 'ROGER', belief: 'Believes the house is empty enough to host MTV Spring Break.' },
      { holder: 'STEVE', belief: 'Believes Carmen will love him more without implants.' },
    ],
  },
  {
    id: 'G1',
    parent: 'G0',
    label: 'G₁ · Q1: Remove Stan + Peter-Rainee Morph',
    question: 'Q1: "What happens if we remove Stan from the house, add Rainee as Francine\'s wife, and Rainee becomes Peter Griffin?"',
    beats: [
      { id: 'E01*', status: 'new', text: 'Francine & Rainee Ling open in the kitchen; Stan is moved next door with his Porsche Christmas family.', requires: ['LAW_ZERO_SMITH'] },
      { id: 'E02*', status: 'new', text: "Rainee's gas blast triggers Peter-Rainee morph (Quahog baritone + giant rear); Francine takes her to Ma Ma & Bah-Bah's.", requires: ['LAW_SHAPESHIFT'] },
      { id: 'E03×', status: 'broken', text: 'PRUNED: Steve anti-implant arc & Carmen death chain invalidated by Stella Siren Field inversion.', requires: ['LAW_NO_IMPLANT_DEATH'] },
      { id: 'E04*', status: 'new', text: "Roger's daisy-chain portal spills onto Neighbor Stan's lawn -> Stan's shutdown attempt creates legendary climax.", requires: ['LAW_ZERO_SMITH'] },
    ],
    qd: [
      { axis: 'Domestic Farce × B-Plot', title: 'Shared-Patient Rivalry', pitch: "Peter-Rainee and Bah-Bah form an alliance trying to sneak out of Nurse Francine's care.", scores: [94, 82, 97] },
      { axis: 'Surreal Escalation × A-Plot', title: 'Portal Border War', pitch: "Neighbor Stan builds a CIA perimeter fence; Roger daisy-chains portals through Stan's garage.", scores: [91, 88, 95] },
      { axis: 'Mind-Game × Youth Plot', title: 'Ruth Fixation Cascade', pitch: "Stan's daughter Ruth stares at Stella's Carmen-energy shift; Stan walks in at the worst moment.", scores: [89, 86, 94] },
      { axis: 'Wild Mutation (100% Noise)', title: 'Peter-Rainee Calls Quahog', pitch: 'Peter-Rainee accidentally dials the Drunken Clam on speakerphone while Francine lectures Bah-Bah.', scores: [80, 96, 84] },
    ],
    epistemic: [
      { holder: 'NEIGHBOR STAN', belief: 'Falsely believes Roger is intentionally corrupting his perfect family.' },
      { holder: 'BAH-BAH', belief: 'Thinks Peter-Rainee is a weirdly tall Rhode Island cousin until Francine sighs.' },
      { holder: "MARY (STAN'S WIFE)", belief: 'Believes Stan is overreacting and the kids are just having normal fun.' },
    ],
  },
  {
    id: 'G2',
    parent: 'G1',
    label: 'G₂ · Q2 (Chained off G₁): Fart Splits into The Plastics',
    question: 'Q2 on G₁: "What if the Peter Griffin morph doesn\'t stick — she farts and splits into The Plastics (Rainee Sade, Rainee Becky, Rainee Clarie)?"',
    beats: [
      { id: 'E02×', status: 'broken', text: "PRUNED FROM G₁: Peter-Rainee stays at Ma Ma's house — morph destabilizes before leaving the driveway!", requires: ['LAW_SHAPESHIFT'] },
      { id: 'E05*', status: 'new', text: 'Second tuberose/orange/sandalwood blast splits Rainee into 3 Mean Girls facets (Sade, Becky, Clarie) stealing the red sedan.', requires: ['LAW_SHAPESHIFT'] },
      { id: 'E06*', status: 'new', text: "The Plastics hijack Roger's Spring Break VIP deck, instantly dethroning Roger's King-of-Spring-Break status.", requires: ['LAW_ZERO_SMITH'] },
      { id: 'E07*', status: 'new', text: 'Nurse Francine arrives mid-party trying to re-merge all three clones before Ma Ma & Bah-Bah notice.', requires: ['LAW_SHAPESHIFT'] },
    ],
    qd: [
      { axis: 'Social Warfare × A-Plot', title: 'Plastics Coup on MTV Stage', pitch: "Sade, Becky, and Clarie rate Roger's outfit a 4/10 on live MTV, forcing Roger into desperate persona swaps.", scores: [96, 93, 98] },
      { axis: 'Domestic Chaos × B-Plot', title: 'Red Sedan Escape', pitch: 'All three clones argue over aux cord & mirror space while Francine chases them in Nurse scrubs.', scores: [92, 87, 95] },
      { axis: 'Epistemic Comedy × Neighbor', title: 'Stan Meets Three Wives', pitch: 'Neighbor Stan sees three identical glamorous Rainees walk past his fence and assumes CIA cloning.', scores: [90, 94, 93] },
      { axis: 'Wild Mutation (100% Noise)', title: 'Burn Book of Spring Break', pitch: 'Becky & Clarie start an instant Burn Book on every Spring Break contestant, turning Carmen into an ally.', scores: [88, 97, 91] },
    ],
    epistemic: [
      { holder: 'RAINEE SADE (ALPHA)', belief: 'Believes she is the "original" Rainee and Becky/Clarie are backup dancers.' },
      { holder: 'ROGER', belief: 'Thinks the three clones are rival influencers hired by MTV to ruin his coronation.' },
      { holder: 'NEIGHBOR STAN', belief: 'Convinced the CIA is running an illegal cloning op next door.' },
    ],
  },
];

function esc(value) {
  return String(value ?? '')
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;');
}

export function promoteCandidateToPrepNodes(candidate, branchId, activeLawIds) {
  const lawList = Array.isArray(activeLawIds) ? activeLawIds : Array.from(activeLawIds || []);
  const nodes = [
    { id: `pnode-${Date.now()}-1`, kind: 'scene-heading', speaker: '', text: `INT. ${candidate.title.toUpperCase()} - NIGHT` },
    { id: `pnode-${Date.now()}-2`, kind: 'stage-direction', speaker: '', text: `[${candidate.pitch}]` },
    { id: `pnode-${Date.now()}-3`, kind: 'character', speaker: 'SADE', text: '"Keep up — the party doesn\'t wait for anyone."' },
    { id: `pnode-${Date.now()}-4`, kind: 'world-law', speaker: '', text: lawList[0] ? `@law:${lawList[0]}` : '@law:kidney-price' },
    { id: `pnode-${Date.now()}-5`, kind: 'beat-turn', speaker: '', text: `Promoted from ${branchId} (${candidate.axis})` },
  ];
  return { source_branch_id: branchId, nodes };
}

export function renderAnalysisLabStage(state) {
  const branches = Array.isArray(state.labBranches) ? state.labBranches : DEFAULT_BRANCHES;
  const branchId = state.labBranchId || 'G2';
  const branch = branches.find((b) => b.id === branchId) || branches[0];
  const universe = state.labUniverse || 'afm_canon';
  const laws = Array.isArray(state.labLaws) ? state.labLaws : WORLD_LAW_PRESETS[universe];
  const activeLawIds = new Set(laws.filter((l) => l.active).map((l) => l.id));
  const subtab = state.labSubtab || 'causal';
  const mediaName = state.labMediaName || 'American Dad! - S04E16 - Spring Breakup - HDTV-1080ph265 AAC.mp4';

  return `
    <div class="v2-lab-studio">
      <header class="v2-lab-hero">
        <div>
          <span class="v2-lab-eyebrow">V7 PARALLEL ANALYSIS LAB · COUNTERFACTUAL STORY RECOMPUTE</span>
          <h1>Ingest Media, Chain What-If Branches &amp; Test Live World Laws</h1>
          <p>Ask sequential What-If questions without mutating baseline G₀, toggle universe rules to detect conflicts pre-LLM, and stage chosen possibilities when you are ready to send them to the Main Cooker.</p>
        </div>
        <div class="v2-lab-pills">
          <span class="v2-pill v2-pill-finished">IMMUTABLE G₀</span>
          <span class="v2-pill v2-pill-draft">BRANCH ${esc(branch.id)}</span>
          <span class="v2-pill v2-pill-draft">COOK QUEUE: ${(state.labStagedPackets || []).length}</span>
        </div>
      </header>

      <div class="v2-lab-grid">
        <div class="v2-lab-col">
          <section class="v2-lab-card">
            <div class="v2-lab-card-head">
              <h2>01 · Media &amp; Movie Ingest</h2>
              <span class="v2-pill v2-pill-finished">READY</span>
            </div>
            <div class="v2-lab-ingest">
              <strong>${esc(mediaName)}</strong>
              <small>MP4, MKV, SRT, PDF, DOCX, TXT → Baseline Causal DAG (G₀)</small>
              <div class="v2-lab-steps">
                <div><b>ASR/SRT</b><span>286 lines</span></div>
                <div><b>Diarize</b><span>14 speakers</span></div>
                <div><b>Base DAG</b><span>26 beats</span></div>
              </div>
              <input type="file" id="v2LabMediaInput" accept=".mp4,.mkv,.srt,.pdf,.docx,.txt,.md" hidden>
              <button type="button" class="v2-btn" id="v2LabPickMediaBtn">Attach Clip / Script → G₀</button>
            </div>
          </section>

          <section class="v2-lab-card">
            <div class="v2-lab-card-head">
              <h2>02 · Chained What-If Branches</h2>
              <span class="v2-pill v2-pill-draft">${branches.length} branches</span>
            </div>
            <div class="v2-lab-branch-list">
              ${branches.map((b) => `
                <button type="button" class="v2-lab-branch ${b.id === branch.id ? 'is-active' : ''}" data-lab-branch="${esc(b.id)}">
                  <strong>${esc(b.label)}</strong>
                  <small>${b.parent ? `Forked from ${esc(b.parent)}` : 'Immutable Source Root'}</small>
                </button>
              `).join('')}
            </div>
            <form id="v2LabForkForm" class="v2-lab-fork-form">
              <input type="text" id="v2LabQuestionInput" placeholder="What-If question off ${esc(branch.id)} (e.g. 'What if Holly joins?')..." required maxlength="180">
              <button type="submit" class="v2-btn v2-btn-accent">+ Fork New Branch off ${esc(branch.id)}</button>
            </form>
          </section>

          <section class="v2-lab-card">
            <div class="v2-lab-card-head">
              <h2>03 · Live World-Laws Grid</h2>
              <select id="v2LabUniverseSelect" aria-label="Parallel world preset">
                <option value="afm_canon" ${universe === 'afm_canon' ? 'selected' : ''}>AFM Main Canon</option>
                <option value="parallel_human" ${universe === 'parallel_human' ? 'selected' : ''}>Parallel: No-Morph AU</option>
                <option value="plastics_split" ${universe === 'plastics_split' ? 'selected' : ''}>Plastics Split Override</option>
              </select>
            </div>
            <div class="v2-lab-laws">
              ${laws.map((l) => `
                <label class="v2-lab-law ${l.active ? '' : 'is-off'}">
                  <div>
                    <strong>${esc(l.title)}</strong>
                    <small>${esc(l.desc)}</small>
                  </div>
                  <input type="checkbox" data-lab-law="${esc(l.id)}" ${l.active ? 'checked' : ''}>
                </label>
              `).join('')}
            </div>
          </section>
        </div>

        <div class="v2-lab-col">
          <section class="v2-lab-card">
            <div class="v2-lab-card-head">
              <h2>${esc(branch.label)}</h2>
              <div class="v2-lab-tabs" role="tablist">
                <button type="button" class="v2-btn" data-lab-tab="causal" aria-pressed="${subtab === 'causal'}">Causal Ripple (DAG)</button>
                <button type="button" class="v2-btn" data-lab-tab="qd" aria-pressed="${subtab === 'qd'}">MAP-Elites (2×2)</button>
                <button type="button" class="v2-btn" data-lab-tab="epistemic" aria-pressed="${subtab === 'epistemic'}">Epistemic (ToM)</button>
              </div>
            </div>
            <p class="v2-lab-question">${esc(branch.question)}</p>

            ${subtab === 'causal' ? `
              <div class="v2-lab-flow">
                ${branch.beats.map((bt) => {
                  const missing = (bt.requires || []).filter((id) => !activeLawIds.has(id));
                  const cls = missing.length ? 'is-conflict' : `is-${bt.status}`;
                  const pillText = missing.length
                    ? `LAW CONFLICT: ${missing.join(', ')}`
                    : bt.status === 'broken' ? 'PRUNED CANON'
                    : bt.status === 'new' ? 'RECOMPUTED BEAT'
                    : 'SOURCE G₀';
                  return `
                    <div class="v2-lab-beat ${cls}">
                      <span class="v2-lab-beat-id">${esc(bt.id)}</span>
                      <div>${esc(bt.text)}</div>
                      <span class="v2-pill v2-pill-draft">${esc(pillText)}</span>
                    </div>
                  `;
                }).join('')}
              </div>
            ` : subtab === 'qd' ? `
              <div class="v2-lab-qd-grid">
                ${branch.qd.map((c, idx) => `
                  <article class="v2-lab-qd-cell">
                    <span class="v2-lab-qd-axis">${esc(c.axis)}</span>
                    <strong>${esc(c.title)}</strong>
                    <p>${esc(c.pitch)}</p>
                    <div class="v2-lab-bar-row"><span>Coherence</span><div class="v2-lab-bar"><i style="width:${c.scores[0]}%"></i></div><b>${c.scores[0]}</b></div>
                    <div class="v2-lab-bar-row"><span>Novelty</span><div class="v2-lab-bar"><i style="width:${c.scores[1]}%"></i></div><b>${c.scores[1]}</b></div>
                    <div class="v2-lab-bar-row"><span>Canon Fit</span><div class="v2-lab-bar"><i style="width:${c.scores[2]}%"></i></div><b>${c.scores[2]}</b></div>
                    <div style="display:flex;gap:6px;flex-wrap:wrap">
                      <button type="button" class="v2-btn v2-btn-accent" data-lab-stage="${idx}">Stage for Main Cooker</button>
                      <button type="button" class="v2-btn" data-lab-promote="${idx}">Send → Word Prep ↗</button>
                    </div>
                  </article>
                `).join('')}
              </div>
            ` : `
              <div class="v2-lab-flow">
                ${branch.epistemic.map((ep) => `
                  <div class="v2-lab-beat is-new">
                    <span class="v2-lab-beat-id">${esc(ep.holder)}</span>
                    <div>${esc(ep.belief)}</div>
                    <span class="v2-pill v2-pill-finished">BELIEF STATE</span>
                  </div>
                `).join('')}
              </div>
            `}
          </section>

          <section class="v2-lab-card">
            <div class="v2-lab-card-head">
              <h2>04 · Draft Generator &amp; World-Law Spell-Check</h2>
              <button type="button" class="v2-btn v2-btn-accent" id="v2LabGenDraftBtn">⚡ Generate Draft (Non-Blocking)</button>
            </div>
            ${(() => {
              const draftText = state.labDraftText ?? DEFAULT_SPELLCHECK_DRAFT;
              const errors = scanDraftWorldLawErrors(draftText, laws, state.labIgnoredErrors);
              return `
                <div class="v2-lab-draft-paper" aria-label="Generated draft with inline World-Law spell-check">
                  ${highlightDraftErrorsHtml(draftText, errors)}
                </div>
                <div class="v2-lab-spell-head">
                  <strong>${errors.length ? `⚠ ${errors.length} World-Law Error(s) Found — How do you want to solve them?` : '✅ Zero World-Law Errors — Draft matches active canon!'}</strong>
                </div>
                ${errors.length ? `
                  <div class="v2-lab-error-list">
                    ${errors.map((err) => `
                      <div class="v2-lab-error-row">
                        <div>
                          <strong>"${esc(err.phrase)}" → <em>${esc(err.lawId)}</em></strong>
                          <small>${esc(err.reason)}</small>
                        </div>
                        <div class="v2-lab-error-btns">
                          <button type="button" class="v2-mini-btn" data-fix-phrase="${esc(err.phrase)}" data-fix-repl="${esc(err.replacement)}">Fix → "${esc(err.replacement)}"</button>
                          <button type="button" class="v2-mini-btn" data-solve-law="${esc(err.lawId)}" data-solve-enable="${err.canEnableLaw ? '1' : '0'}">${err.canEnableLaw ? `Enable ${esc(err.lawId)}` : `Disable ${esc(err.lawId)}`}</button>
                          <button type="button" class="v2-mini-btn" data-ignore-err="${esc(err.id)}">Ignore</button>
                        </div>
                      </div>
                    `).join('')}
                  </div>
                ` : ''}
              `;
            })()}
          </section>

          <section class="v2-lab-card">
            <div class="v2-lab-card-head">
              <h2>05 · Staged Main Cooker Queue (${(state.labStagedPackets || []).length})</h2>
              <div style="display:flex;gap:6px;flex-wrap:wrap">
                ${(state.labStagedPackets || []).length ? '<button type="button" class="v2-btn" id="v2LabClearQueueBtn">Clear Queue</button>' : ''}
                <button type="button" class="v2-btn v2-btn-accent" id="v2LabRunCookerBtn" ${(state.labStagedPackets || []).length && !state.busy ? '' : 'disabled'}>
                  ▶ Run Main Cooker (${(state.labStagedPackets || []).length})
                </button>
              </div>
            </div>
            ${(state.labStagedPackets || []).length ? `
              <div class="v2-lab-flow">
                ${(state.labStagedPackets || []).map((pkt, idx) => `
                  <div class="v2-lab-beat is-new">
                    <span class="v2-lab-beat-id">${esc(pkt.source_branch_id || 'G2')}</span>
                    <div><strong>${esc(pkt.title)}</strong> · ${(pkt.nodes || []).length} Gutter-Nodes staged</div>
                    <button type="button" class="v2-mini-btn" data-lab-unstage="${idx}">Remove</button>
                  </div>
                `).join('')}
              </div>
            ` : '<p class="v2-lab-question">No possibilities staged yet. Click <strong>Stage for Main Cooker</strong> on any MAP-Elites card above to queue it here.</p>'}
          </section>
        </div>
      </div>
    </div>
  `;
}

export function bindAnalysisLabEvents({ store, changeView, onRunMainCooker }) {
  document.getElementById('v2LabPickMediaBtn')?.addEventListener('click', () => {
    document.getElementById('v2LabMediaInput')?.click();
  });
  document.getElementById('v2LabMediaInput')?.addEventListener('change', (e) => {
    const file = e.target.files?.[0];
    if (!file) return;
    store.set({
      labMediaName: file.name,
      labBranchId: 'G0',
      notice: { text: `Ingested "${file.name}" as immutable baseline G₀.`, tone: 'ok' },
    });
  });

  document.querySelectorAll('[data-lab-branch]').forEach((btn) => {
    btn.addEventListener('click', () => {
      window.NOIR_FX?.trigger('OVERDRIVE_SURGE', { el: btn, label: btn.dataset.labBranch });
      store.set({ labBranchId: btn.dataset.labBranch });
    });
  });

  document.querySelectorAll('[data-lab-tab]').forEach((btn) => {
    btn.addEventListener('click', () => {
      window.NOIR_FX?.trigger('NODE_SELECT', { el: btn, badgeText: btn.dataset.labTab });
      store.set({ labSubtab: btn.dataset.labTab });
    });
  });

  document.getElementById('v2LabUniverseSelect')?.addEventListener('change', (e) => {
    const univ = e.target.value;
    store.set({
      labUniverse: univ,
      labLaws: JSON.parse(JSON.stringify(WORLD_LAW_PRESETS[univ] || WORLD_LAW_PRESETS.afm_canon)),
      notice: { text: `Switched Parallel World rules to ${univ}. Validators re-run.`, tone: 'ok' },
    });
  });

  document.querySelectorAll('[data-lab-law]').forEach((chk) => {
    chk.addEventListener('change', () => {
      const cur = store.get();
      const laws = Array.isArray(cur.labLaws) ? cur.labLaws : WORLD_LAW_PRESETS[cur.labUniverse || 'afm_canon'];
      const nextLaws = laws.map((l) => (l.id === chk.dataset.labLaw ? { ...l, active: chk.checked } : l));
      store.set({
        labLaws: nextLaws,
        notice: { text: `World Law ${chk.dataset.labLaw} -> ${chk.checked ? 'ACTIVE' : 'DISABLED'}.`, tone: 'ok' },
      });
    });
  });

  document.getElementById('v2LabForkForm')?.addEventListener('submit', (e) => {
    e.preventDefault();
    const q = document.getElementById('v2LabQuestionInput')?.value?.trim();
    if (!q) return;
    const cur = store.get();
    const branches = Array.isArray(cur.labBranches) ? cur.labBranches : DEFAULT_BRANCHES;
    const parentId = cur.labBranchId || 'G2';
    const nextId = `G${branches.length}`;
    const forked = {
      id: nextId,
      parent: parentId,
      label: `${nextId} · Fork off ${parentId}`,
      question: `Q${branches.length} on ${parentId}: "${q}"`,
      beats: [
        { id: `E0${branches.length + 5}*`, status: 'new', text: `Counterfactual recompute from "${q}" (parent ${parentId} preserved).`, requires: ['LAW_ZERO_SMITH'] },
        { id: `E0${branches.length + 6}*`, status: 'new', text: 'Downstream character reaction & causal escalation generated against active World Laws.', requires: ['LAW_SHAPESHIFT'] },
      ],
      qd: [
        { axis: 'Domestic Escalation', title: `Domestic Twist: ${q.slice(0, 26)}`, pitch: q, scores: [93, 89, 96] },
        { axis: 'Surreal Chaos', title: `Wild Payoff: ${q.slice(0, 26)}`, pitch: `Amplify "${q}" with Roger portal & character mind collision.`, scores: [89, 95, 92] },
        { axis: 'Epistemic Collision', title: 'Misunderstanding Hook', pitch: `Characters misread "${q}" from blind belief states.`, scores: [91, 90, 95] },
        { axis: '100% Wild', title: 'Maximum Divergence', pitch: `Trigger full Form Switchyard cascade off "${q}".`, scores: [84, 98, 88] },
      ],
      epistemic: [
        { holder: 'ACTIVE CAST', belief: `Reacts to "${q}" from partial local knowledge.` },
      ],
    };
    store.set({
      labBranches: [...branches, forked],
      labBranchId: nextId,
      notice: { text: `Forked immutable branch ${nextId} from ${parentId}.`, tone: 'ok' },
    });
  });

  document.querySelectorAll('[data-lab-stage]').forEach((btn) => {
    btn.addEventListener('click', () => {
      const cur = store.get();
      const branches = Array.isArray(cur.labBranches) ? cur.labBranches : DEFAULT_BRANCHES;
      const branch = branches.find((b) => b.id === (cur.labBranchId || 'G2')) || branches[0];
      const laws = Array.isArray(cur.labLaws) ? cur.labLaws : WORLD_LAW_PRESETS[cur.labUniverse || 'afm_canon'];
      const activeLawIds = laws.filter((l) => l.active).map((l) => l.id);
      const candidate = branch.qd[Number(btn.dataset.labStage)];
      if (!candidate) return;
      const packet = promoteCandidateToPrepNodes(candidate, branch.id, activeLawIds);
      const queued = Array.isArray(cur.labStagedPackets) ? cur.labStagedPackets : [];
      store.set({
        labStagedPackets: [...queued, { title: candidate.title, ...packet }],
        notice: { text: `Staged "${candidate.title}" (${branch.id}) for Main Cooker. Nothing sent automatically.`, tone: 'ok' },
      });
    });
  });

  document.querySelectorAll('[data-lab-promote]').forEach((btn) => {
    btn.addEventListener('click', () => {
      const cur = store.get();
      const branches = Array.isArray(cur.labBranches) ? cur.labBranches : DEFAULT_BRANCHES;
      const branch = branches.find((b) => b.id === (cur.labBranchId || 'G2')) || branches[0];
      const laws = Array.isArray(cur.labLaws) ? cur.labLaws : WORLD_LAW_PRESETS[cur.labUniverse || 'afm_canon'];
      const activeLawIds = laws.filter((l) => l.active).map((l) => l.id);
      const candidate = branch.qd[Number(btn.dataset.labPromote)];
      if (!candidate) return;
      const packet = promoteCandidateToPrepNodes(candidate, branch.id, activeLawIds);
      const serialized = serializePrepNodesToText(packet.nodes);
      try { localStorage.setItem(PREP_DRAFT_KEY, serialized); } catch (_) {}
      store.set({
        prepNodes: packet.nodes,
        prepDraftText: serialized,
        prepViewMode: 'visual',
        notice: { text: `Promoted "${candidate.title}" (${packet.source_branch_id}) to Word Prep Gutter-Nodes!`, tone: 'ok' },
      });
      if (typeof changeView === 'function') changeView('prep');
    });
  });

  document.getElementById('v2LabGenDraftBtn')?.addEventListener('click', () => {
    store.set({
      labDraftText: DEFAULT_SPELLCHECK_DRAFT,
      labIgnoredErrors: [],
      notice: { text: 'Generated draft with non-blocking World-Law spell-check flags.', tone: 'warn' },
    });
  });

  document.querySelectorAll('[data-fix-phrase]').forEach((btn) => {
    btn.addEventListener('click', () => {
      const cur = store.get();
      const draft = cur.labDraftText ?? DEFAULT_SPELLCHECK_DRAFT;
      const updated = draft.replaceAll(btn.dataset.fixPhrase, btn.dataset.fixRepl);
      store.set({
        labDraftText: updated,
        notice: { text: `Fixed "${btn.dataset.fixPhrase}" -> "${btn.dataset.fixRepl}".`, tone: 'ok' },
      });
    });
  });

  document.querySelectorAll('[data-solve-law]').forEach((btn) => {
    btn.addEventListener('click', () => {
      const cur = store.get();
      const laws = Array.isArray(cur.labLaws) ? cur.labLaws : WORLD_LAW_PRESETS[cur.labUniverse || 'afm_canon'];
      const enable = btn.dataset.solveEnable === '1';
      const nextLaws = laws.map((l) => (l.id === btn.dataset.solveLaw ? { ...l, active: enable } : l));
      store.set({
        labLaws: nextLaws,
        notice: { text: `Updated World Law ${btn.dataset.solveLaw} = ${enable ? 'ACTIVE' : 'DISABLED'}.`, tone: 'ok' },
      });
    });
  });

  document.querySelectorAll('[data-ignore-err]').forEach((btn) => {
    btn.addEventListener('click', () => {
      const cur = store.get();
      const ignored = new Set(cur.labIgnoredErrors || []);
      ignored.add(btn.dataset.ignoreErr);
      store.set({
        labIgnoredErrors: Array.from(ignored),
        notice: { text: 'Added draft exception for this World-Law flag.', tone: 'ok' },
      });
    });
  });

  document.querySelectorAll('[data-lab-unstage]').forEach((btn) => {
    btn.addEventListener('click', () => {
      const cur = store.get();
      const idx = Number(btn.dataset.labUnstage);
      const next = (cur.labStagedPackets || []).filter((_, i) => i !== idx);
      store.set({ labStagedPackets: next, notice: { text: 'Removed item from Staged Cooker Queue.', tone: 'ok' } });
    });
  });

  document.getElementById('v2LabClearQueueBtn')?.addEventListener('click', () => {
    store.set({ labStagedPackets: [], notice: { text: 'Cleared Staged Cooker Queue.', tone: 'ok' } });
  });

  document.getElementById('v2LabRunCookerBtn')?.addEventListener('click', () => {
    if (typeof onRunMainCooker === 'function') onRunMainCooker();
  });
}
