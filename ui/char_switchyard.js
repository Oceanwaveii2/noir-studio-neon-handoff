/* Noir Fiction Studio — Milestone 2: Character Form Switchyard & Direct-Drop Firewall */

import { escapeHtml } from './compose.js';
import { playTick, playSelect, playAlert } from './sound.js';
import { NoirApi } from './api.js';
import { summarizeLiveCharacterLinks } from './live_graph_bridge.js';
import { PIN_ROLES, openMediaVault, uploadMediaFiles } from './media_vault.js';
import { openFormBoard } from './form-board.js';

const IMAGE_EXT_RE = /\.(png|jpe?g|webp|gif|svg)$/i;
const swState = {
  mode: 'episodic', showStandby: true, characterId: '', selectedFormId: '', selectedBeat: '',
  relationshipTarget: '', allHousehold: false,
  pinRole: 'wardrobe_reference', camera: { tx: 24, ty: 20, zoom: 1 },
  nodePos: {}, dropTray: [], toast: null, modalOpen: false,
};

function formStatus(form, beat) {
  if (form.episode_status === 'locked_future') return 'Locked Future';
  const status = beat?.forms?.[form.port_id] || form.episode_status || form.status;
  return status === 'active' ? 'Active' : 'Standby';
}

function activeProject(state) {
  const graph = state?.formGraph;
  if (!graph) return null;
  const beat = graph.beats?.find((item) => item.id === swState.selectedBeat);
  const characters = graph.junctions.map((group) => {
    const forms = group.forms.map((form) => ({ ...form, portrait: form.image, badge: formStatus(form, beat) }));
    const active = forms.find((form) => form.badge === 'Active')?.id || '';
    return { ...group, id: group.character_id, name: group.label || group.character_id,
      forms, active, portrait: forms[0]?.image };
  });
  return { characters, graph };
}

function activeCharacter(proj) {
  return proj?.characters.find((c) => c.id === swState.characterId) || proj?.characters[0];
}

function currentForm(char) {
  return char?.forms.find((form) => form.id === swState.selectedFormId)
    || char?.forms.find((form) => form.id === char.active) || char?.forms[0];
}

function pinTarget(state, character, form) {
  const group = activeProject(state)?.characters.find((item) => item.id === character);
  const selected = form || group?.active;
  return group?.forms.some((item) => item.id === selected) ? { character, form: selected } : null;
}

function initialsFor(name) {
  return name.trim().split(/\s+/).slice(0, 2).map((word) => word[0]).join('').toUpperCase();
}

function defaultPos(key, x, y) {
  return swState.nodePos[key] ||= { x, y };
}

function getLodLabel(zoom) {
  if (zoom >= 1.25) return 'Detail';
  if (zoom >= 0.65) return 'Switchyard';
  return 'Constellation';
}

function buildSwitchyardScene(proj) {
  const chars = proj ? (swState.allHousehold ? proj.characters : [activeCharacter(proj)].filter(Boolean)) : [];
  const nodes = [], wires = [];
  let y = 36;
  for (const char of chars) {
    const forms = char.forms.filter((form) => swState.mode === 'global' || swState.showStandby || form.badge === 'Active');
    const anchor = { key: `id:${char.id}`, char, kind: 'identity', title: char.name, portrait: char.portrait,
      subtitle: `${char.forms.length} saved forms`, w: 198, h: 108, mint: true,
      ...defaultPos(`id:${char.id}`, 24, y) };
    nodes.push(anchor);
    const visible = new Set(forms.map((form) => form.id));
    for (const [index, form] of forms.entries()) {
      const key = `form:${char.id}:${form.id}`;
      const mint = form.badge === 'Active';
      const x = 24 + index * 264;
      nodes.push({ key, kind: 'form', char, form, title: form.display_label || form.label,
        subtitle: form.kind, portrait: form.portrait, w: 240, h: 110, mint, copper: !mint,
        ...defaultPos(key, x, y + 148) });
      wires.push({ fromKey: visible.has(form.after) ? `form:${char.id}:${form.after}` : anchor.key,
        toKey: key, tone: mint ? 'mint' : 'idle' });
      const mindKey = `mind:${char.id}:${form.id}`;
      const linked = proj.graph.nodes.find((node) => node.id === form.link?.node_id);
      nodes.push({ key: mindKey, char, form, kind: 'mind', title: linked?.label || 'Mind socket',
        subtitle: form.link?.kind === 'super_character' ? 'Super Character · open schema'
          : form.link ? 'Digital Mind' : 'Available for a Mind or Super Character',
        w: 240, h: 106, mint: Boolean(form.link && mint), ...defaultPos(mindKey, x, y + 298) });
      wires.push({ fromKey: key, toKey: mindKey, tone: mint && linked ? 'mint' : 'idle' });
    }
    y += 460;
  }
  const scope = proj?.graph.stage_scope;
  for (const edge of proj?.graph.relationship_edges || []) {
    if (edge.retired || (swState.mode === 'episodic' && (edge.episode !== scope?.episode || edge.branch !== scope?.branch))) continue;
    const { from, to } = edge;
    wires.push({ fromKey: `form:${from.character}:${from.form}`, toKey: `form:${to.character}:${to.form}`, tone: 'directed' });
  }
  return { nodes, wires, stageHeight: Math.max(540, y) };
}

