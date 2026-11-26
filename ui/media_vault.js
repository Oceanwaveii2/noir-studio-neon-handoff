/* Noir Fiction Studio v2 — Unified Multimodal Media Vault & Typed Pin Client */

import { escapeHtml } from './compose.js';
import { NoirApi } from './api.js';
import { playPortSnap, playSelect, playTick } from './sound.js';

export const PIN_ROLES = [
  { id: 'catalyst_trigger', label: 'Catalyst Trigger', purpose: 'cutaway', tone: 'is-gag', desc: 'Visual/audio gag beat or branch trigger' },
  { id: 'relationship_chemistry', label: 'Relationship Chemistry', purpose: 'reference', tone: 'is-rel', desc: 'Dynamic or chemistry reference between speakers' },
  { id: 'rhythm_timing', label: 'Rhythm & Timing', purpose: 'timing', tone: 'is-rhythm', desc: 'Beat pause, cutaway cadence, or comic snap' },
  { id: 'personality_mind', label: 'Personality & Mind', purpose: 'performance', tone: 'is-mind', desc: 'Voice, attitude, or mental delivery lens' },
  { id: 'wardrobe_reference', label: 'Wardrobe & Appearance', purpose: 'appearance', tone: 'is-form', desc: 'Visual appearance, outfit, or form look' },
];

const vaultLoads = new WeakMap();

export function resolveEpisodeScope(state) {
  const ep = state?.episodeState?.episode;
  if (!ep?.id || (state.episodeId && state.episodeId !== ep.id)) return null;
  const project = state?.episodeState?.scope?.project_id || state?.episodeState?.workspace?.project_id
    || state?.timeline?.scope?.project_id
    || 'afm';
  const universe = state?.episodeState?.scope?.universe_id || state?.episodeState?.workspace?.universe_id
    || state?.timeline?.scope?.universe_id
    || 'afm';
  return {
    project,
    universe,
    episode: ep.id,
    branch: ep.branch || 'main',
  };
}

export function defaultSelectorForAsset(asset) {
  const kind = asset?.kind;
  const analysis = asset?.analysis || {};
  if (kind === 'image') {
    return { x: 0, y: 0, width: 10000, height: 10000 };
  }
  if (kind === 'document') {
    const chars = Math.max(1, Number(analysis.characters || 1));
    return { start: 0, end: Math.min(400, chars) };
  }
  const duration = Math.max(50, Number(analysis.duration_ms || 1000));
  return { start: 0, end: Math.min(duration, 3000) };
}

function buildTargetFields(state, target) {
  if (!target) return null;
  if (target.character && target.form) {
    const junction = state.formGraph?.junctions?.find((item) => item.character_id === target.character);
    return junction?.forms?.some((form) => form.id === target.form)
      ? { character: target.character, form: target.form } : null;
  }
  const ep = state?.episodeState?.episode;
  const story = state?.storyTimeline;
  if (!ep || story?.scope?.episode !== ep.id || story.timeline_revision !== ep.head) return null;
  if (target.beat && story?.scenes?.length) {
    for (const sc of story.scenes) {
      const row = (sc.beats || []).find((b) => b.id === target.beat);
      if (row?.passage?.sha256) {
        return {
          timeline_revision: story.timeline_revision ?? ep?.head ?? 0,
          beat: row.id,
          passage_sha256: row.passage.sha256,
          ...(story.fragment ? { fragment: story.fragment } : {}),
        };
      }
    }
  }
  if (target.scene && story?.scenes?.length) {
    const sc = story.scenes.find((s) => s.id === target.scene);
    if (sc?.passages_sha256) {
      return {
        timeline_revision: story.timeline_revision ?? ep?.head ?? 0,
        scene: sc.id,
        scene_sha256: sc.passages_sha256,
        ...(story.fragment ? { fragment: story.fragment } : {}),
      };
    }
  }
  return null;
}

