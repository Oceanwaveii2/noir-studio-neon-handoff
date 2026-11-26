/* A reference board uses the same revisioned graph store as its form node. */
import { escapeHtml as esc } from './compose.js';

const COLUMN = 276;
const ROW = 280;
const PAD = 24;
const STEP = 20;
const MAX_FILE = 20_000_000;
const emptyBoard = () => ({ notes: [], positions: {} });

function readFile(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onerror = () => reject(new Error('This file could not be read.'));
    reader.onload = () => resolve(String(reader.result).split(',', 2)[1]);
    reader.readAsDataURL(file);
  });
}

function attachmentUrl(episode, id, preview = false) {
  const query = new URLSearchParams({ episode, id });
  if (preview) query.set('preview', '1');
  return '/api/form-attachment?' + query;
}

const mindKind = (kind) => kind === 'super_character' ? 'Super Character' : 'Digital Mind';

export function openFormBoard(ctx, character, port, { onChange, openMind } = {}) {
  const { api, store } = ctx;
  const { episodeId: episode, formGraph } = store.get();
  if (!episode || !formGraph || document.querySelector('.v2-form-board[open]')) return;
  let graph = formGraph;
  const getGroup = () => graph.junctions.find((item) => item.character_id === character);
  const getForm = () => getGroup()?.forms.find((item) => item.port_id === port);
  if (!getForm()) return;
  const media = new URLSearchParams({ episode, character, form: getForm().id });

  let draft = structuredClone(getGroup().boards?.[port] || emptyBoard());
  let dirty = false;
  let pending = false;
  let list = false;
  const returnFocus = document.activeElement;
  const dialog = document.createElement('dialog');
  dialog.className = 'v2-form-board';
  dialog.setAttribute('aria-labelledby', 'v2FormBoardTitle');
  dialog.innerHTML = `
    <header class="v2-board-head">
      <div>
        <span class="v2-board-kicker">Character graph / ${esc(getGroup().label || character)}</span>
        <h2 id="v2FormBoardTitle">${esc(getForm().display_label || getForm().label)}</h2>
        <p>Reference board</p>
      </div>
      <button type="button" class="v2-tl-btn" data-board-close aria-label="Close reference board">Close</button>
    </header>
    <div class="v2-board-tools" aria-label="Board tools">
      <button type="button" class="v2-tl-btn v2-tl-btn-primary" data-board-note>+ Note</button>
      <button type="button" class="v2-tl-btn" data-board-pick="image">+ Images</button>
      <button type="button" class="v2-tl-btn" data-board-pick="file">+ Files</button>
      <a class="v2-tl-btn" href="/beat-media?${esc(media.toString())}" target="_blank" rel="noopener">Form media ↗</a>
      <input type="file" hidden multiple accept="image/png,image/jpeg,image/webp" data-board-files="image">
      <input type="file" hidden multiple data-board-files="file">
      <span class="v2-board-tool-gap"></span>
      <button type="button" class="v2-tl-btn" aria-pressed="false" data-board-list>List view</button>
      <button type="button" class="v2-tl-btn" data-board-history="undo_graph">Undo</button>
      <button type="button" class="v2-tl-btn" data-board-history="redo_graph">Redo</button>
    </div>
    <div class="v2-board-viewport" aria-label="Form board cards" tabindex="0">
      <div class="v2-board-canvas"></div>
    </div>
    <footer class="v2-board-foot">
      <span data-board-status role="status" aria-live="polite">Drop files here or move a card by its grip. Board notes stay with this form.</span>
      <button type="button" class="v2-tl-btn" data-board-reload>Reload saved board</button>
      <button type="button" class="v2-tl-btn v2-tl-btn-primary" data-board-save>Save board</button>
    </footer>
  `;
  const $ = (selector) => dialog.querySelector(selector);
  const canvas = $('.v2-board-canvas');
  const viewport = $('.v2-board-viewport');
  const status = $('[data-board-status]');
  const say = (message, error = false) => {
    status.textContent = message;
    status.classList.toggle('is-error', error);
  };
  const filesForForm = () => (getGroup()?.attachments || []).filter((file) => file.node === port);

  function controls() {
    const editable = graph.editable && !pending && !!getForm();
    dialog.querySelectorAll('[data-board-pick], [data-board-note]').forEach((button) => {
      button.disabled = !editable;
    });
    $('[data-board-save]').disabled = !editable || !dirty;
    $('[data-board-reload]').disabled = pending;
    $('[data-board-history="undo_graph"]').disabled = !editable || dirty || !graph.can_undo_graph;
    $('[data-board-history="redo_graph"]').disabled = !editable || dirty || !graph.can_redo_graph;
    canvas.inert = pending;
    dialog.setAttribute('aria-busy', String(pending));
  }

  function edited() {
    dirty = true;
    controls();
    say('Board edits are ready to save.');
  }

  function sync(next, resetDraft = !dirty) {
    graph = next;
    store.setQuiet({ formGraph: next });
    if (resetDraft) {
      draft = structuredClone(getGroup()?.boards?.[port] || emptyBoard());
      dirty = false;
    }
    paint();
  }

  async function run(work) {
    if (pending) return;
    pending = true;
    controls();
    try {
      await work();
    } catch (error) {
      say(error.message || 'The board could not be saved.', true);
    } finally {
      pending = false;
      controls();
    }
  }

  const change = (payload) => api.formGraphAction({ episode, revision: graph.revision, ...payload });

  function move(card, key, x, y) {
    const point = {
      x: Math.max(0, Math.min(3200, Math.round(x))),
      y: Math.max(0, Math.min(24000, Math.round(y))),
    };
    draft.positions[key] = point;
    card.style.left = point.x + 'px';
    card.style.top = point.y + 'px';
    edited();
  }

  function resizeCanvas() {
    if (list) return;
    let width = 884;
    let height = 433;
    for (const card of canvas.querySelectorAll('.v2-board-card')) {
      width = Math.max(width, card.offsetLeft + card.offsetWidth + PAD);
      height = Math.max(height, card.offsetTop + card.offsetHeight + PAD);
    }
    canvas.style.width = width + 'px';
    canvas.style.minHeight = height + 'px';
  }

  function card(key, index, type, title, content, tone = '') {
    const columns = viewport.clientWidth >= 1120 ? 4 : 3;
    const point = draft.positions[key] || {
      x: PAD + (index % columns) * COLUMN,
      y: PAD + Math.floor(index / columns) * ROW,
    };
    const element = document.createElement('article');
    element.className = 'v2-board-card ' + tone;
    if (!list) {
      element.style.left = point.x + 'px';
      element.style.top = point.y + 'px';
    }
    element.innerHTML = `
      <div class="v2-board-card-head">
        <span>${esc(type)}</span>
        <button type="button" data-board-move aria-label="Move ${esc(title)} card" title="Drag or press arrow keys to move">⠿</button>
      </div>
      <div class="v2-board-card-body">${content}</div>
    `;
    canvas.append(element);
    const grip = element.querySelector('[data-board-move]');
    grip.disabled = list || !graph.editable;
    grip.addEventListener('keydown', (event) => {
      const delta = { ArrowLeft: [-STEP, 0], ArrowRight: [STEP, 0], ArrowUp: [0, -STEP], ArrowDown: [0, STEP] }[event.key];
      if (!delta) return;
      event.preventDefault();
      move(element, key, element.offsetLeft + delta[0], element.offsetTop + delta[1]);
      resizeCanvas();
    });
    let origin;
    grip.addEventListener('pointerdown', (event) => {
      if (event.button !== 0) return;
      origin = { id: event.pointerId, x: event.clientX, y: event.clientY, left: element.offsetLeft, top: element.offsetTop };
      grip.setPointerCapture(event.pointerId);
    });
    grip.addEventListener('pointermove', (event) => {
      if (origin?.id !== event.pointerId || !event.buttons) return;
      const dx = event.clientX - origin.x;
      const dy = event.clientY - origin.y;
      if (dx || dy) move(element, key, origin.left + dx, origin.top + dy);
    });
    const finish = () => { if (origin) { origin = null; resizeCanvas(); } };
    grip.addEventListener('lostpointercapture', finish);
    return element;
  }

  function paint() {
    const form = getForm();
    canvas.replaceChildren();
    canvas.classList.toggle('is-list', list);
    canvas.style.width = '';
    canvas.style.minHeight = '';
    if (!form) {
      canvas.textContent = 'This form is no longer in the graph.';
      controls();
      return;
    }
    const portrait = form.image && (/^\/images\//.test(form.image) || /^data:image\/(?:png|jpeg|webp);base64,/.test(form.image));
    card('portrait', 0, 'Form portrait', 'portrait', `
      ${portrait ? `<img class="v2-board-image" src="${esc(form.image)}" alt="${esc(form.display_label || form.label)}">`
                 : '<div class="v2-board-no-image">No portrait for this form</div>'}
      <strong>${esc(form.display_label || form.label)}</strong>
      <small>${esc(form.kind || 'form')} · ${form.status === 'planning_only' ? 'Planning view' : esc(form.status || 'Form board')}</small>
    `);
    const target = (graph.nodes || []).find((node) => node.id === form.link?.node_id);
    const mind = card('mind', 1, 'Mind connection', 'mind', `
      <strong>${target ? esc(target.label) : 'No mind connected'}</strong>
      <small>${target ? esc(mindKind(target.kind)) + ' · Linked to this form' : 'Choose an existing mind or create one.'}</small>
      <label>Character mind
        <select data-board-target aria-label="Character mind">
          <option value="">None</option>
          ${(graph.nodes || []).map((node) => `<option value="${esc(node.id)}" ${target?.id === node.id ? 'selected' : ''}>${esc(node.label)} · ${esc(mindKind(node.kind))}</option>`).join('')}
        </select>
      </label>
      <div class="v2-board-card-actions">
        <button type="button" class="v2-tl-btn" data-board-connect>Save connection</button>
        ${target && openMind ? '<button type="button" class="v2-tl-btn" data-board-open-mind>Open profile</button>' : ''}
      </div>
      <details>
        <summary>New Digital Mind</summary>
        <form data-board-new-mind>
          <label>Name <input name="name" maxlength="80" required></label>
          <button class="v2-tl-btn" type="submit">Create and connect</button>
        </form>
      </details>
    `, 'v2-board-mind');
    mind.querySelector('[data-board-connect]').addEventListener('click', () => run(async () => {
      const nodeId = mind.querySelector('[data-board-target]').value || null;
      sync(await change({ action: 'set_link', port, node_id: nodeId }));
      say(nodeId ? 'Mind linked to this form.' : 'Mind disconnected.');
    }));
    mind.querySelector('[data-board-new-mind]').addEventListener('submit', (event) => {
      event.preventDefault();
      const label = new FormData(event.currentTarget).get('name');
      run(async () => {
        sync(await change({ action: 'create_mind_link', port, label, kind: 'digital_mind' }));
        say('Digital Mind created and linked. Open its profile to add character details.');
      });
    });
    mind.querySelector('[data-board-open-mind]')?.addEventListener('click', () => {
      if (requestClose()) openMind(form, target.id);
    });
    let index = 2;
    for (const note of draft.notes) {
      const key = 'note:' + note.id;
      const element = card(key, index++, 'Note', 'note', `
        <textarea maxlength="4000" aria-label="Board note" placeholder="Write a reference note…">${esc(note.text)}</textarea>
        <button type="button" class="v2-tl-btn" data-board-remove-note>Remove note</button>
      `, 'v2-board-note');
      element.querySelector('textarea').addEventListener('input', (event) => {
        note.text = event.target.value;
        edited();
      });
      element.querySelector('[data-board-remove-note]').addEventListener('click', () => {
        draft.notes = draft.notes.filter((item) => item.id !== note.id);
        delete draft.positions[key];
        edited();
        paint();
      });
    }
    for (const file of filesForForm().filter((entry) => !entry.removed)) {
      const element = card('file:' + file.id, index++, file.image_type ? 'Image' : 'File', file.name, `
        ${file.image_type ? `<a href="${esc(attachmentUrl(episode, file.id, true))}" target="_blank" rel="noopener" aria-label="View ${esc(file.name)}"><img class="v2-board-image" src="${esc(attachmentUrl(episode, file.id, true))}" alt="${esc(file.name)}" loading="lazy"></a>` : ''}
        <strong>${esc(file.name)}</strong>
        <small>${new Intl.NumberFormat().format(file.size)} bytes</small>
        <div class="v2-board-card-actions">
          <a class="v2-tl-btn" href="${esc(attachmentUrl(episode, file.id))}">Download</a>
          <button type="button" class="v2-tl-btn" data-board-remove-file>Remove</button>
        </div>
      `);
      element.querySelector('[data-board-remove-file]').addEventListener('click', () => run(async () => {
        sync(await change({ action: 'remove_attachment', character, node: port, attachment: file.id }));
        say('File removed. Undo can restore it.');
      }));
    }
    if (!graph.editable) canvas.querySelectorAll('input, textarea, select, button').forEach((control) => {
      if (!control.matches('[data-board-open-mind]')) control.disabled = true;
    });
    resizeCanvas();
    controls();
  }

  function requestClose() {
    if (pending) return false;
    if (dirty && !window.confirm('Close without saving the board notes and layout?')) return false;
    dialog.close();
    return true;
  }

  function attach(files, images = false) {
    if (!graph.editable || pending || !files.length) return;
    run(async () => {
      let added = 0;
      for (const file of files) {
        if (!file.size || file.size > MAX_FILE) throw new Error(`Choose a nonempty file up to 20 MB: ${file.name}`);
        const content = await readFile(file);
        const next = await change({ action: 'add_attachment', character, node: port, name: file.name, content, image_only: images });
        sync(next);
        added++;
        say(`${added} ${added === 1 ? 'file saved' : 'files saved'} to this form.`);
      }
    });
  }

  dialog.addEventListener('close', () => {
    dialog.remove();
    onChange?.();
    if (returnFocus instanceof HTMLElement && returnFocus.isConnected) returnFocus.focus();
  }, { once: true });
  dialog.addEventListener('cancel', (event) => { event.preventDefault(); requestClose(); });
  $('[data-board-close]').addEventListener('click', requestClose);
  $('[data-board-note]').addEventListener('click', () => {
    if (draft.notes.length >= 40) { say('This board already has 40 notes.', true); return; }
    draft.notes.push({ id: crypto.randomUUID().replaceAll('-', ''), text: '' });
    edited();
    paint();
    const notes = canvas.querySelectorAll('textarea');
    notes[notes.length - 1].focus();
  });
  dialog.querySelectorAll('[data-board-pick]').forEach((button) => button.addEventListener('click', () => {
    const picker = $('[data-board-files="' + button.dataset.boardPick + '"]');
    picker.click();
  }));
  dialog.querySelectorAll('[data-board-files]').forEach((picker) => picker.addEventListener('change', () => {
    const files = Array.from(picker.files);
    picker.value = '';
    attach(files, picker.dataset.boardFiles === 'image');
  }));
  viewport.addEventListener('dragover', (event) => {
    if (!event.dataTransfer.types.includes('Files')) return;
    event.preventDefault();
    event.dataTransfer.dropEffect = graph.editable && !pending ? 'copy' : 'none';
    viewport.classList.add('is-drop');
  });
  viewport.addEventListener('dragleave', (event) => {
    if (!viewport.contains(event.relatedTarget)) viewport.classList.remove('is-drop');
  });
  viewport.addEventListener('drop', (event) => {
    event.preventDefault();
    viewport.classList.remove('is-drop');
    attach(Array.from(event.dataTransfer.files));
  });
  $('[data-board-list]').addEventListener('click', (event) => {
    list = !list;
    event.currentTarget.setAttribute('aria-pressed', String(list));
    event.currentTarget.textContent = list ? 'Canvas view' : 'List view';
    paint();
  });
  $('[data-board-save]').addEventListener('click', () => run(async () => {
    sync(await change({ action: 'save_board', character, port, board: draft }), true);
    say('Board saved.');
  }));
  $('[data-board-reload]').addEventListener('click', () => {
    if (dirty && !window.confirm('Reload the saved board and discard current board edits?')) return;
    run(async () => {
      sync(await api.getFormGraph(episode), true);
      say('Saved board reloaded.');
    });
  });
  dialog.querySelectorAll('[data-board-history]').forEach((button) => button.addEventListener('click', () => run(async () => {
    const action = button.dataset.boardHistory;
    sync(await change({ action }), true);
    say(action === 'undo_graph' ? 'Last graph change undone.' : 'Graph change restored.');
  })));
  document.body.append(dialog);
  dialog.showModal();
  paint();
}