function wirePath(fromNode, toNode) {
  // Vertical Top -> Bottom Bezier (Bottom-Center -> Top-Center)
  const x1 = fromNode.x + Math.round(fromNode.w / 2);
  const y1 = fromNode.y + fromNode.h;
  const x2 = toNode.x + Math.round(toNode.w / 2);
  const y2 = toNode.y;
  const dy = Math.max(32, Math.abs(y2 - y1) * 0.45);
  return `M ${x1} ${y1} C ${x1} ${y1 + dy}, ${x2} ${y2 - dy}, ${x2} ${y2}`;
}

export function renderCharSwitchyard(state = null) {
  const proj = activeProject(state);
  if (state?.graphSelection?.characterId && proj?.characters?.some((c) => c.id === state.graphSelection.characterId)) {
    swState.characterId = state.graphSelection.characterId;
  }
  const char = activeCharacter(proj);
  const liveLinksMap = summarizeLiveCharacterLinks(state, proj?.characters || []);
  const charLinks = char ? (liveLinksMap.get(char.id) || []) : [];
  const { nodes, wires, stageHeight } = buildSwitchyardScene(proj);
  const nodeMap = new Map(nodes.map((n) => [n.key, n]));
  const zoomPct = Math.round(swState.camera.zoom * 100);
  const lod = getLodLabel(swState.camera.zoom).toLowerCase();

  const selectedForm = currentForm(char);

  return `
    <div class="sw-shell" id="swSwitchyardMount">
      <aside class="sw-rail" aria-label="Character Index">
        <div class="sw-rail-head">
          <span>Character view</span>
          <button type="button" class="v2-mini-btn" id="swAllHouseholdBtn" aria-pressed="${swState.allHousehold}">All characters</button>
        </div>
        <div class="sw-proj-pills">
          <button type="button" class="sw-proj-btn" data-sw-mode="global" aria-pressed="${swState.mode === 'global'}">Global Master Vault</button>
          <button type="button" class="sw-proj-btn" data-sw-mode="episodic" aria-pressed="${swState.mode === 'episodic'}">Episodic Staging</button>
        </div>
        ${swState.mode === 'episodic' ? `<div class="sw-beat-box">
          <strong>${escapeHtml(state?.episodeState?.episode?.title || 'Select an episode')}</strong>
          <label><input type="checkbox" id="swShowStandby" ${swState.showStandby ? 'checked' : ''}> Show standby and future forms</label>
          ${proj?.graph.beats?.length ? `<label>Saved beat<select id="swBeatSelect" class="sw-pin-select">
            <option value="">Episode staging</option>
            ${proj.graph.beats.map((beat) => `<option value="${escapeHtml(beat.id)}" ${beat.id === swState.selectedBeat ? 'selected' : ''}>${escapeHtml(beat.label)}</option>`).join('')}
          </select></label>` : ''}
        </div>` : ''}

        <div class="sw-rail-head"><span>Characters (${(proj?.characters || []).length})</span></div>
        <div class="sw-char-list">
          ${(proj?.characters || []).map((c) => {
            const cLinks = (liveLinksMap.get(c.id) || []).length;
            const avatarHtml = c.portrait
              ? `<img class="sw-char-avatar" src="${escapeHtml(c.portrait)}" alt="${escapeHtml(c.name)}">`
              : `<span class="sw-char-avatar is-initials" aria-hidden="true">${escapeHtml(initialsFor(c.name))}</span>`;
            return `
            <button type="button" class="sw-char-btn" data-sw-char="${escapeHtml(c.id)}" aria-current="${c.id === char?.id ? 'true' : 'false'}">
              ${avatarHtml}
              <div class="sw-char-meta">
                <strong>${escapeHtml(c.name)}</strong>
                <small>${c.forms.length} forms${cLinks ? ` · 🔗 ${cLinks}` : ''}</small>
              </div>
            </button>
          `;
          }).join('')}
        </div>
      </aside>

      <section class="sw-canvas-col" aria-label="Form Switchyard Canvas">
        <div class="sw-toolbar">
          <div class="sw-col-crumbs">
            <span>Identity</span> → <span>Forms</span> → <span>Mind sockets</span>
          </div>
          <div class="sw-canvas-actions">
            <span class="sw-lod-pill" id="swLodPill">LOD: ${getLodLabel(swState.camera.zoom)}</span>
            <button type="button" class="v2-mini-btn" id="swZoomOutBtn">-</button>
            <span class="sw-lod-pill" id="swZoomPct">${zoomPct}%</span>
            <button type="button" class="v2-mini-btn" id="swZoomInBtn">+</button>
            <button type="button" class="v2-mini-btn" id="swFitBtn">Fit (Home)</button>
          </div>
        </div>

        <div class="sw-viewport" id="swViewport">
          <div class="sw-stage" id="swStage" data-lod="${lod}" style="height:${stageHeight}px; transform: translate(${swState.camera.tx}px, ${swState.camera.ty}px) scale(${swState.camera.zoom});">
            <svg class="sw-wires" id="swWires" viewBox="0 0 1200 ${stageHeight}">
              <defs><marker id="swDirectionArrow" markerWidth="8" markerHeight="8" refX="7" refY="4" orient="auto"><path d="M 0 0 L 8 4 L 0 8 z" fill="#ffb07d"></path></marker></defs>
              ${wires.map((w) => {
                const fn = nodeMap.get(w.fromKey);
                const tn = nodeMap.get(w.toKey);
                if (!fn || !tn) return '';
                const cls = w.tone === 'mint' ? 'is-mint' : w.tone === 'directed' ? 'is-copper' : '';
                return `<path class="sw-wire ${cls}" ${w.tone === 'directed' ? 'marker-end="url(#swDirectionArrow)"' : ''} data-wire-from="${escapeHtml(w.fromKey)}" data-wire-to="${escapeHtml(w.toKey)}" d="${wirePath(fn, tn)}"></path>`;
              }).join('')}
            </svg>

            ${nodes.map((n) => `
              <article
                class="sw-node sw-node-${n.kind} ${n.mint ? 'is-mint' : ''} ${n.copper ? 'is-copper' : ''}"
                data-node-key="${escapeHtml(n.key)}"
                data-node-kind="${n.kind}"
                data-char-id="${escapeHtml(n.char.id)}"
                data-form-id="${escapeHtml(n.form?.id || '')}"
                style="left:${n.x}px; top:${n.y}px;"
                tabindex="0"
              >
                <div class="sw-node-head">
                  <span>${{ identity: 'Identity', form: 'Form', mind: 'Mind socket' }[n.kind]}</span>
                  <span class="sw-badge ${n.mint ? 'is-mint' : n.copper ? 'is-copper' : ''}">
                    ${n.kind === 'form' ? escapeHtml(n.form.badge) : n.kind === 'mind' ? (n.form.link ? 'Linked' : 'Open') : 'Root'}
                  </span>
                </div>
                <div class="sw-node-body">
                  ${n.portrait ? `<img class="sw-node-thumb" src="${escapeHtml(n.portrait)}" alt="${escapeHtml(n.title)}">` : ''}
                  <div class="sw-node-info">
                    <strong>${escapeHtml(n.title)}</strong>
                    <small>${escapeHtml(String(n.subtitle || '').slice(0, 72))}</small>
                  </div>
                </div>
              </article>
            `).join('')}
          </div>

          <div class="sw-drop-tray" id="swDropTray">
            <span>Direct Drop: drag <code>.mp4/.wav/.png/.md</code> onto any Form or Mind node</span>
            ${swState.dropTray.map((d, idx) => `
              <span class="sw-tray-chip" draggable="true" data-tray-idx="${idx}">${escapeHtml(d.name)}</span>
            `).join('')}
          </div>

          ${swState.toast ? `<div class="sw-toast" id="swToast" data-tone="${swState.toast.tone}">${escapeHtml(swState.toast.text)}</div>` : ''}
        </div>
      </section>

      <aside class="sw-inspector" aria-label="Form Board Inspector">
        ${char ? `
          <div class="sw-insp-card">
            <h3>${escapeHtml(selectedForm?.display_label || char.name)}</h3>
            <span class="sw-badge ${selectedForm?.badge === 'Active' ? 'is-mint' : 'is-copper'}">${escapeHtml(selectedForm?.badge || '')}</span>
            <button type="button" class="v2-btn v2-btn-accent" id="swOpenModalBtn">Open Form Interior</button>
            ${swState.mode === 'episodic' && selectedForm?.badge === 'Standby' && !swState.selectedBeat
              ? '<button type="button" class="v2-btn" id="swStageFormBtn">Route into episode</button>' : ''}
            <div class="sw-insp-actions">
              <button type="button" class="v2-mini-btn" data-sw-history="undo_graph" ${proj.graph.can_undo_graph ? '' : 'disabled'}>Undo graph</button>
              <button type="button" class="v2-mini-btn" data-sw-history="redo_graph" ${proj.graph.can_redo_graph ? '' : 'disabled'}>Redo graph</button>
            </div>
          </div>
          <div class="sw-insp-card">
            <h3>Typed Media Pins</h3>
            <select id="swPinRoleSelect" class="sw-pin-select" aria-label="Typed Pin Role">
              ${PIN_ROLES.map((role) => `<option value="${role.id}" ${swState.pinRole === role.id ? 'selected' : ''}>${role.label}</option>`).join('')}
            </select>
            <button type="button" class="v2-mini-btn" id="swMediaVaultBtn" data-open-media-vault
              data-mv-char="${escapeHtml(char.id)}" data-mv-form="${escapeHtml(selectedForm?.id || '')}">Open Media Vault</button>
          </div>

          ${renderRelationshipEditor(proj, char, selectedForm)}

          <div class="sw-insp-card">
            <h3>Linked Compose Blocks (${charLinks.length})</h3>
            ${charLinks.length ? charLinks.slice(0, 6).map((lk) => `
              <div class="sg-rhythm-item">
                <span><strong>${escapeHtml(lk.beatId)}</strong> · ${escapeHtml(lk.snippet || lk.kind)}</span>
                <button type="button" class="v2-mini-btn" data-sw-jump-block="${escapeHtml(lk.blockId)}">Jump ↗</button>
              </div>
            `).join('') : '<small>No blocks linked in current Compose episode yet.</small>'}
          </div>

        ` : '<div class="sw-insp-card"><p class="v2-muted">Choose a saved episode to open its Character Graph.</p></div>'}
      </aside>
    </div>

    <dialog class="sw-modal" id="swInteriorModal" aria-label="Form Interior">
      ${char ? renderInteriorModalBody(proj, char, selectedForm) : ''}
    </dialog>
  `;
}