export async function loadMediaVault(store, target = null) {
  const state = store.get();
  const scope = resolveEpisodeScope(state);
  const attempt = {};
  vaultLoads.set(store, attempt);
  if (!scope) {
    store.set({ mediaVault: { assets: [], segments: [], pins: [], overrides: [], loading: false, error: '' } });
    return null;
  }
  const targetFields = buildTargetFields(state, target);
  const isCurrent = () => vaultLoads.get(store) === attempt
    && JSON.stringify(resolveEpisodeScope(store.get())) === JSON.stringify(scope);
  try {
    const res = await NoirApi.episodeCommand({
      action: 'scene.media.open',
      ...scope,
      ...(targetFields || {}),
    });
    const vault = {
      assets: res.assets || [],
      segments: res.segments || [],
      pins: res.pins || [],
      overrides: res.overrides || [],
      pinRoleMap: res.pin_role_map || {},
      target: res.target || null,
      loading: false,
      error: '',
    };
    if (isCurrent()) {
      store.set({ mediaVault: vault });
      store.emit?.('media:changed', vault);
    }
    return vault;
  } catch (err) {
    const fallback = {
      ...(store.get().mediaVault || { assets: [], segments: [], pins: [], overrides: [] }),
      loading: false,
      error: err.message || 'Could not load Media Vault.',
    };
    if (isCurrent()) store.set({ mediaVault: fallback });
    return fallback;
  }
}

export async function attachMediaAssetPin(store, { asset, segmentId = '', pinRole = 'relationship_chemistry', target = null, observation = '' }) {
  const state = store.get();
  const scope = resolveEpisodeScope(state);
  const targetFields = buildTargetFields(state, target);
  if (!scope || !targetFields) {
    throw new Error('Select a saved Beat, Scene, or Character Form to pin media.');
  }
  const input = segmentId
    ? { segment: segmentId }
    : {
        asset: asset.id,
        selector: defaultSelectorForAsset(asset),
        pin_role: pinRole,
        observation: String(observation || '').slice(0, 380),
      };
  const res = await NoirApi.episodeCommand({
    action: 'scene.media.attach',
    ...scope,
    ...targetFields,
    ...input,
  });
  playPortSnap();
  window.NOIR_FX?.trigger('PORT_SNAP');
  store.emit?.('media:pinned', res);
  if (JSON.stringify(resolveEpisodeScope(store.get())) === JSON.stringify(scope)) {
    await loadMediaVault(store, store.get().mediaVaultTarget);
  }
  return res;
}

export async function uploadMediaFiles(store, files, { pinRole = 'relationship_chemistry', target = null, observation = '' } = {}) {
  const state = store.get();
  const scope = resolveEpisodeScope(state);
  if (!scope) throw new Error('Open a saved episode before uploading media.');
  const targetFields = buildTargetFields(state, target);
  if (target && !targetFields) throw new Error('Choose a saved Beat, Scene, or Character Form before attaching media.');
  const fileList = Array.from(files || []).filter(Boolean);

  const imported = [];
  const pins = [];
  const errors = [];
  for (const file of fileList) {
    try {
      const data = await NoirApi.uploadBeatMedia(scope, file);
      if (!data.asset) throw new Error('Upload returned no saved source.');
      imported.push(data.asset);
      if (targetFields) {
        try {
          pins.push(await NoirApi.episodeCommand({
            action: 'scene.media.attach',
            ...scope,
            ...targetFields,
            asset: data.asset.id,
            selector: defaultSelectorForAsset(data.asset),
            pin_role: pinRole,
            observation: String(observation || '').slice(0, 380),
          }));
        } catch (attachErr) {
          errors.push(`${file.name} pin: ${attachErr.message}`);
        }
      }
    } catch (err) {
      errors.push(`${file.name}: ${err.message}`);
    }
  }

  if (pins.length) store.emit?.('media:pinned', pins);
  if (JSON.stringify(resolveEpisodeScope(store.get())) === JSON.stringify(scope)) {
    await loadMediaVault(store, store.get().mediaVaultTarget);
  }
  if (pins.length) {
    playPortSnap();
    window.NOIR_FX?.trigger('PORT_SNAP');
  }
  return { imported, pins, errors };
}