function renderRelationshipEditor(proj, char, form) {
  const scope = proj.graph.stage_scope;
  if (!scope || !form) return '';
  const options = proj.characters.filter((candidate) => candidate.id !== char.id)
    .flatMap((candidate) => candidate.forms.map((target) => ({ char: candidate, form: target })));
  const selected = options.find((option) => option.form.port_id === swState.relationshipTarget) || options[0];
  if (!selected) return '';
  const edges = proj.graph.relationship_edges || [];
  const current = edges.find((edge) => edge.episode === scope.episode && edge.branch === scope.branch
    && edge.from.character === char.id && edge.from.form === form.id
    && edge.to.character === selected.char.id && edge.to.form === selected.form.id);
  const incident = edges.filter((edge) => !edge.retired && (edge.from.character === char.id || edge.to.character === char.id)
    && (swState.mode === 'global' || (edge.episode === scope.episode && edge.branch === scope.branch)));
  const name = ({ character, form: id }) => {
    const owner = proj.characters.find((item) => item.id === character);
    return owner?.forms.find((item) => item.id === id)?.label || id;
  };
  return `<form class="sw-insp-card" id="swRelationshipForm">
    <h3>Directed relationships</h3>
    ${incident.map((edge) => `<small>${escapeHtml(name(edge.from))} → ${escapeHtml(name(edge.to))}${swState.mode === 'global' ? ` · ${escapeHtml(edge.episode)}` : ''}</small>`).join('')}
    <small>From ${escapeHtml(form.label)}</small>
    <label>To <select id="swRelationshipTarget" name="target" class="sw-pin-select">
      ${options.map(({ char: peer, form: target }) => `<option value="${escapeHtml(target.port_id)}" data-character="${escapeHtml(peer.id)}" data-form="${escapeHtml(target.id)}" ${target === selected.form ? 'selected' : ''}>${escapeHtml(peer.name)} · ${escapeHtml(target.label)}</option>`).join('')}
    </select></label>
    <label>Patience % <input name="patience" type="number" min="0" max="100" value="${Math.round((current?.patience ?? 0.5) * 100)}" required></label>
    <label>Friction % <input name="friction" type="number" min="0" max="100" value="${Math.round((current?.friction ?? 0.5) * 100)}" required></label>
    <label>Bridging stage direction <input name="direction" value="${escapeHtml(current?.bridging_direction || '')}" maxlength="300"></label>
    <div class="sw-insp-actions">
      <button type="submit" class="v2-mini-btn">Save direction</button>
      ${current && !current.retired ? '<button type="submit" value="retire" class="v2-mini-btn">Retire direction</button>' : ''}
    </div>
  </form>`;
}

function renderInteriorModalBody(proj, char, form) {
  if (!form) return '';
  const data = char.node_data?.[form.port_id] || {};
  const socket = proj.graph.nodes.find((node) => node.id === form.link?.node_id);
  const openSchema = form.link?.kind === 'super_character';
  const editable = proj.graph.editable ? '' : 'disabled';
  return `
    <div class="sw-modal-head">
      <strong>${escapeHtml(char.name)} / ${escapeHtml(form.display_label || form.label)}</strong>
      <button type="button" class="v2-btn" id="swCloseModalBtn">Back to Character Graph</button>
    </div>
    <div class="sw-modal-body sw-interior-grid">
      <section class="sw-insp-card" aria-label="Physical Identity and Wardrobe">
        <h3>Physical Identity &amp; Wardrobe</h3>
        ${form.portrait ? `<img class="sw-insp-portrait" src="${escapeHtml(form.portrait)}" alt="${escapeHtml(form.label)}">` : ''}
        <label>Appearance <textarea id="swAppearance" rows="3" ${editable}>${escapeHtml(data.appearance || '')}</textarea></label>
        <label>Wardrobe notes <textarea id="swWardrobe" rows="3" ${editable}>${escapeHtml(data.wardrobe || '')}</textarea></label>
        <div class="sw-insp-actions">
          <button type="button" class="v2-mini-btn" id="swSavePhysical" ${editable}>Save appearance</button>
          <button type="button" class="v2-mini-btn" id="swReferenceBoard">Reference board</button>
          <button type="button" class="v2-mini-btn" id="swWardrobeMedia">Wardrobe media</button>
        </div>
      </section>
      <section class="sw-insp-card" aria-label="Behavioral Mind Graph">
        <h3>Behavioral Mind Graph</h3>
        <label>Linked Mind <select class="sw-pin-select" id="swMindLink" ${editable}>
          <option value="">Open socket</option>
          ${proj.graph.nodes.map((node) => `<option value="${escapeHtml(node.id)}" ${node.id === form.link?.node_id ? 'selected' : ''}>${escapeHtml(node.label)} · ${node.kind === 'super_character' ? 'Super Character' : 'Digital Mind'}</option>`).join('')}
        </select></label>
        ${openSchema ? `<small>Super Character · open schema</small><pre>${escapeHtml(JSON.stringify(socket?.mind_payload ?? {}, null, 2))}</pre>` : ''}
        <form id="swCreateSuper">
          <label>Super Character name <input name="label" maxlength="100" required ${editable}></label>
          <label>Mind payload (JSON) <textarea name="payload" rows="4" ${editable}>{}</textarea></label>
          <button type="submit" class="v2-mini-btn" ${editable}>Create and link Super Character</button>
        </form>
      </section>
    </div>`;
}