export function openMediaVault(store, target = null, assetId = '') {
  store.set({ popModal: 'media', mediaVaultTarget: target, mediaVaultSelectedAssetId: assetId });
  void loadMediaVault(store, target);
}

function listAvailableTargets(state) {
  const targets = [];
  const junctions = state?.formGraph?.junctions || [];
  for (const j of junctions) {
    for (const f of j.forms || []) {
      targets.push({
        value: `form::${j.character_id}::${f.id}`,
        label: `Form · ${j.label || j.character_id} -> ${f.label || f.id}`,
        target: { character: j.character_id, form: f.id },
      });
    }
  }
  const scenes = state?.storyTimeline?.scenes || [];
  for (const sc of scenes) {
    targets.push({
      value: `scene::${sc.id}`,
      label: `Scene · ${sc.title || sc.id}`,
      target: { scene: sc.id },
    });
    for (const b of sc.beats || []) {
      targets.push({
        value: `beat::${b.id}`,
        label: `Beat · ${b.label || b.id}`,
        target: { beat: b.id },
      });
    }
  }
  return targets;
}

function targetToValue(target) {
  if (!target) return '';
  if (target.character && target.form) return `form::${target.character}::${target.form}`;
  if (target.beat) return `beat::${target.beat}`;
  if (target.scene) return `scene::${target.scene}`;
  return '';
}

function parseTargetValue(val) {
  if (!val) return null;
  const parts = val.split('::');
  if (parts[0] === 'form' && parts[1] && parts[2]) return { character: parts[1], form: parts[2] };
  if (parts[0] === 'beat' && parts[1]) return { beat: parts[1] };
  if (parts[0] === 'scene' && parts[1]) return { scene: parts[1] };
  return null;
}

export function renderMediaVaultModal(state) {
  const scope = resolveEpisodeScope(state);
  const vault = state.mediaVault || { assets: [], segments: [], pins: [], overrides: [] };
  const targets = listAvailableTargets(state);
  const curTargetVal = targetToValue(state.mediaVaultTarget);
  const selectedAsset = vault.assets.find((a) => a.id === state.mediaVaultSelectedAssetId) || vault.assets[0];
  const selectedAssetId = selectedAsset?.id;
  const activeRole = state.mediaVaultPinRole || 'relationship_chemistry';
  const originalUrl = selectedAsset && scope
    ? `/api/beat-media/original?${new URLSearchParams({ ...scope, id: selectedAsset.id }).toString()}`
    : '';

  if (!scope) {
    return '<div class="v2-inspector-card"><p class="v2-muted">Select or create an episode before managing multimodal sources.</p></div>';
  }

  return `
    <div class="v2-mv-shell">
      <div class="v2-mv-toolbar">
        <div class="v2-mv-dropzone" id="v2MvDropZone" tabindex="0">
          <strong>Drop source media or select files</strong>
          <small>Supports scripts (.txt/.md/.docx/.pdf), images (.png/.jpg/.webp), audio (.wav), and clips (.mp4/.webm)</small>
          <div class="v2-mv-upload-row">
            <input type="file" id="v2MvFileInput" multiple>
            <button type="button" class="v2-btn v2-btn-accent" id="v2MvPickBtn">+ Upload Source(s)</button>
            <button type="button" class="v2-btn" id="v2MvRefreshBtn">Refresh Vault</button>
          </div>
        </div>
        <div class="v2-mv-pin-controls">
          <label class="v2-mv-field">
            Target Node
            <select id="v2MvTargetSelect">
              <option value="">Project library</option>
              ${targets.map((t) => `<option value="${escapeHtml(t.value)}" ${t.value === curTargetVal ? 'selected' : ''}>${escapeHtml(t.label)}</option>`).join('')}
            </select>
          </label>
          <label class="v2-mv-field">
            Typed Pin Role
            <select id="v2MvRoleSelect">
              ${PIN_ROLES.map((r) => `<option value="${escapeHtml(r.id)}" ${r.id === activeRole ? 'selected' : ''}>${escapeHtml(r.label)} (${escapeHtml(r.purpose)})</option>`).join('')}
            </select>
          </label>
          <label class="v2-mv-field">
            Director Observation (entered into prose budget, never raw media)
            <input type="text" id="v2MvObsInput" placeholder="e.g. hold 1.5s perfume pause before Franny answers…" value="${escapeHtml(state.mediaVaultObs || '')}">
          </label>
          <button type="button" class="v2-btn v2-btn-accent" id="v2MvAttachBtn" ${!selectedAsset || !curTargetVal ? 'disabled' : ''}>Attach Typed Pin</button>
        </div>
      </div>

      ${vault.error ? `<div class="v2-notice" data-tone="err">${escapeHtml(vault.error)}</div>` : ''}

      <div class="v2-mv-grid">
        <section class="v2-mv-col">
          <h3>Saved Sources (${vault.assets.length})</h3>
          <div class="v2-mv-list">
            ${vault.assets.map((a) => `
              <button type="button" class="v2-mv-item ${a.id === selectedAssetId ? 'is-selected' : ''}" data-mv-asset="${escapeHtml(a.id)}">
                <div>
                  <strong>${escapeHtml(a.name)}</strong>
                  <small>${escapeHtml(a.kind.toUpperCase())} · ${Math.max(1, Math.round((a.bytes || 0) / 1024))} KB · sha ${escapeHtml(String(a.sha256 || '').slice(0, 8))}</small>
                </div>
                <span class="v2-pill">${escapeHtml(a.analysis?.method || a.kind)}</span>
              </button>
            `).join('') || '<p class="v2-muted">No uploaded sources in this workspace yet.</p>'}
          </div>
        </section>

        <section class="v2-mv-col">
          <h3>Source Preview &amp; Active Pins (${vault.pins.length})</h3>
          ${selectedAsset ? `
            <div class="v2-mv-preview">
              <div class="v2-mv-preview-head">
                <strong>${escapeHtml(selectedAsset.name)}</strong>
                <a class="v2-mini-btn" href="${escapeHtml(originalUrl)}&download=1" download>Download Original</a>
              </div>
              ${selectedAsset.kind === 'image' ? `<img class="v2-mv-img" src="${escapeHtml(originalUrl)}" alt="${escapeHtml(selectedAsset.name)}">` : ''}
              ${selectedAsset.kind === 'audio' ? `<audio class="v2-mv-audio" controls preload="metadata" src="${escapeHtml(originalUrl)}"></audio>` : ''}
              ${selectedAsset.kind === 'video' ? `<video class="v2-mv-video" controls preload="metadata" playsinline src="${escapeHtml(originalUrl)}"></video>` : ''}
              ${selectedAsset.kind === 'document' ? `<p class="v2-muted">${Number(selectedAsset.analysis?.characters || 0)} characters extracted locally (${escapeHtml(selectedAsset.analysis?.method || 'document')}).</p>` : ''}
            </div>
          ` : '<p class="v2-muted">Select an uploaded source to preview and bind its typed pin.</p>'}

          <div class="v2-mv-pins">
            ${vault.pins.map((p) => {
              const seg = (vault.segments || []).find((s) => s.id === p.segment);
              const asset = (vault.assets || []).find((a) => a.id === seg?.asset);
              const role = seg?.pin_role || seg?.purpose || 'reference';
              return `
                <div class="v2-mv-pin-card">
                  <div>
                    <strong>${escapeHtml(asset?.name || seg?.asset || 'Source')}</strong>
                    <small>Target: ${escapeHtml(p.target?.label || p.target?.form || p.target?.beat || p.target?.scene || 'Node')}</small>
                    ${seg?.observation ? `<small>Note: ${escapeHtml(seg.observation)}</small>` : ''}
                  </div>
                  <span class="v2-pill">${escapeHtml(role)}</span>
                </div>
              `;
            }).join('') || '<p class="v2-muted">No active pins recorded for this scope yet.</p>'}
          </div>
        </section>
      </div>
    </div>
  `;
}