export function bindCharSwitchyard(stateOrCb, maybeCb, onJumpToBlock) {
  const state = typeof stateOrCb === 'function' ? null : stateOrCb;
  const onRerender = typeof stateOrCb === 'function' ? stateOrCb : maybeCb;
  const store = window.__noirStore;
  const rerender = () => {
    const mount = document.getElementById('swSwitchyardMount')?.parentElement;
    if (mount) {
      const current = store?.get() || state;
      mount.innerHTML = renderCharSwitchyard(current);
      bindCharSwitchyard(current, onRerender, onJumpToBlock);
    } else if (onRerender) {
      onRerender();
    }
  };
  document.querySelectorAll('[data-sw-jump-block]').forEach((btn) => {
    btn.addEventListener('click', () => {
      playSelect();
      if (onJumpToBlock) onJumpToBlock(btn.dataset.swJumpBlock);
    });
  });

  if (swState.modalOpen) {
    const dlg = document.getElementById('swInteriorModal');
    if (dlg && !dlg.open) dlg.showModal();
  }

  const current = () => {
    const saved = store.get();
    const proj = activeProject(saved);
    const char = activeCharacter(proj);
    return { saved, proj, char, form: currentForm(char) };
  };
  let changing = false;
  const change = async (action, fields = {}) => {
    const { saved, proj } = current();
    if (changing || !proj?.graph.editable) return;
    changing = true;
    try {
      const result = await NoirApi.formGraphAction({ ...proj.graph.stage_scope, ...fields, action,
        episode: saved.episodeId, revision: proj.graph.revision });
      if (store.get().episodeId === saved.episodeId) {
        store.set({ formGraph: result, notice: { text: 'Saved Character Graph.', tone: 'ok' } });
      }
    } catch (error) {
      store.set({ notice: { text: error.message, tone: 'err' } });
    } finally {
      changing = false;
    }
  };
  const choose = (character, form = '') => {
    swState.characterId = character;
    swState.selectedFormId = form;
    store.setQuiet({ graphSelection: { characterId: character } });
  };
  document.querySelectorAll('[data-sw-mode]').forEach((btn) => btn.addEventListener('click', () => {
    swState.mode = btn.dataset.swMode;
    if (swState.mode === 'global') swState.selectedBeat = '';
    rerender();
  }));
  document.querySelectorAll('[data-sw-char]').forEach((btn) => btn.addEventListener('click', () => {
    playSelect();
    choose(btn.dataset.swChar);
    rerender();
  }));
  document.getElementById('swShowStandby')?.addEventListener('change', (event) => {
    swState.showStandby = event.target.checked;
    rerender();
  });
  document.getElementById('swBeatSelect')?.addEventListener('change', (event) => {
    swState.selectedBeat = event.target.value;
    rerender();
  });
  document.getElementById('swStageFormBtn')?.addEventListener('click', () => {
    const { char, form } = current();
    if (form) void change('stage_form', { character: char.id, form: form.id });
  });
  document.querySelectorAll('[data-sw-history]').forEach((btn) => btn.addEventListener('click', () => {
    void change(btn.dataset.swHistory);
  }));
  document.getElementById('swRelationshipTarget')?.addEventListener('change', (event) => {
    swState.relationshipTarget = event.target.value;
    rerender();
  });
  document.getElementById('swRelationshipForm')?.addEventListener('submit', (event) => {
    event.preventDefault();
    const { char, form } = current();
    const options = event.target.elements.target.selectedOptions;
    if (!form || !options[0]) return;
    const values = new FormData(event.target);
    void change('set_relationship', { character: char.id, form: form.id,
      target_character: options[0].dataset.character, target_form: options[0].dataset.form,
      patience: Number(values.get('patience')) / 100, friction: Number(values.get('friction')) / 100,
      bridging_direction: values.get('direction'), retired: event.submitter?.value === 'retire' });
  });
  document.getElementById('swPinRoleSelect')?.addEventListener('change', (event) => {
    swState.pinRole = event.target.value;
  });
  document.getElementById('swAllHouseholdBtn')?.addEventListener('click', () => {
    swState.allHousehold = !swState.allHousehold;
    rerender();
  });
  const dialog = document.getElementById('swInteriorModal');
  const open = () => { swState.modalOpen = true; rerender(); };
  const close = () => { swState.modalOpen = false; dialog?.close(); };
  dialog?.addEventListener('close', () => { swState.modalOpen = false; });
  document.getElementById('swOpenModalBtn')?.addEventListener('click', open);
  document.getElementById('swCloseModalBtn')?.addEventListener('click', close);
  document.getElementById('swReferenceBoard')?.addEventListener('click', () => {
    const { char, form } = current();
    close();
    if (form) openFormBoard({ store, api: NoirApi }, char.id, form.port_id);
  });
  document.getElementById('swWardrobeMedia')?.addEventListener('click', () => {
    const { char, form } = current();
    close();
    if (!form) return;
    store.setQuiet({ mediaVaultPinRole: 'wardrobe_reference' });
    openMediaVault(store, { character: char.id, form: form.id });
  });
  document.getElementById('swSavePhysical')?.addEventListener('click', () => {
    const { char, form } = current();
    if (!form) return;
    const content = { ...char.node_data?.[form.port_id], appearance: document.getElementById('swAppearance').value,
      wardrobe: document.getElementById('swWardrobe').value };
    void change('save_node_data', { character: char.id, node: form.port_id, content });
  });
  document.getElementById('swMindLink')?.addEventListener('change', (event) => {
    const { form } = current();
    if (form) void change('set_link', { port: form.port_id, node_id: event.target.value || null });
  });
  document.getElementById('swCreateSuper')?.addEventListener('submit', (event) => {
    event.preventDefault();
    const { form } = current();
    if (!form) return;
    const values = new FormData(event.target);
    try {
      const mind_payload = JSON.parse(values.get('payload'));
      void change('create_mind_link', { kind: 'super_character', port: form.port_id,
        label: values.get('label'), mind_payload });
    } catch (error) {
      store.set({ notice: { text: 'Enter valid JSON for the Mind payload.', tone: 'err' } });
    }
  });

  // Pan & Zoom
  const viewport = document.getElementById('swViewport');
  const stage = document.getElementById('swStage');
  const applyCam = () => {
    if (!stage) return;
    stage.style.transform = `translate(${swState.camera.tx}px, ${swState.camera.ty}px) scale(${swState.camera.zoom})`;
    stage.dataset.lod = getLodLabel(swState.camera.zoom).toLowerCase();
    const zp = document.getElementById('swZoomPct');
    const lp = document.getElementById('swLodPill');
    if (zp) zp.textContent = `${Math.round(swState.camera.zoom * 100)}%`;
    if (lp) lp.textContent = `LOD: ${getLodLabel(swState.camera.zoom)}`;
  };

  document.getElementById('swZoomInBtn')?.addEventListener('click', () => {
    swState.camera.zoom = Math.min(2, +(swState.camera.zoom + 0.15).toFixed(2));
    applyCam();
  });
  document.getElementById('swZoomOutBtn')?.addEventListener('click', () => {
    swState.camera.zoom = Math.max(0.4, +(swState.camera.zoom - 0.15).toFixed(2));
    applyCam();
  });
  document.getElementById('swFitBtn')?.addEventListener('click', () => {
    swState.camera = { tx: 24, ty: 22, zoom: 1 };
    applyCam();
  });

  viewport?.addEventListener('wheel', (e) => {
    e.preventDefault();
    const delta = e.deltaY < 0 ? 0.1 : -0.1;
    swState.camera.zoom = Math.max(0.4, Math.min(2.0, +(swState.camera.zoom + delta).toFixed(2)));
    applyCam();
  }, { passive: false });

  // Node Drag + Canvas Pan
  let dragMode = null;
  let dragged = false;
  let selectionTimer;
  viewport?.addEventListener('pointerdown', (e) => {
    if (e.button !== 0 || e.target.closest('button, input, .sw-drop-tray')) return;
    dragged = false;
    e.target.setPointerCapture?.(e.pointerId);
    const nodeEl = e.target.closest('.sw-node');
    if (nodeEl) {
      const key = nodeEl.dataset.nodeKey;
      const pos = swState.nodePos[key];
      if (pos) {
        dragMode = {
          type: 'node',
          key,
          el: nodeEl,
          startX: e.clientX,
          startY: e.clientY,
          origX: pos.x,
          origY: pos.y,
          moved: false,
        };
      }
      return;
    }
    dragMode = { type: 'pan', startX: e.clientX, startY: e.clientY, origTx: swState.camera.tx, origTy: swState.camera.ty };
    viewport.classList.add('is-panning');
  });

  viewport?.addEventListener('pointermove', (e) => {
    if (!dragMode) return;
    if (dragMode.type === 'pan') {
      swState.camera.tx = dragMode.origTx + (e.clientX - dragMode.startX);
      swState.camera.ty = dragMode.origTy + (e.clientY - dragMode.startY);
      applyCam();
      return;
    }
    const dx = (e.clientX - dragMode.startX) / swState.camera.zoom;
    const dy = (e.clientY - dragMode.startY) / swState.camera.zoom;
    if (Math.abs(dx) > 2 || Math.abs(dy) > 2) dragged = true;
    const nx = Math.round(dragMode.origX + dx);
    const ny = Math.round(dragMode.origY + dy);
    swState.nodePos[dragMode.key] = { x: nx, y: ny };
    dragMode.el.style.left = `${nx}px`;
    dragMode.el.style.top = `${ny}px`;
    const proj = activeProject(store.get());
    const { nodes } = buildSwitchyardScene(proj);
    const nmap = new Map(nodes.map((n) => [n.key, n]));
    document.querySelectorAll('#swWires .sw-wire').forEach((pathEl) => {
      const fn = nmap.get(pathEl.dataset.wireFrom);
      const tn = nmap.get(pathEl.dataset.wireTo);
      if (fn && tn) pathEl.setAttribute('d', wirePath(fn, tn));
    });
  });

  viewport?.addEventListener('pointerup', () => {
    if (dragMode?.type === 'pan') viewport?.classList.remove('is-panning');
    dragMode = null;
  });

  // Node Selection + Double-click Modal + Direct Drag-and-Drop Firewall
  document.querySelectorAll('.sw-node').forEach((nodeEl) => {
    nodeEl.addEventListener('click', (event) => {
      if (dragged || event.detail > 1) return;
      playSelect();
      choose(nodeEl.dataset.charId, nodeEl.dataset.formId);
      document.querySelectorAll('.sw-node[aria-selected="true"]').forEach((node) => node.removeAttribute('aria-selected'));
      nodeEl.setAttribute('aria-selected', 'true');
      clearTimeout(selectionTimer);
      selectionTimer = setTimeout(() => {
        if (nodeEl.isConnected) rerender();
      }, 300);
    });
    nodeEl.addEventListener('dblclick', () => {
      clearTimeout(selectionTimer);
      choose(nodeEl.dataset.charId, nodeEl.dataset.formId);
      open();
    });
    nodeEl.addEventListener('keydown', (event) => {
      if (event.key === 'Enter') {
        clearTimeout(selectionTimer);
        choose(nodeEl.dataset.charId, nodeEl.dataset.formId);
        open();
      }
    });

    nodeEl.addEventListener('dragover', (e) => {
      if (!['form', 'mind'].includes(nodeEl.dataset.nodeKind)) return;
      e.preventDefault();
      nodeEl.classList.add('sw-drop-accept');
    });
    nodeEl.addEventListener('dragleave', () => {
      nodeEl.classList.remove('sw-drop-accept', 'sw-drop-reject');
    });
    nodeEl.addEventListener('drop', async (e) => {
      e.preventDefault();
      e.stopPropagation();
      nodeEl.classList.remove('sw-drop-accept', 'sw-drop-reject');
      const kind = nodeEl.dataset.nodeKind;
      if (!['form', 'mind'].includes(kind)) return;
      const trayIndex = e.dataTransfer?.getData('application/x-noir-media-index');
      const staged = trayIndex ? swState.dropTray[Number(trayIndex)] : null;
      const files = staged ? [staged] : Array.from(e.dataTransfer?.files || []);
      if (!files.length) return;

      if (kind === 'mind' && files.some((file) => file.type.startsWith('image/') || IMAGE_EXT_RE.test(file.name))) {
        playAlert();
        nodeEl.classList.add('sw-drop-reject');
        swState.toast = { text: 'Drop appearance images on the Form node.', tone: 'err' };
        setTimeout(() => rerender(), 220);
        return;
      }

      const target = pinTarget(store.get(), nodeEl.dataset.charId, nodeEl.dataset.formId);
      try {
        if (!target) throw new Error('Choose a saved Character Form before attaching media.');
        const pinRole = kind === 'mind' ? 'personality_mind' : swState.pinRole;
        const result = await uploadMediaFiles(store, files, { target, pinRole });
        if (result.pins.length && staged) swState.dropTray = swState.dropTray.filter((file) => file !== staged);
        swState.toast = {
          text: result.errors.join(' · ') || `Saved ${result.pins.length} media pin(s).`,
          tone: result.errors.length ? 'err' : 'ok',
        };
      } catch (err) {
        swState.toast = { text: err.message, tone: 'err' };
      }
      rerender();
    });
  });

  document.querySelectorAll('[data-tray-idx]').forEach((chip) => {
    chip.addEventListener('dragstart', (e) => {
      e.dataTransfer?.setData('application/x-noir-media-index', chip.dataset.trayIdx);
    });
  });

  viewport?.addEventListener('dragover', (e) => e.preventDefault());
  viewport?.addEventListener('drop', (e) => {
    if (e.target.closest('.sw-node')) return;
    e.preventDefault();
    const files = Array.from(e.dataTransfer?.files || []);
    if (!files.length) return;
    swState.dropTray.push(...files);
    swState.toast = { text: `Staged ${files.length} file(s). Drag them onto a Form or Mind node.`, tone: 'ok' };
    rerender();
  });
}