export function bindMediaVaultEvents({ store }) {
  const dropZone = document.getElementById('v2MvDropZone');
  const fileInput = document.getElementById('v2MvFileInput');

  const handleUpload = async (files) => {
    const targetVal = document.getElementById('v2MvTargetSelect')?.value || '';
    const pinRole = document.getElementById('v2MvRoleSelect')?.value || 'relationship_chemistry';
    const observation = document.getElementById('v2MvObsInput')?.value || '';
    const target = parseTargetValue(targetVal);
    store.set({ mediaVaultTarget: target, mediaVaultPinRole: pinRole, mediaVaultObs: observation });
    let res;
    try {
      res = await uploadMediaFiles(store, files, { pinRole, target, observation });
    } catch (err) {
      store.set({ notice: { text: err.message, tone: 'err' } });
      return;
    }
    if (res.imported.length) {
      store.set({
        mediaVaultSelectedAssetId: res.imported[0].id,
        notice: { text: `Uploaded ${res.imported.length} source(s) to Media Vault.${res.errors.length ? ' ' + res.errors.join('; ') : ''}`, tone: res.errors.length ? 'warn' : 'ok' },
      });
    } else if (res.errors.length) {
      store.set({ notice: { text: res.errors.join('; '), tone: 'err' } });
    }
  };

  document.getElementById('v2MvPickBtn')?.addEventListener('click', () => fileInput?.click());
  fileInput?.addEventListener('change', (e) => {
    if (e.target.files?.length) void handleUpload(e.target.files);
  });

  dropZone?.addEventListener('dragover', (e) => {
    e.preventDefault();
    dropZone.classList.add('is-drag');
  });
  dropZone?.addEventListener('dragleave', () => dropZone.classList.remove('is-drag'));
  dropZone?.addEventListener('drop', (e) => {
    e.preventDefault();
    dropZone.classList.remove('is-drag');
    if (e.dataTransfer?.files?.length) void handleUpload(e.dataTransfer.files);
  });

  document.getElementById('v2MvRefreshBtn')?.addEventListener('click', () => {
    playTick();
    const target = parseTargetValue(document.getElementById('v2MvTargetSelect')?.value || '');
    void loadMediaVault(store, target);
  });

  document.getElementById('v2MvTargetSelect')?.addEventListener('change', (e) => {
    const target = parseTargetValue(e.target.value);
    store.set({ mediaVaultTarget: target });
    void loadMediaVault(store, target);
  });

  document.getElementById('v2MvRoleSelect')?.addEventListener('change', (e) => {
    store.setQuiet({ mediaVaultPinRole: e.target.value });
  });

  document.getElementById('v2MvObsInput')?.addEventListener('input', (e) => {
    store.setQuiet({ mediaVaultObs: e.target.value });
  });

  document.querySelectorAll('.v2-mv-list [data-mv-asset]').forEach((btn) => {
    btn.addEventListener('click', () => {
      playSelect();
      store.set({ mediaVaultSelectedAssetId: btn.dataset.mvAsset });
    });
  });

  document.getElementById('v2MvAttachBtn')?.addEventListener('click', async () => {
    const state = store.get();
    const vault = state.mediaVault;
    const asset = vault?.assets?.find((a) => a.id === state.mediaVaultSelectedAssetId) || vault?.assets?.[0];
    if (!asset) return;
    const targetVal = document.getElementById('v2MvTargetSelect')?.value || '';
    const pinRole = document.getElementById('v2MvRoleSelect')?.value || 'relationship_chemistry';
    const observation = document.getElementById('v2MvObsInput')?.value || '';
    const target = parseTargetValue(targetVal);
    try {
      await attachMediaAssetPin(store, { asset, pinRole, target, observation });
      store.set({
        mediaVaultTarget: target,
        notice: { text: `Pinned "${asset.name}" as ${pinRole}.`, tone: 'ok' },
      });
    } catch (err) {
      store.set({ notice: { text: err.message, tone: 'err' } });
    }
  });
}
