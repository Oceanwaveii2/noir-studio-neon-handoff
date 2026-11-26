import { NoirApi } from './api.js';
import {
  loadMediaVault,
  openMediaVault,
  renderMediaVaultModal,
  bindMediaVaultEvents,
} from './media_vault.js';
import { createStore, resolveInitialTheme, resolveInitialView } from './store.js';
import {
  isSoundEnabled,
  setSoundEnabled,
  isMusicEnabled,
  setMusicEnabled,
  getAudioFocusMode,
  setAudioFocusMode,
  cycleAudioFocusMode,
  getVolumeSettings,
  setVolumeSetting,
  setMusicZone,
  playTick,
  playSelect,
  playCookStart,
  playCookComplete,
} from './sound.js';
import { FX } from './fx_bus.js';
import {
  composeText,
  escapeHtml,
  renderComposeStage,
  renderProtectionInspector,
  bindComposeEvents,
  saveNotebookState,
  renderTrack,
  animateTrack,
  revealStoryPassage,
} from './compose.js';
import { extractSceneOutline } from './splitter.js';
import {
  displayEpisodeTitle,
  renderLeftRailShelf,
  renderWordPrepWorkspace,
  bindShelfAndWordMockup,
} from './shelf.js';
import {
  renderAnalysisLabStage,
  bindAnalysisLabEvents,
} from './analysis_lab.js';
import {
  renderTimelineStage,
  renderTimelineInspector,
  bindTimelineEvents,
  drawTimelineWires,
} from './timeline.js';
import { renderStoryTimeline, bindStoryTimeline } from './story_timeline.js';
import { renderStoryGraphCanvas, bindStoryGraphCanvas } from './story_graph_canvas.js';
import {
  renderGraphStage,
  renderGraphInspector,
  bindGraphEvents,
} from './graph.js';
import {
  renderBeatStage,
  renderBeatInspector,
  bindBeatEvents,
  bindActStructure,
  refreshActStructure,
  renderActStructure,
} from './beat.js';
import {
  renderProseStage,
  renderProseInspector,
  bindProseEvents,
  loadSelectionRun,
  renderLawsStage,
  renderLawsInspector,
  bindLawsEvents,
} from './prose.js';
import { renderIntake, bindIntake, renderDirectorInspector, bindDirectorInspector } from './intake.js';
import { currentScenePlan, renderScenePlan } from './scene_plan.js';
import { bindDesktopHost, openDesktopPassage } from './desktop-host.js';
import { noirVfx, getVfxIntensity, setVfxIntensity } from './vfx_engine.js';
import { createGlobalHistory, isEditableTarget } from './history.js';

if (typeof window !== 'undefined') window.__noirVfx = noirVfx;

const VIEWS = [
  { id: 'start', label: 'Home' },
  { id: 'prep', label: 'Word Prep', icon: '⚡' },
  { id: 'compose', label: 'Compose', icon: '✎' },
  { id: 'graph', label: 'Character Graph', icon: '◇' },
  { id: 'story', label: 'Story Graph & Rhythm', icon: '◈' },
  { id: 'timeline', label: 'Timeline', icon: '▦' },
];

const store = createStore({
  theme: resolveInitialTheme(),
  vfxIntensity: getVfxIntensity(),
  view: resolveInitialView(),
  railTab: resolveInitialView() === 'prep' ? 'shelf' : 'episodes',
  episodeId: new URLSearchParams(location.search).get('episode') || '',
  timeline: null,
  sampleProjects: null,
  episodeState: null,
  formGraph: null,
  graphSubtab: 'switchyard',
  graphFilter: '',
  graphDraft: null,
  graphSelectedNodeId: '',
  graphSelectedEdgeId: '',
  selectedProfile: null,
  beatMap: null,
  beatRhythm: null,
  beatSceneFilter: '',
  selectedBeatIds: [],
  beatGroupInstruction: '',
  beatGroupPreview: '',
  beatPaper: true,
  composeSplitGraph: new URLSearchParams(location.search).get('split') === '1',
  graphSplit: false,
  triSplit: false,
  triRatio: 'balanced',
  soloPane: null,
  popModal: null,
  mediaVault: { assets: [], segments: [], pins: [], overrides: [], loading: false, error: '' },
  mediaVaultTarget: null,
  mediaVaultSelectedAssetId: '',
  mediaVaultPinRole: 'relationship_chemistry',
  mediaVaultObs: '',
  directorOutline: null,
  writingRun: null,
  bookPolicy: null,
  bookStatus: null,
  proseProvider: 'codex-session',
  proseRefMode: 'none',
  proseSceneFn: 'scene',
  proseOutput: '',
  prosePreviewDraftId: '',
  compareA: '',
  compareB: '',
  draftCompareOutput: '',
  policyFilter: '',
  worldLaws: null,
  worldLawsDraft: null,
  canonState: null,
  canonDiffReport: null,
  scopedValidationReport: null,
  slotInfillPlan: null,
  slotInfillReport: null,
  craftBriefData: null,
  slopCritiqueReport: null,
  bestOfNRankReport: null,
  craftLensId: 'irby',
  timelineEvents: [],
  timelineDrafts: [],
  timelineDraftHistory: null,
  activeDraftId: null,
  timelineDraftPreviewId: '',
  timelineRemovedOpen: false,
  timelineSubtab: 'graph',
  storySubtab: new URLSearchParams(location.search).get('track') === 'story' ? 'passages'
    : new URLSearchParams(location.search).get('view') === 'beat' ? 'rhythm'
    : (new URLSearchParams(location.search).get('sub') || 'graph'),
  storyStructure: null, structureViewpoint: '', processingJobs: null,
  storyCursor: new URLSearchParams(location.search).get('story-beat') || '',
  storyTimeline: null,
  storyFragment: new URLSearchParams(location.search).get('story-fragment') || '',
  storyClip: '',
  storyError: '',
  beat: 0,
  viewpoint: '',
  dirty: false,
  draftBlocks: null,
  selectionRange: null,
  highlightMode: false,
  navigationOpen: false,
  speakerPicker: null,
  inspectorOpen: false,
  engineDrawerOpen: false,
  soundEnabled: isSoundEnabled(),
  musicEnabled: isMusicEnabled(),
  globalUndoCount: 0,
  globalRedoCount: 0,
  globalTrashCount: 0,
  switchyardSync: null,
  storySync: null,
  notice: { text: 'Noir Fiction Studio ready.', tone: 'ok' },
  busy: false,
});

const globalHistory = createGlobalHistory(store);
if (typeof window !== 'undefined') {
  window.__noirStore = store;
  window.__noirHistory = globalHistory;
}

function triggerStarRailShutter() {
  if (store.get().theme !== 'racing') return;
  if (window.matchMedia?.('(prefers-reduced-motion: reduce)').matches) return;
  document.getElementById('v2ShutterOverlay')?.remove();
  const el = document.createElement('div');
  el.id = 'v2ShutterOverlay';
  el.className = 'v2-shutter-overlay';
  el.setAttribute('aria-hidden', 'true');
  document.body.appendChild(el);
  window.setTimeout(() => el.remove(), 460);
}

function changeView(view) {
  if (view === 'beat') {
    store.setQuiet({ storySubtab: 'rhythm' });
    view = 'story';
  }
  const prev = store.get().view;
  const url = new URL(location.href);
  url.searchParams.set('view', view);
  url.searchParams.delete('track');
  if (view === 'story') url.searchParams.set('sub', store.get().storySubtab || 'graph');
  else url.searchParams.delete('sub');
  history.replaceState(null, '', url);
  if (prev && prev !== view) {
    triggerStarRailShutter();
    noirVfx.playSpeedRibbonWipe();
    FX.trigger('TAB_SWITCH', { zone: view === 'start' ? 'lobby' : 'nontrack' });
  }
  store.set({
    view,
    inspectorOpen: false,
    navigationOpen: false,
    ...(view === 'prep' ? { railTab: 'shelf' } : {}),
  });
  if (view === 'story' && store.get().storySubtab === 'passages') void loadStoryTimeline();
  if (view === 'story' && store.get().storySubtab === 'processing') void loadProcessing();
  if (view === 'laws') void loadCanonState();
}

async function loadCanonState() {
  const s = store.get();
  const ep = s.episodeState?.episode;
  const scope = s.episodeState?.scope || {};
  if (!ep) return;
  try {
    const canonState = await NoirApi.canonProposals({
      action: 'open',
      episode: ep.id,
      branch: ep.branch,
      beat: s.beat || 0,
      project: scope.project_id,
      universe: scope.universe_id,
    });
    if (store.get().episodeId === ep.id) store.set({ canonState });
  } catch (_) {}
}

function setPanels(navigationOpen, inspectorOpen) {
  store.setQuiet({ navigationOpen, inspectorOpen });
  for (const [rail, toggle, open] of [
    ['v2LeftRail', 'v2NavigationToggle', navigationOpen],
    ['v2RightRail', 'v2InspectorToggle', inspectorOpen],
  ]) {
    document.getElementById(rail)?.classList.toggle('is-open', open);
    document.getElementById(toggle)?.setAttribute('aria-expanded', String(open));
  }
}

let storyLoad = 0;

async function loadStoryTimeline(fragment = store.get().storyFragment) {
  const state = store.get();
  const { episode, scope } = state.episodeState || {};
  if (!episode?.head || !scope || state.episodeId !== episode.id) return;
  const attempt = ++storyLoad;
  const current = () => attempt === storyLoad && store.get().episodeId === episode.id
    && store.get().episodeState?.episode?.head === episode.head;
  store.setQuiet({ storyError: '', storyFragment: fragment,
    ...(fragment !== state.storyFragment ? { storyTimeline: null } : {}) });
  try {
    const storyTimeline = await NoirApi.episodeCommand({
      action: 'scene.timeline.open', project: scope.project_id, universe: scope.universe_id,
      episode: episode.id, branch: episode.branch, timeline_revision: episode.head,
      ...(fragment ? { fragment } : {}),
    });
    if (current()) store.set({ storyTimeline });
  } catch (error) {
    if (current()) store.set({ storyError: error.message });
  }
}

function selectStorySubtab(storySubtab) {
  store.setQuiet({ storySubtab, popModal: null });
  changeView('story');
}

async function loadProcessing() {
  const state = store.get();
  const ep = state.episodeState?.episode;
  const scope = state.episodeState?.scope;
  if (!ep || !scope) return;
  try {
    const { jobs } = await NoirApi.episodeCommand({ action: 'processing.open', episode: ep.id,
      branch: ep.branch, project: scope.project_id, universe: scope.universe_id });
    if (store.get().episodeId === ep.id) store.set({ processingJobs: jobs });
  } catch (error) {
    if (store.get().episodeId === ep.id) store.set({ notice: { text: error.message, tone: 'err' } });
  }
}

function pickStoryBeat(id) {
  if (!id) return;
  const url = new URL(location.href);
  url.searchParams.set('story-beat', id);
  history.replaceState(null, '', url);
  store.set({ storyCursor: id, storyClip: '' });
  document.querySelector(`[data-story-beat="${CSS.escape(id)}"]`)?.focus({ preventScroll: true });
}

async function openStoryPassage(beat) {
  const state = store.get();
  const story = state.storyTimeline;
  if (!story) return;
  if (state.dirty) {
    store.set({ storyError: 'Save the open notebook before going to a saved passage.' });
    return;
  }
  try {
    const fresh = await NoirApi.getEpisodeState(story.scope.episode);
    if (store.get().storyTimeline !== story || store.get().dirty || store.get().view !== 'story') return;
    const blocks = state.episodeState.notebook?.blocks;
    if (!blocks || fresh.episode.head !== story.timeline_revision || fresh.episode.branch !== story.scope.branch
        || composeText(blocks) !== fresh.script_text
        || [...fresh.script_text].slice(beat.passage.start, beat.passage.end).join('') !== beat.passage.text) {
      throw new Error('The manuscript changed. Reload the saved timeline before opening this passage.');
    }
    store.setQuiet({ activeDraftId: null, highlightMode: false, storyError: '' });
    changeView('compose');
    if (!revealStoryPassage(blocks, beat.passage)) {
      store.set({ notice: { text: 'This passage has no visible notebook block.', tone: 'warn' } });
    }
  } catch (error) {
    store.set({ storyError: error.message });
  }
}

function updateCookMount() {
  const mount = document.getElementById('v2CookMount');
  if (!mount) return;
  mount.innerHTML = renderCookOverlay(store.get());
  document.getElementById('v2CookCloseBtn')?.addEventListener('click', () => {
    playTick();
    store.setQuiet({ cookModalOpen: false });
    updateCookMount();
  });
  bindCookRender();
}

function bindCookRender() {
  document.getElementById('v2CookRenderForm')?.addEventListener('submit', (event) => {
    event.preventDefault();
    const values = new FormData(event.target);
    void renderCookPassage(values.get('passage'), values.get('provider'));
  });
  document.getElementById('v2OpenCookDraft')?.addEventListener('click', () => {
    const id = store.get().cookJob?.run?.draft_id;
    if (id) {
      store.setQuiet({ cookModalOpen: false });
      void openSavedDraft(id);
    }
  });
}

async function renderCookPassage(id, provider) {
  const state = store.get();
  const { episode, notebook, scope } = state.episodeState || {};
  const job = state.cookJob;
  const beat = state.beatMap?.beats?.find((item) => item.id === id);
  if (state.busy || !episode || !notebook || !scope || !job?.result?.receipt || !beat || !provider) return;
  const request_id = crypto.randomUUID();
  const stages = job.stages.slice(0, 3).map((step, index) => ({
    ...step, cache: index < 2 ? 'CACHE_HIT' : 'RECOMPUTED',
  }));
  stages.push(
    { label: 'Realize passage', status: 'running', detail: 'Connecting the selected writer', cache: 'RECOMPUTED' },
    { label: 'Polish and check exact bytes', status: 'pending', detail: 'Waiting for the writer' },
  );
  const update = (patch) => {
    store.setQuiet({ cookJob: { ...job, ...patch, stages } });
    updateCookMount();
  };
  store.setQuiet({ busy: true });
  update({ status: 'running', progress: 67, message: 'Preparing the scoped writer request.' });
  try {
    let run = await NoirApi.episodeCommand({
      action: 'run.selection', request_id, episode: episode.id, branch: episode.branch,
      project: scope.project_id, universe: scope.universe_id, revision: episode.head,
      notebook_revision: notebook.revision, beat: beat.scope_beat, start: beat.start, end: beat.end,
      provider, references: state.proseRefMode || 'none', reference_delivery: 'cadence',
      viewpoint: state.viewpoint || null, max_attempts: 1, compositor_preparation: job.result.receipt.id,
    });
    while (['QUEUED', 'RUNNING'].includes(run.status)) {
      if (store.get().episodeId !== episode.id) return;
      const polishing = ['validate-1', 'save'].includes(run.stage);
      if (polishing) {
        stages[3] = { ...stages[3], status: 'done', detail: 'Writer response received' };
        stages[4] = { ...stages[4], status: 'running', detail: 'Checking the passage against its saved constraints' };
      }
      update({ status: 'running', run, progress: polishing ? 90 : 75, message: polishing ? 'Polishing the draft.' : 'Writing the passage.' });
      await new Promise((resolve) => setTimeout(resolve, 500));
      run = await NoirApi.episodeCommand({ action: 'run.status', episode: episode.id, request_id });
    }
    if (store.get().episodeId !== episode.id) return;
    const ready = Boolean(run.status === 'COMPLETED' && run.generation_receipt);
    const preserved = run.status === 'PRESERVED';
    stages[3] = { ...stages[3], status: ready ? 'done' : preserved ? 'skipped' : 'failed',
      cache: ready ? 'RECOMPUTED' : '', detail: ready ? 'Writer receipt saved' : run.reason || run.status };
    stages[4] = { ...stages[4], status: ready && run.polish ? 'done' : 'skipped',
      cache: ready && run.polish ? 'RECOMPUTED' : '',
      detail: run.polish ? `Composite Slop Score ${run.polish.slop_before} → ${run.polish.slop_after} (Δ ${run.polish.slop_delta})` : 'No passage to polish' };
    update({ status: ready || preserved ? 'completed' : 'failed', progress: ready || preserved ? 100 : 75, run,
      message: ready ? 'Draft saved through the five-pass Cook.' : run.reason || run.status,
      error: ready || preserved ? null : run.reason || run.status });
  } catch (error) {
    if (store.get().episodeId === episode.id) {
      stages[3] = { ...stages[3], status: 'failed', detail: error.message };
      update({ status: 'failed', progress: 75, error: error.message });
    }
  } finally {
    if (store.get().episodeId === episode.id) store.set({ busy: false });
  }
}

function updateNoticeDom(notice) {
  const el = document.querySelector('.v2-rail-right .v2-notice[role="status"]');
  if (el && notice) {
    el.dataset.tone = notice.tone || 'ok';
    el.textContent = notice.text || '';
  }
}

function episodeStageLabel(ep, blocks = []) {
  if (!ep) return { text: 'Draft', cls: 'v2-pill-draft' };
  const list = Array.isArray(blocks) ? blocks : [];
  const hasStructured = list.length > 2 && list.some((b) => b.kind && b.kind !== 'unresolved');
  if (/unprocessed/i.test(ep.title || '')) {
    if (hasStructured) return { text: 'Draft', cls: 'v2-pill-draft' };
    return { text: 'Unprocessed', cls: 'v2-pill-unprocessed' };
  }
  if (ep.status === 'finished') return { text: 'Finished', cls: 'v2-pill-finished' };
  return { text: 'Draft', cls: 'v2-pill-draft' };
}

function countStats(blocks) {
  const list = Array.isArray(blocks) ? blocks : [];
  const fullText = composeText(list);
  const trimmed = fullText.trim();
  const words = trimmed ? trimmed.split(/\s+/).length : 0;
  return { blocks: list.length, words, chars: fullText.length, fullText };
}

function applyTheme(theme) {
  document.body.dataset.theme = theme;
  try {
    localStorage.setItem('noir-theme', theme);
  } catch (_) {}
}

async function loadTimelineExtras(episodeId, branch) {
  if (!episodeId) return { timelineEvents: [], timelineDrafts: [], timelineDraftHistory: null };
  const [evRes, drRes] = await Promise.all([
    NoirApi.timelineAction({ action: 'events', id: episodeId }).catch(() => ({ events: [] })),
    branch
      ? NoirApi.draftsAction({ action: 'list', episode: episodeId, branch }).catch(() => ({ drafts: [], favorite_history: null }))
      : Promise.resolve({ drafts: [], favorite_history: null }),
  ]);
  const drafts = drRes.drafts || [];
  const grouped = new Set(drafts.filter(d => d.writing_run?.kind === 'group').map(d => d.writing_run.id));
  return {
    timelineEvents: evRes.events || [],
    timelineDrafts: drafts.filter(d => !(d.writing_run?.kind === 'passage' && grouped.has(d.writing_run.id))),
    timelineDraftHistory: drRes.favorite_history || null,
  };
}

async function refreshTimeline() {
  const timeline = await NoirApi.getTimeline();
  const curId = store.get().episodeId;
  const activeCard = (timeline.cards || []).find((c) => c.id === curId) || timeline.cards?.[0] || null;
  if (!activeCard) {
    store.set({ timeline, episodeId: '', episodeState: null, timelineEvents: [], timelineDrafts: [], timelineDraftHistory: null });
    return;
  }
  const [episodeState, notebook, extras] = await Promise.all([
    NoirApi.getEpisodeState(activeCard.id),
    NoirApi.notebookAction({ action: 'open', episode: activeCard.id }).catch(() => null),
    loadTimelineExtras(activeCard.id, activeCard.branch),
  ]);
  const mergedState = notebook ? { ...episodeState, notebook } : episodeState;
  store.set({
    timeline,
    episodeId: activeCard.id,
    episodeState: mergedState,
    ...extras,
  });
}

async function loadBeatData(episodeId, revision, beat, viewpoint) {
  if (!episodeId || typeof revision !== 'number') {
    return { beatMap: null, beatRhythm: null, directorOutline: null, writingRun: null };
  }
  const [beatMap, beatRhythm, latest] = await Promise.all([
    NoirApi.getBeatMap(episodeId, revision, viewpoint).catch(() => null),
    NoirApi.beatRhythmAction({ action: 'open', episode: episodeId, beat }).catch(() => null),
    NoirApi.episodeCommand({ action: 'run.latest', episode: episodeId, kind:'beats' }).catch(() => null),
  ]);
  const directorOutline = beatMap ? await NoirApi.episodeCommand({
    action: 'director.open', episode: episodeId, revision, viewpoint: viewpoint || null,
    project: beatMap.project_id, universe: beatMap.universe_id, branch: beatMap.branch,
    source_sha256: beatMap.source_sha256, anchor_token: beatMap.anchor_token,
  }).catch(() => null) : null;
  return { beatMap, beatRhythm, directorOutline, writingRun: latest?.run || null };
}

async function selectEpisode(episodeId, { keepBusy = false } = {}) {
  if (!episodeId) return false;
  const old = store.get();
  if (old.dirty && old.episodeId !== episodeId) {
    store.set({ notice: { text: 'Save your open notebook before switching episodes.', tone: 'warn' } });
    return false;
  }
  ++storyLoad;
  store.set({
    busy: true,
    episodeId,
    dirty: false,
    draftBlocks: null,
    selectionRange: null,
    highlightMode: false,
    navigationOpen: false,
    activeDraftId: null,
    speakerPicker: null,
    timelineDraftPreviewId: '',
    graphDraft: null,
    graphSelectedNodeId: '',
    graphSelectedEdgeId: '',
    selectedProfile: null,
    beatSceneFilter: '',
    selectedBeatIds: [],
    beatGroupPreview: '',
    directorOutline: null,
    writingRun: null,
    preparation: null,
    selectionRun: null,
    selectionError: '',
    selectionPreview: null,
    proseOutput: '',
    canonState: null,
    canonDiffReport: null,
    scopedValidationReport: null,
    slotInfillPlan: null,
    slotInfillReport: null,
    craftBriefData: null,
    slopCritiqueReport: null,
    bestOfNRankReport: null,
    storyTimeline: null,
    storyStructure: null,
    processingJobs: null,
    storyError: '',
    ...(old.episodeId !== episodeId ? { storyFragment: '', storyClip: '', storyCursor: '', bridgeBeatId: '',
      mediaVault: null, mediaVaultTarget: null, mediaVaultSelectedAssetId: '' } : {}),
  });
  try {
    const curState = store.get();
    const [episodeState, notebook, formGraph] = await Promise.all([
      NoirApi.getEpisodeState(episodeId),
      NoirApi.notebookAction({ action: 'open', episode: episodeId }).catch(() => null),
      NoirApi.getFormGraph(episodeId).catch(() => null),
    ]);
    const mergedState = notebook ? { ...episodeState, notebook } : episodeState;
    const url = new URL(location.href);
    url.searchParams.set('episode', episodeId);
    history.replaceState(null, '', url);
    // Render the saved document before loading the secondary metadata.
    store.set({
      busy: keepBusy,
      episodeState: mergedState,
      formGraph,
      beatGroupInstruction: old.episodeId === episodeId && old.episodeState?.episode?.id === episodeId
        ? old.beatGroupInstruction : (mergedState.intake?.prompt || ''),
      beatWriter: mergedState.intake?.provider || old.beatWriter || 'codex-session',
      notice: {
        text: mergedState.episode?.title
          ? `Loaded ${mergedState.episode.title} (r${mergedState.episode.head}, nb r${mergedState.notebook?.revision ?? 0}).`
          : 'Episode loaded.',
        tone: 'ok',
      },
    });
    const [extras, beatData, selectionRun, prepared, directorHist] = await Promise.all([
      loadTimelineExtras(episodeId, mergedState.episode?.branch),
      loadBeatData(episodeId, mergedState.episode?.head, curState.beat, curState.viewpoint),
      loadSelectionRun(NoirApi, mergedState).catch(() => null),
      NoirApi.episodeCommand({action:'episode.preparation.open', episode:episodeId}).catch(() => null),
      NoirApi.intake({ action: 'intake.history', episode: episodeId, project: mergedState.workspace?.project_id || curState.timeline?.scope?.project_id, universe: mergedState.workspace?.universe_id || curState.timeline?.scope?.universe_id }).catch(() => null),
    ]);
    if (store.get().episodeId !== episodeId) return true;
    store.set({
      ...extras,
      ...beatData,
      selectionRun,
      preparation: prepared?.receipt || null,
      directorHistory: Array.isArray(directorHist?.entries) ? directorHist.entries : [],
    });
    void loadStoryTimeline();
    void refreshActStructure(store, NoirApi);
    if (store.get().storySubtab === 'processing') void loadProcessing();
    void loadMediaVault(store);
    if (store.get().view === 'laws') void loadCanonState();
    return true;
  } catch (err) {
    store.set({ busy: false, notice: { text: err.message, tone: 'err' } });
    return false;
  }
}

async function saveDocumentChanges() {
  const cur = store.get();
  const ep = cur.episodeState?.episode;
  const nb = cur.episodeState?.notebook;
  if (!ep || !nb || !cur.dirty || !cur.draftBlocks) return;
  const text = composeText(cur.draftBlocks);
  store.set({ busy: true });
  try {
    const updatedNb = await NoirApi.notebookAction({
      action: 'save-document',
      episode: ep.id,
      revision: nb.revision,
      timeline_revision: nb.timeline_revision,
      text,
      graph: null,
    });
    store.set({
      busy: false,
      dirty: false,
      draftBlocks: null,
      canonDiffReport: null,
      scopedValidationReport: null,
      episodeState: { ...cur.episodeState, episode: { ...ep, head: updatedNb.timeline_revision },
        script_text: text, notebook: updatedNb },
      notice: { text: `Saved script edits (nb r${updatedNb.revision}).`, tone: 'ok' },
    });
  } catch (err) {
    store.set({ busy: false, notice: { text: err.message, tone: 'err' } });
  }
}

async function setProtectionWeight(weight) {
  const cur = store.get();
  const nb = cur.episodeState?.notebook;
  if (!nb) return;
  const blocks = cur.draftBlocks || nb.blocks;
  await saveNotebookState(store, NoirApi, blocks, weight, nb.masks || [], `Default protection set to ${weight}%.`);
  if (weight !== nb.default_protection && store.get().episodeState?.notebook?.default_protection === weight) {
    animateTrack(document.getElementById('v2DocDial')?.querySelector('[data-track]'), weight);
  }
}

function projectHistoryControl(state, direction) {
  const item = state.projectHistory?.[`next_${direction}`];
  const undo = direction === 'undo';
  const label = undo ? 'Undo' : 'Redo';
  const shortcut = undo ? 'Ctrl+Z' : 'Ctrl+Shift+Z';
  const local = undo ? globalHistory.peekUndoLabel() : globalHistory.peekRedoLabel();
  const notebook = !state.projectHistory?.revision && ['compose', 'beat'].includes(state.view) &&
    state.episodeState?.notebook?.[`can_${direction}`];
  const description = item ? item.operation.replaceAll('_', ' ') : local;
  return {
    enabled: !state.busy && Boolean(item || notebook || local),
    title: description ? `${label} ${description} (${shortcut})` : `${label} (${shortcut})`,
  };
}

function showProjectHistory(history) {
  const state = store.get();
  if (history.revision < (state.projectHistory?.revision ?? 0)) return;
  store.setQuiet({ projectHistory: history });
  for (const direction of ['undo', 'redo']) {
    const button = document.getElementById(direction === 'undo' ? 'v2UndoBtn' : 'v2RedoBtn');
    if (!button) continue;
    const { enabled, title } = projectHistoryControl(store.get(), direction);
    button.disabled = !enabled;
    button.title = title;
  }
}

async function refreshProjectHistory() {
  try {
    showProjectHistory(await NoirApi.episodeCommand({ action: 'history.open' }));
  } catch {
    // A workspace without project history still has its original editor controls.
  }
}

async function stepProjectHistory(direction) {
  const { projectHistory, dirty, graphDraft, busy } = store.get();
  const item = projectHistory?.[`next_${direction}`];
  if (busy || !item) return;
  if (dirty || graphDraft) {
    store.set({ notice: { text: 'Save your open edits before using project history.', tone: 'warn' } });
    return;
  }
  store.set({ busy: true });
  try {
    const result = await NoirApi.episodeCommand({
      action: `history.${direction}`, revision: projectHistory.revision, tx_id: item.tx_id,
    });
    showProjectHistory(result);
    const timeline = await NoirApi.getTimeline();
    const cards = timeline.cards || timeline.episodes || [];
    const active = cards.find((card) => card.id === store.get().episodeId) || cards[0];
    store.setQuiet({ timeline });
    if (active) await selectEpisode(active.id, { keepBusy: true });
    else store.setQuiet({ episodeId: '', episodeState: null, timelineEvents: [], timelineDrafts: [] });
    FX.trigger('TELEMETRY_DELTA');
    store.set({ busy: false, notice: { text: `Project ${direction} applied.`, tone: 'ok' } });
  } catch (err) {
    store.set({ busy: false, notice: { text: err.message, tone: 'err' } });
    await refreshProjectHistory();
  }
}

async function stepHistory(direction) {
  const { episodeState } = store.get();
  if (!episodeState?.episode || !episodeState?.notebook) return;
  if (store.get().dirty) {
    store.set({ notice: { text: 'Save your edits before using document history.', tone: 'warn' } });
    return;
  }
  store.set({ busy: true });
  try {
    const nb = await NoirApi.notebookAction({
      action: direction,
      episode: episodeState.episode.id,
      revision: episodeState.notebook.revision,
      timeline_revision: episodeState.notebook.timeline_revision,
    });
    store.set({
      busy: false,
      dirty: false,
      draftBlocks: null,
      selectionRange: null,
      episodeState: { ...episodeState, episode: { ...episodeState.episode, head: nb.timeline_revision },
        script_text: composeText(nb.blocks), notebook: nb },
      notice: { text: `Notebook ${direction} applied (nb r${nb.revision}).`, tone: 'ok' },
    });
  } catch (err) {
    store.set({ busy: false, notice: { text: err.message, tone: 'err' } });
  }
}

async function runCookPipeline() {
  const cur = store.get();
  if (!cur.episodeId || cur.busy) return;
  if (cur.dirty || cur.graphDraft) {
    store.set({ notice: { text: 'Save your edits before preparing the episode.', tone: 'warn' } });
    return;
  }
  store.setQuiet({ busy: true });
  const cookBtn = document.getElementById('v2CookBtn');
  if (cookBtn) {
    cookBtn.disabled = true;
  }
  FX.trigger('COOK_START', { el: cookBtn || document.body, label: 'OVERDRIVE COOK' });
  try {
    let job = await NoirApi.cookEpisode(cur.episodeId, cur.viewpoint || '',
      cur.episodeState?.episode?.head, cur.episodeState?.notebook?.revision);
    if (store.get().episodeId !== cur.episodeId) return;
    store.setQuiet({ cookJob: job, cookModalOpen: true });
    updateCookMount();

    let finalLapFired = false;
    while (job.status === 'running') {
      await new Promise((resolve) => setTimeout(resolve, 120));
      job = await NoirApi.getCookStatus(job.job_id);
      if (store.get().episodeId !== cur.episodeId) return;
      if (!finalLapFired && ((job.progress ?? 0) >= 75 || /polish|final|guard/i.test(job.step || job.message || ''))) {
        finalLapFired = true;
        FX.trigger('FINAL_LAP');
      }
      store.setQuiet({ cookJob: job });
      updateCookMount();
    }

    if (job.status === 'completed') {
      const beatRev = job.result.timeline_revision;
      const [episodeState, formGraph, notebookResult, beatData] = await Promise.all([
        NoirApi.getEpisodeState(cur.episodeId),
        NoirApi.getFormGraph(cur.episodeId),
        NoirApi.notebookAction({action:'current', episode:cur.episodeId}),
        loadBeatData(cur.episodeId, beatRev, cur.beat, cur.viewpoint || ''),
      ]);
      if (store.get().episodeId !== cur.episodeId) return;
      const notebook = notebookResult.notebook;
      if (episodeState.episode.head !== beatRev || notebook?.revision !== job.result.revision) {
        throw new Error('The saved episode changed during preparation. Reopen it to see the current structure.');
      }
      FX.trigger('FINISH_TRIUMPH', {
        title: 'COOK COMPLETE',
        subtitle: job.message || 'Canon & style guards verified',
      });
      const notice = { text: job.message, tone: 'ok' };
      store.set({
        busy: false,
        dirty: false,
        draftBlocks: null,
        episodeState: { ...episodeState, notebook },
        formGraph,
        ...beatData,
        preparation: job.result.receipt,
        cookJob: { ...job, stages: job.stages.map((stage) => ({ ...stage, cache: 'RECOMPUTED' })) },
        cookModalOpen: true,
        notice,
      });
      void refreshProjectHistory();
    } else {
      const notice = { text: job.error || 'Cook failed.', tone: 'err' };
      store.setQuiet({ busy: false, cookJob: job, notice });
      if (cookBtn) cookBtn.disabled = false;
      updateCookMount();
      updateNoticeDom(notice);
    }
  } catch (err) {
    if (store.get().episodeId !== cur.episodeId) return;
    const notice = { text: err.message, tone: 'err' };
    store.setQuiet({ busy: false, cookModalOpen: false, notice });
    if (cookBtn) cookBtn.disabled = false;
    updateCookMount();
    updateNoticeDom(notice);
  }
}

function render(state) {
  applyTheme(state.theme);
  const episodes = state.timeline?.cards || state.timeline?.episodes || [];
  const ep = state.episodeState?.episode || episodes.find((e) => e.id === state.episodeId) || null;
  const nb = state.episodeState?.notebook || null;
  const blocks = state.draftBlocks || nb?.blocks || state.episodeState?.blocks || [];
  const outline = extractSceneOutline(blocks);
  const stats = countStats(blocks);
  const protection = nb?.default_protection ?? 100;
  const storyTrack = state.view === 'story' && state.storySubtab === 'passages';

  const root = document.getElementById('v2App');
  const focusedPicker = root.querySelector('#v2WorkspacePicker:focus, #v2ThemeSelect:focus')?.id;
  const renderKey = `${state.view}:${state.episodeId}:${state.activeDraftId || ''}:${storyTrack}`;
  const scrollSelectors = ['.v2-stage','.v2-rail-left','.v2-rail-right','.v2-tl-canvas','.v2-beat-paper','.v2-beat-pane','.v2-story-lane'];
  const previousScroll = root.dataset.renderKey === renderKey ? scrollSelectors.map(sel => {
    const el = root.querySelector(sel); return [sel, el?.scrollTop || 0, el?.scrollLeft || 0];
  }) : [];
  root.dataset.renderKey = renderKey;
  root.innerHTML = `
    <header class="v2-topbar">
      <div class="v2-brand">
        ${state.theme === 'racing'
          ? '<img class="v2-brand-logo-img" src="/assets/v2/game-noir-logo.webp" alt="NOIR">'
          : '<span class="v2-stripes" aria-hidden="true"></span><span class="v2-logo">NOIR</span>'}
      </div>
      <nav class="v2-nav" aria-label="Workspace">
        ${VIEWS.map(
          (v) => `
          <button
            type="button"
            class="v2-tab"
            data-view="${v.id}"
            ${['beat','prose','laws'].includes(v.id) ? 'data-secondary' : ''}
            ${state.view === v.id ? 'aria-current="page"' : ''}
          >${v.icon ? `<span aria-hidden="true">${v.icon}</span>` : ''}${escapeHtml(v.label)}</button>`
        ).join('')}
      </nav>
      <select class="v2-workspace-picker" id="v2WorkspacePicker" aria-label="Workspace">
        ${VIEWS.map((v) => `<option value="${v.id}" ${state.view === v.id ? 'selected' : ''}>${escapeHtml(v.label)}</option>`).join('')}
      </select>
      <div class="v2-top-controls">
        <div class="v2-view-actions">
          <button type="button" class="v2-btn v2-nav-toggle" id="v2NavigationToggle" aria-controls="v2LeftRail" aria-expanded="${state.navigationOpen}">Episodes</button>
          ${state.view !== 'start' && !storyTrack ? `<button type="button" class="v2-btn v2-inspector-toggle" id="v2InspectorToggle" aria-controls="v2RightRail" aria-expanded="${state.inspectorOpen}">Inspector</button>` : ''}
          <button type="button" class="v2-btn" id="v2UndoBtn" ${projectHistoryControl(state, 'undo').enabled ? '' : 'disabled'} title="${escapeHtml(projectHistoryControl(state, 'undo').title)}">Undo</button>
          <button type="button" class="v2-btn" id="v2RedoBtn" ${projectHistoryControl(state, 'redo').enabled ? '' : 'disabled'} title="${escapeHtml(projectHistoryControl(state, 'redo').title)}">Redo</button>
          <button type="button" class="v2-btn" id="v2TrashBtn" title="Soft-deleted recovery vault (Zero Hard Deletes)">Trash (${globalHistory.getTrash().length})</button>
          <button type="button" class="v2-btn v2-btn-cook" id="v2CookBtn" ${!ep || state.busy ? 'disabled' : ''}>Cook</button>
          <button type="button" class="v2-btn v2-btn-accent" id="v2SaveBtn" ${state.dirty && !state.busy ? '' : 'disabled'}>
            ${state.dirty ? 'Save changes' : (ep ? `Saved r${ep.head}` : 'No episode')}
          </button>
          <button type="button" class="v2-btn v2-btn-sound" id="v2SoundBtn" aria-label="UI sound effects" aria-pressed="${state.soundEnabled ? 'true' : 'false'}" title="UI SFX">${state.soundEnabled ? 'SFX: On' : 'SFX: Off'}</button>
          <button type="button" class="v2-btn v2-btn-music" id="v2MusicBtn" aria-label="Background music" aria-pressed="${state.musicEnabled ? 'true' : 'false'}" title="Background Music">${state.musicEnabled ? 'Music: On' : 'Music: Off'}</button>
          <button type="button" class="v2-btn v2-btn-audio-focus" id="v2AudioFocusBtn" aria-label="Audio Focus Mode" title="Cycle Audio Focus: Overdrive / Balanced / Focus / Muted">Audio: ${getAudioFocusMode().replace(/^\w/, c => c.toUpperCase())}</button>
          <button type="button" class="v2-btn v2-btn-vfx" id="v2VfxModeBtn" aria-label="VFX Intensity" title="Cycle VFX Intensity: Full / Crisp / Minimal">VFX: ${state.vfxIntensity === 'focus' ? 'Minimal' : state.vfxIntensity === 'balanced' ? 'Crisp' : 'Full'}</button>
          <button type="button" class="v2-btn" id="v2EngineDrawerBtn" aria-controls="v2EngineDrawer" aria-expanded="${state.engineDrawerOpen ? 'true' : 'false'}" title="Engine Settings &amp; PDG Diagnostics">⚙ Engine</button>
        </div>
      </div>
    </header>

    <aside class="v2-engine-drawer" id="v2EngineDrawer" aria-label="Engine Settings and Diagnostics" ${state.engineDrawerOpen ? '' : 'hidden'}>
      <div class="v2-engine-drawer-head">
        <strong>⚙ Engine / PDG Settings</strong>
        <button type="button" class="v2-btn" id="v2EngineDrawerCloseBtn">✕</button>
      </div>
      <div class="v2-engine-section">
        <h3>Appearance &amp; Theme</h3>
        <label class="v2-theme-picker">
          <span>Appearance</span>
          <select id="v2ThemeSelect" aria-label="Appearance">
            <option value="noir-v4" ${state.theme === 'noir-v4' ? 'selected' : ''}>Noir v4</option>
            <option value="racing" ${state.theme === 'racing' ? 'selected' : ''}>Racing</option>
            <option value="classic" ${state.theme === 'classic' ? 'selected' : ''}>Classic</option>
          </select>
        </label>
        <label class="v2-theme-picker" style="margin-top:8px">
          <span>VFX Intensity</span>
          <select id="v2VfxSelect" aria-label="VFX Intensity">
            <option value="overdrive" ${state.vfxIntensity === 'overdrive' ? 'selected' : ''}>Full (Overdrive)</option>
            <option value="balanced" ${state.vfxIntensity === 'balanced' ? 'selected' : ''}>Crisp (Balanced)</option>
            <option value="focus" ${state.vfxIntensity === 'focus' ? 'selected' : ''}>Minimal (Writer Focus)</option>
          </select>
        </label>
        <label class="v2-theme-picker" style="margin-top:8px">
          <span>Audio Focus</span>
          <select id="v2AudioFocusSelect" aria-label="Audio Focus">
            <option value="overdrive" ${getAudioFocusMode() === 'overdrive' ? 'selected' : ''}>Overdrive Full</option>
            <option value="balanced" ${getAudioFocusMode() === 'balanced' ? 'selected' : ''}>Balanced Studio</option>
            <option value="focus" ${getAudioFocusMode() === 'focus' ? 'selected' : ''}>Writer Focus (Keys)</option>
            <option value="muted" ${getAudioFocusMode() === 'muted' ? 'selected' : ''}>Muted</option>
          </select>
        </label>
        ${(() => {
          const vols = getVolumeSettings();
          return `
            <div class="v2-engine-kv" style="margin-top:6px"><small>Master</small><input type="range" min="0" max="1" step="0.05" value="${vols.master}" data-drawer-vol="master" aria-label="Master Volume" style="width:120px"></div>
            <div class="v2-engine-kv"><small>BGM</small><input type="range" min="0" max="1" step="0.05" value="${vols.bgm}" data-drawer-vol="bgm" aria-label="BGM Volume" style="width:120px"></div>
            <div class="v2-engine-kv"><small>SFX</small><input type="range" min="0" max="1" step="0.05" value="${vols.sfx}" data-drawer-vol="sfx" aria-label="SFX Volume" style="width:120px"></div>
          `;
        })()}
      </div>
      <div class="v2-engine-section">
        <h3>Advanced Views &amp; Diagnostics</h3>
        <div class="v2-engine-actions">
          <button type="button" class="v2-btn" data-engine-view="prose">⚙ Prose Engine &amp; PDG Trace</button>
          <button type="button" class="v2-btn" data-engine-view="laws">⚖ World Laws (Constitution)</button>
          <button type="button" class="v2-btn" data-engine-view="prep">📝 Word Prep Shelf</button>
          <button type="button" class="v2-btn" data-engine-view="lab">🧪 Analysis Lab</button>
          <button type="button" class="v2-btn" data-engine-view="story">◈ Story Graph &amp; Rhythm</button>
          <button type="button" class="v2-btn" id="v2PopLawsBtn" aria-pressed="${state.popModal === 'laws'}">Pop-Out World Laws (Alt+W)</button>
          <button type="button" class="v2-btn" id="v2PopMemoryBtn" aria-pressed="${state.popModal === 'memory'}">Pop-Out Episode Memory (Alt+M)</button>
          <button type="button" class="v2-btn" id="v2PopTimelineBtn" aria-pressed="${state.popModal === 'timeline'}">Pop-Out Timeline Gate (Alt+T)</button>
          <button type="button" class="v2-btn" id="v2PopMediaBtn" aria-pressed="${state.popModal === 'media'}">📦 Media Vault (${state.mediaVault?.assets?.length || 0} · Alt+U)</button>
          <a class="v2-btn" href="/assets/audio/preview.html" target="_blank" rel="noopener">🎵 Open Audio Lab Preview</a>
        </div>
      </div>
      <div class="v2-engine-section">
        <h3>Kernel v5 · PDG Diagnostics</h3>
        <div class="v2-engine-kv"><small>Episode</small><span>${escapeHtml(ep?.title || 'None')} (r${ep?.head ?? 0})</span></div>
        <div class="v2-engine-kv"><small>Protection</small><span>${protection}%</span></div>
        <div class="v2-engine-kv"><small>Minds Loaded</small><span>6 AFM + 4 Green Room</span></div>
        <div class="v2-engine-kv"><small>PDG Mode</small><span>Stage 1 Mind + Stage 2 Surgical Repair</span></div>
        <button type="button" class="v2-btn v2-btn-cook" id="v2DrawerCookBtn" ${!ep || state.busy ? 'disabled' : ''}>Run Cook Pipeline</button>
      </div>
    </aside>

    <div class="v2-body" data-view="${state.view}" ${storyTrack ? 'data-story-track' : ''} ${(state.view === 'graph' && !state.triSplit && !state.graphSplit && (state.graphSubtab || 'switchyard') === 'switchyard') || (state.view === 'story' || state.view === 'beat') || (state.view === 'compose' && state.composeSplitGraph) ? 'data-switchyard' : ''}>
      <aside class="v2-rail-left ${state.navigationOpen ? 'is-open' : ''}" id="v2LeftRail" aria-label="Episodes and scope">
        <div class="v2-project-card">
          <small>Project</small>
          <strong>${escapeHtml(state.timeline?.project_name || 'American Foxy Mom')}</strong>
        </div>
        <div class="v2-rail-tabs" role="tablist" aria-label="Left rail mode">
          <button type="button" class="v2-rail-tab" data-rail-tab="episodes" role="tab" aria-selected="${(state.railTab || 'episodes') === 'episodes'}">Episodes (${episodes.length})</button>
          <button type="button" class="v2-rail-tab" data-rail-tab="shelf" role="tab" aria-selected="${state.railTab === 'shelf'}">Text Shelf</button>
        </div>
        ${state.railTab === 'shelf' ? renderLeftRailShelf(state) : `
        <div class="v2-section-head">
          <span>Episodes</span>
          <span>${episodes.length}</span>
        </div>
        ${['compose','beat'].includes(state.view) && ep && !state.activeDraftId ? `<div class="v2-writing-rail" aria-label="Writing tools"><button type="button" class="v2-btn" id="v2HighlightTool" aria-pressed="${state.highlightMode}" ${nb?.stale || !nb || ep.status !== 'draft' ? 'disabled' : ''}><svg width="15" height="15" viewBox="0 0 24 24" fill="none" aria-hidden="true" stroke="currentColor" stroke-width="2"><path d="m4 15 10-11 5 4-10 11H4zM4 22h16M12 6l5 5"/></svg> Highlighter</button></div>` : ''}
        <div class="v2-episode-list">
          ${episodes
            .map((item) => {
              const active = ep && item.id === ep.id;
              const badge = episodeStageLabel(item, active ? blocks : []);
              const drafts = active ? (state.timelineDrafts || []) : [];
              return `
                <button
                  type="button"
                  class="v2-episode-item"
                  data-episode-id="${escapeHtml(item.id)}"
                  ${active ? 'aria-current="true"' : ''}
                >
                  <span class="v2-episode-title">${escapeHtml(displayEpisodeTitle(item.title || item.id))}</span>
                  <span class="v2-episode-meta">
                    <span class="v2-pill ${badge.cls}">${badge.text}</span>
                    <span>${escapeHtml(item.branch || 'main')}</span>
                  </span>
                </button>
                ${active && (outline.length || drafts.length) ? `
                  <div class="v2-outline-list" aria-label="Draft variants and scene outline">
                    ${drafts.length ? `
                      <div class="v2-rail-group">
                        <small class="v2-rail-subhead">Draft Variants (${drafts.length + 1})</small>
                        <button type="button" class="v2-outline-btn ${!state.activeDraftId ? 'is-active-draft' : ''}" data-rail-current title="Current Active Script">
                          📄 Current (r${ep.head})
                        </button>
                        ${drafts
                          .map(
                            (d, idx) => `
                          <button
                            type="button"
                            class="v2-outline-btn v2-draft-variant-btn ${state.activeDraftId === d.id ? 'is-active-draft' : ''}"
                            data-rail-draft="${escapeHtml(d.id)}"
                            title="Draft ${escapeHtml(d.id)} · ${escapeHtml(d.status || 'PROPOSED')}"
                          >
                            ✨ Draft #${drafts.length - idx} · ${escapeHtml(d.status || 'PROPOSED')}
                          </button>`
                          )
                          .join('')}
                      </div>
                    ` : ''}
                    ${outline.length ? `
                      <div class="v2-rail-group">
                        <small class="v2-rail-subhead">Sections & Scenes (${outline.length})</small>
                        ${outline
                          .map(
                            (sc) => `
                          <button type="button" class="v2-outline-btn" data-jump-block="${escapeHtml(sc.blockId)}" title="${escapeHtml(sc.label)}">
                            ${escapeHtml(sc.label)}
                          </button>`
                          )
                          .join('')}
                      </div>
                    ` : ''}
                  </div>
                ` : ''}`;
            })
            .join('')}
        </div>
        `}
      </aside>

      <main class="v2-stage">
        ${renderStage(state, ep, blocks, stats)}
      </main>

      <aside class="v2-rail-right ${state.inspectorOpen ? 'is-open' : ''}" id="v2RightRail" aria-label="Inspector">
        <div id="v2ViewInspectorHost">
        ${state.view === 'start' || storyTrack ? '' : state.view === 'timeline'
          ? renderTimelineInspector(state)
          : state.view === 'graph'
          ? renderGraphInspector(state)
          : state.view === 'prose'
          ? renderScenePlan(state) + renderProseInspector(state)
          : state.view === 'laws'
          ? renderLawsInspector(state)
          : `
          ${renderScenePlan(state)}
          <div class="v2-inspector-card">
            <h2>Document protection</h2>
            <div class="v2-race-dial-wrap" id="v2DocDial">${(state.theme === 'racing' || state.theme === 'noir-v4') ? renderTrack(protection) : ''}<div class="v2-protection-value">${protection}%</div></div>
            <div class="v2-weight-grid" role="group" aria-label="Document protection weight">
              ${[25, 50, 75, 100]
                .map(
                  (w) => `
                <button
                  type="button"
                  class="v2-weight-btn"
                  data-weight="${w}"
                  aria-pressed="${protection === w ? 'true' : 'false'}"
                  ${state.busy || !ep ? 'disabled' : ''}
                >${w}%</button>`
                )
                .join('')}
            </div>
            <div class="v2-delta-preview-bar" id="v2DocDeltaBar" title="Projected Protection Delta">
              <div class="v2-delta-preview-base" style="width:${protection}%"></div>
              <div class="v2-delta-preview-seg" style="width:0%;opacity:0"></div>
            </div>
          </div>
          ${renderProtectionInspector(nb, stats.fullText, state)}
        `}
        </div>
        <div class="v2-inspector-card">
          <h2>Workspace status</h2>
          <div class="v2-notice" data-tone="${escapeHtml(state.notice.tone)}" role="status">
            ${escapeHtml(state.notice.text)}
          </div>
        </div>
        ${renderDirectorInspector(state, ep)}
      </aside>
    </div>

    <footer class="v2-footer" aria-label="Document statistics">
      ${state.view === 'timeline' ? `
        <span>${(state.timeline?.cards || []).length} episodes</span>
        <span>${(Array.isArray(state.timeline?.branches) ? state.timeline.branches.length : Object.keys(state.timeline?.branches || { main: true }).length)} branch(es)</span>
        <span>Theme: ${state.theme}</span>
      ` : `
        <span>${stats.blocks} ${stats.blocks === 1 ? 'block' : 'blocks'}</span>
        <span>${stats.words} words</span>
        <span>${stats.chars} characters</span>
        <span>Theme: ${state.theme}</span>
      `}
    </footer>
    ${state.popModal ? `
      <div class="v2-pop-backdrop" id="v2PopModal" role="dialog" aria-modal="true" aria-label="${state.popModal === 'laws' ? 'World Laws Pop-Out' : state.popModal === 'memory' ? 'Episode Memory &amp; Basic Facts' : state.popModal === 'trash' ? 'Soft-Deleted Recovery Vault' : state.popModal === 'media' ? 'Multimodal Media Vault' : 'Episode Timeline'}">
        <div class="v2-pop-dialog">
          <div class="v2-pop-head">
            <strong>${state.popModal === 'laws' ? '⚖ World Laws (Global Pop-Out Controller · Alt+W)' : state.popModal === 'memory' ? '🧠 Episode Memory &amp; Basic Facts (Alt+M)' : state.popModal === 'trash' ? `🗑 Soft-Deleted Recovery Vault (${globalHistory.getTrash().length})` : state.popModal === 'media' ? `📦 Multimodal Media Vault (${state.mediaVault?.assets?.length || 0} sources · Alt+U)` : '🕒 Episode Timeline & Chronology Gate (Alt+T)'}</strong>
            <button type="button" class="v2-btn" id="v2PopCloseBtn">✕ Close (Esc)</button>
          </div>
          <div class="v2-pop-body">
            ${state.popModal === 'laws' ? renderLawsStage(state) : state.popModal === 'memory' ? renderMemoryStage(state, ep, blocks) : state.popModal === 'trash' ? renderTrashStage() : state.popModal === 'media' ? renderMediaVaultModal(state) : renderTimelineStage(state)}
          </div>
        </div>
      </div>
    ` : ''}
    <div id="v2CookMount">${renderCookOverlay(state)}</div>
    <div id="v2MaskMount"></div>
  `;

  bindEvents(state);
  for (const [selector, top, left] of previousScroll) root.querySelector(selector)?.scrollTo(left, top);
  if (focusedPicker) document.getElementById(focusedPicker)?.focus({ preventScroll: true });
}

function renderTrashStage() {
  const items = globalHistory.getTrash();
  if (!items.length) {
    return '<div class="v2-inspector-card"><p class="v2-muted">Trash is empty. Every node, attachment, or media hook removed in Studio v2 is soft-deleted and restorable here or via Ctrl+Z.</p></div>';
  }
  return `
    <div style="display:grid;gap:8px;">
      ${items.map((item) => `
        <div class="v2-inspector-card" style="display:flex;align-items:center;justify-content:space-between;gap:12px;">
          <div>
            <strong>${escapeHtml(item.label)}</strong>
            <div class="v2-muted" style="font-size:11.5px;">Type: ${escapeHtml(item.kind)} · Deleted at ${escapeHtml(item.deletedAt)}</div>
          </div>
          <button type="button" class="v2-btn v2-btn-accent" data-restore-global-trash="${escapeHtml(item.id)}">↩ Restore Intact</button>
        </div>
      `).join('')}
    </div>
  `;
}

function renderMemoryStage(state, ep, blocks) {
  const junctions = state.formGraph?.junctions || [];
  const outline = extractSceneOutline(blocks || []);
  const beatCount = state.beatMap?.beats?.length || 0;
  const protection = state.episodeState?.notebook?.default_protection ?? 100;
  const rulesCount = (state.worldLaws?.rules || state.worldLaws?.laws || []).length;
  const title = ep ? displayEpisodeTitle(ep.title || ep.id) : 'No episode selected';
  return `
    <div class="v2-memory-grid">
      <section class="v2-memory-card">
        <h3>Spatial &amp; Timeline Anchor</h3>
        <div><span class="v2-memory-pill">${escapeHtml(ep?.branch || 'main')}</span> <span class="v2-memory-pill">r${ep?.head ?? 0}</span></div>
        <ul class="v2-memory-list">
          <li><strong>Episode:</strong> ${escapeHtml(title)}</li>
          <li><strong>Default Protection:</strong> ${protection}%</li>
          <li><strong>Noise Mode:</strong> ${escapeHtml(String(state.director?.noise_mode ?? '50'))}%</li>
        </ul>
      </section>
      <section class="v2-memory-card">
        <h3>Character Minds &amp; Forms (${junctions.length})</h3>
        ${junctions.length ? `<ul class="v2-memory-list">${junctions.slice(0, 6).map((j) => `<li><strong>${escapeHtml(j.label || j.character_id)}</strong> · ${escapeHtml(j.active_form || j.forms?.[0]?.label || 'Default')}</li>`).join('')}</ul>` : '<p class="v2-muted">No character junctions loaded for this episode yet.</p>'}
      </section>
      <section class="v2-memory-card">
        <h3>Scene &amp; Beat Memory (${outline.length})</h3>
        ${outline.length ? `<ul class="v2-memory-list">${outline.slice(0, 6).map((s) => `<li>${escapeHtml(s.label)}</li>`).join('')}</ul>` : `<p class="v2-muted">${beatCount ? `${beatCount} beat(s) mapped.` : 'No scene headings extracted yet.'}</p>`}
      </section>
      <section class="v2-memory-card">
        <h3>World Laws &amp; Canon Guard</h3>
        <ul class="v2-memory-list">
          <li><strong>Universe Laws:</strong> ${rulesCount} loaded</li>
          <li><strong>Cook Scope:</strong> ${escapeHtml(state.director?.cook_scope || 'scene_group')}</li>
          <li><strong>Text Shelf Loaded:</strong> ${escapeHtml(state.loadedShelfSnippet?.title || 'None')}</li>
        </ul>
      </section>
    </div>
  `;
}

function renderCookOverlay(state) {
  const job = state.cookJob;
  if (!state.cookModalOpen || !job) return '';
  const pct = Math.max(0, Math.min(100, Number(job.progress || 0)));
  const isDone = job.status === 'completed';
  const isFailed = job.status === 'failed';
  const stages = Array.isArray(job.stages) ? job.stages : [];
  const firstGraph = job.result?.receipt?.fragments?.[0];
  return `
    <div class="v2-cook-overlay" id="v2CookOverlay" role="dialog" aria-modal="true" aria-labelledby="v2CookTitle">
      <div class="v2-cook-modal">
        <div class="v2-cook-head">
          <div>
            <span class="v2-cook-eyebrow">NOIR ENGINE // R&amp;D PIPELINE</span>
            <h2 id="v2CookTitle">COOK PROGRESS</h2>
          </div>
          <span class="v2-cook-pct">${pct}%</span>
        </div>
        <div class="v2-cook-bar-track" role="progressbar" aria-valuenow="${pct}" aria-valuemin="0" aria-valuemax="100">
          <div class="v2-cook-bar-fill ${isDone ? 'is-done' : ''}" style="width: ${pct}%"></div>
        </div>
        <p class="v2-cook-message">${escapeHtml(job.message || '')}</p>
        <div class="v2-cook-stages">
          ${stages.map((s, idx) => `
            <div class="v2-cook-stage" data-status="${escapeHtml(s.status || 'pending')}">
              <span class="v2-cook-stage-idx">0${idx + 1}</span>
              <div class="v2-cook-stage-body">
                <strong>${escapeHtml(s.label || '')}</strong>
                <small>${escapeHtml(s.detail || '')}</small>
              </div>
              <span class="v2-cook-stage-pill">${escapeHtml(s.cache || String(s.status || 'pending').toUpperCase())}</span>
            </div>
          `).join('')}
        </div>
        ${isDone ? `
          <div class="v2-cook-ribbon" role="status">
            <strong>${job.run?.draft_id ? 'Cook draft saved' : job.run?.status === 'PRESERVED' ? 'Passage preserved' : 'Episode prepared'}</strong>
            <span>${job.run ? escapeHtml(job.message) : firstGraph ? 'Choose a saved passage and writer to render a draft.' : 'Add scene text to prepare a scene graph.'}</span>
          </div>
        ` : ''}
        ${isFailed ? `
          <div class="v2-notice" data-tone="err" role="alert">${escapeHtml(job.error || 'Cook failed')}</div>
        ` : ''}
        ${job.status !== 'running' && job.result?.receipt && state.beatMap?.beats?.length ? `
          <form id="v2CookRenderForm" class="v2-cook-actions">
            <label>Passage <select name="passage">${state.beatMap.beats.map((beat) => `<option value="${escapeHtml(beat.id)}" ${state.storyStructure?.selected === beat.id ? 'selected' : ''}>Passage ${beat.number}</option>`).join('')}</select></label>
            <label>Writer <select name="provider" required>${(state.writers || []).map((writer) => `<option value="${escapeHtml(writer.id)}">${escapeHtml(writer.label)}</option>`).join('')}</select></label>
            <button type="submit" class="v2-btn v2-btn-accent" ${state.busy ? 'disabled' : ''}>Render passage</button>
          </form>` : ''}
        <div class="v2-cook-actions">
          ${job.run?.draft_id ? '<button type="button" class="v2-btn" id="v2OpenCookDraft">Open saved draft</button>' : ''}
          ${firstGraph ? `<a class="v2-btn" href="/scene-fragments?${escapeHtml(new URLSearchParams({episode:job.episode, fragment:firstGraph.id}).toString())}">Open scene graphs</a>` : ''}
          <button type="button" class="v2-btn ${isDone ? 'v2-btn-accent' : ''}" id="v2CookCloseBtn" ${job.status === 'running' ? 'disabled' : ''}>
            ${isDone ? 'Done' : 'Close'}
          </button>
        </div>
      </div>
    </div>
  `;
}

function renderWorldHero({ plate, eyebrow, title, subtitle, chips = [] }) {
  return `
    <section class="v2-gp-world-hero" style="--gp-hero-plate: url('/assets/v2/${escapeHtml(plate)}');">
      <div class="v2-gp-world-hero-copy">
        <span class="v2-gp-world-eyebrow">${escapeHtml(eyebrow)}</span>
        <h2 class="v2-gp-world-title">${escapeHtml(title)}</h2>
        <p class="v2-gp-world-sub">${escapeHtml(subtitle)}</p>
      </div>
      ${chips.length ? `<div class="v2-gp-world-hero-stats">${chips.map((c) => `<div class="v2-gp-stat-chip"><small>${escapeHtml(c.label)}</small><strong>${escapeHtml(String(c.value))}</strong></div>`).join('')}</div>` : ''}
    </section>
  `;
}

function renderStage(state, ep, blocks, stats) {
  if (state.view === 'lab') return renderAnalysisLabStage(state);
  if (state.view === 'prep') return renderWordPrepWorkspace(state);
  if (state.view === 'start' || (state.view === 'compose' && !ep && !state.busy)) return renderIntake(state);
  if (state.view === 'story') {
    const sub = state.storySubtab || 'graph';
    const subbar = `
      <div class="sg-subbar" role="tablist" aria-label="Story Graph and Rhythm">
        <div class="sg-subtabs">
          <button type="button" class="sg-subtab" role="tab" data-story-subtab="graph" aria-selected="${sub === 'graph' ? 'true' : 'false'}">Beat DAG</button>
          <button type="button" class="sg-subtab" role="tab" data-story-subtab="rhythm" aria-selected="${sub === 'rhythm'}">Rhythm &amp; Timing</button>
          <button type="button" class="sg-subtab" role="tab" data-story-subtab="passages" aria-selected="${sub === 'passages'}">Story Beats</button>
          <button type="button" class="sg-subtab" role="tab" data-story-subtab="processing" aria-selected="${sub === 'processing'}">Processing</button>
          <button type="button" class="sg-subtab" role="tab" data-story-subtab="laws" aria-selected="${sub === 'laws' ? 'true' : 'false'}">World Laws</button>
        </div>
        <div style="display:flex;align-items:center;gap:8px;">
          ${ep ? `<button type="button" class="v2-mini-btn" data-open-media-vault="beat">📦 Media Vault (${state.mediaVault?.assets?.length || 0})</button>` : ''}
          <span class="v2-muted">${escapeHtml(ep?.title || 'Select an episode')}</span>
        </div>
      </div>
    `;
    const hero = renderWorldHero({
      plate: sub === 'laws' ? 'world-coliseum-arena.webp' : 'world-sky-track.webp',
      eyebrow: 'NOIR STUDIO · STORY GRAPH & BEAT RHYTHM ENGINE',
      title: sub === 'laws' ? 'World Laws Constitution' : 'Story Graph & Beat Rhythm',
      subtitle: 'Unified Beat DAG, What-If branches, beat rhythm/pacing direction, room portals, and clip attachments.',
      chips: [{ label: 'BEATS', value: state.beatMap?.beats?.length || stats.blocks }, { label: 'REVISION', value: `r${ep?.head ?? 0}` }],
    });
    if (sub === 'laws') return hero + subbar + renderLawsStage(state);
    if (sub === 'passages') return subbar + renderStoryTimeline(state);
    if (sub === 'rhythm') return subbar + renderActStructure(state) + renderBeatStage(state) +
      `<details class="v2-beat-options"><summary>Beat settings and timing</summary>${renderBeatInspector(state)}</details>`;
    if (sub === 'processing') return subbar + `<section class="v2-inspector-card">
      <h2>Processing receipts</h2><button type="button" id="v2ReloadProcessing" class="v2-btn">Refresh</button>
      ${(state.processingJobs || []).map((job) => `<details><summary>${escapeHtml(job.title || job.kind)} · ${escapeHtml(job.status)}</summary>
        <ol>${(job.steps || []).map((step) => `<li>${escapeHtml(step.label || step.id)} · ${escapeHtml(step.status)}</li>`).join('')}</ol></details>`).join('')
      || '<p class="v2-hint">No processing receipts for this episode.</p>'}
    </section>`;
    return hero + subbar + renderStoryGraphCanvas(state);
  }
  if (state.view === 'timeline') return renderTimelineStage(state);
  if (state.view === 'graph') {
    const beat = state.view === 'beat';
    const tri = !beat && state.triSplit;
    const split = beat ? state.beatPaper : state.graphSplit;
    const paperHtml = ep ? renderComposeStage({
      ep, blocks, stats, badge: episodeStageLabel(ep), state: { ...state, activeDraftId: null }, speakerPicker: state.speakerPicker,
    }) : '<p class="v2-muted">Select or create an episode to compose.</p>';
    const ratio = state.triRatio || 'balanced';
    const isDefaultSwitchyard = !beat && !tri && !split && (state.graphSubtab || 'switchyard') === 'switchyard';
    const modeBar = isDefaultSwitchyard ? '' : `<div class="v2-workspace-mode" role="group" aria-label="Workspace layout">
      ${!beat ? `<button class="v2-btn" id="v2ShowTriSplit" aria-pressed="${!!tri}">Tri-Split</button>` : ''}
      <button class="v2-btn" id="v2ShowSplit" aria-pressed="${!tri && !!split}">Split view</button>
      <button class="v2-btn" id="v2ShowSingle" aria-pressed="${!tri && !split}">${beat ? 'Full Beat Map' : 'Full Graph'}</button>
      ${tri ? `<div class="v2-tri-ratio-group" role="group" aria-label="Tri-split ratio presets">
        <button type="button" class="v2-btn" data-tri-ratio="balanced" aria-pressed="${ratio === 'balanced'}">Balanced</button>
        <button type="button" class="v2-btn" data-tri-ratio="writer" aria-pressed="${ratio === 'writer'}">Writer</button>
        <button type="button" class="v2-btn" data-tri-ratio="graph" aria-pressed="${ratio === 'graph'}">Graph</button>
      </div>` : ''}
      ${beat && ep ? `<button type="button" class="v2-btn" data-open-media-vault="beat">📦 Media Vault (${state.mediaVault?.assets?.length || 0})</button>` : ''}
    </div>`;
    const hero = renderWorldHero({
      plate: beat ? 'world-starting-grid.webp' : 'world-turntable-garage.webp',
      eyebrow: beat ? 'NOIR STUDIO · BEAT STUDIO & SCENE CLIPS' : 'NOIR STUDIO · CHARACTER SWITCHYARD & FORM GARAGE',
      title: beat ? 'Beat Studio & Timing' : 'Character Switchyard & Form Dock',
      subtitle: beat ? 'Inspect scene beats, rhythm-gag timing, and linked media clips.' : 'Tune character minds, form states, directional relationship edges, and media pins.',
      chips: [{ label: 'WORDS', value: stats.words }, { label: 'HEAD', value: `r${ep?.head ?? 0}` }],
    });
    if (tri) {
      const solo = state.soloPane;
      const paneCls = (name) => `v2-tri-pane ${solo === name ? 'is-solo' : (solo ? 'is-hidden' : '')}`;
      const soloLabel = (name) => (solo === name ? '⤢ Tri-Split' : '⛶ Focus');
      return `${hero}${modeBar}<div class="v2-tri-split" data-ratio="${ratio}">
        <section class="${paneCls('compose')}" aria-label="1 · Narrative Composer">
          <div class="v2-tri-pane-head"><span>1 · Composer</span><button type="button" class="v2-btn" data-solo-pane="compose">${soloLabel('compose')}</button></div>
          ${paperHtml}
        </section>
        <section class="${paneCls('graph')}" aria-label="2 · Story Systems Graph">
          <div class="v2-tri-pane-head"><span>2 · Story Systems Graph</span><button type="button" class="v2-btn" data-solo-pane="graph">${soloLabel('graph')}</button></div>
          ${renderGraphStage({ ...state, graphSubtab: 'story' })}
        </section>
        <section class="${paneCls('forms')}" aria-label="3 · Character System & Form Dock">
          <div class="v2-tri-pane-head"><span>3 · Character &amp; Form Dock</span><button type="button" class="v2-btn" data-solo-pane="forms">${soloLabel('forms')}</button></div>
          ${renderGraphStage({ ...state, graphSubtab: 'forms' })}
        </section>
      </div>`;
    }
    const paper = ep && split ? `<section class="v2-beat-paper" aria-label="Editable notebook">${paperHtml}</section>` : '';
    return `${hero}${modeBar}<div class="v2-workspace-split ${paper ? 'is-split' : ''}">${paper}
      <section class="v2-beat-pane" aria-label="${beat ? 'Beat Map' : 'Character and story graphs'}">
        ${beat ? `${renderBeatStage(state)}<details class="v2-beat-options"><summary>Beat settings and timing</summary>${renderBeatInspector(state)}</details>` : renderGraphStage(state)}
      </section></div>`;
  }
  if (state.view === 'prose') {
    return renderProseStage(state);
  }
  if (state.view === 'laws') {
    return renderWorldHero({
      plate: 'world-coliseum-arena.webp',
      eyebrow: 'NOIR STUDIO · UNIVERSE CONSTITUTION & HARD GUARDS',
      title: 'World Laws',
      subtitle: 'Authoritative hard rules and causal constraints enforced across simulation and prose.',
      chips: [{ label: 'EPISODE', value: ep?.title || 'None' }],
    }) + renderLawsStage(state);
  }
  const composeHero = renderWorldHero({
    plate: 'world-paddock-canopy.webp',
    eyebrow: 'NOIR STUDIO · PADDOCK MANUSCRIPT & SPLIT GRAPH',
    title: ep ? displayEpisodeTitle(ep.title || ep.id) : 'Composer',
    subtitle: 'Warm parchment manuscript with frozen dialogue locks, uplift dials, and live bi-directional Story Graph.',
    chips: [{ label: 'WORDS', value: stats.words }, { label: 'BLOCKS', value: stats.blocks }, { label: 'REV', value: `r${ep?.head ?? 0}` }],
  });
  const composeHtml = renderComposeStage({
    ep,
    badge: episodeStageLabel(ep),
    blocks,
    stats,
    state,
    speakerPicker: state.speakerPicker,
  });
  if (state.composeSplitGraph) {
    return `${composeHero}<div class="v2-compose-story-split"><div class="v2-compose-split-left">${composeHtml}</div><div class="v2-compose-split-right">${renderStoryGraphCanvas(state, { compact: true })}</div></div>`;
  }
  return composeHero + composeHtml;
}

function bindEvents(state) {
  const openSavedDraft = async (id) => {
    const s = store.get();
    const ep = s.episodeState?.episode;
    if (!ep || !id) return;
    if (s.dirty) {store.set({notice:{text:'Save the open notebook before opening a variant.',tone:'warn'}});return;}
    try {
      const draft = await NoirApi.episodeCommand({ action: 'draft.open', episode: ep.id, branch: ep.branch, draft: id });
      if (store.get().episodeId !== ep.id) return;
      store.setQuiet({ activeDraftId:draft.id, timelineDrafts:[draft,...store.get().timelineDrafts.filter(d=>d.id!==draft.id)] });
      changeView('compose');
    } catch (e) { store.set({ notice:{text:e.message,tone:'err'} }); }
  };
  document.getElementById('v2ThemeSelect')?.addEventListener('change', (e) => {
    playTick();
    store.set({ theme: e.target.value });
  });

  document.getElementById('v2SoundBtn')?.addEventListener('click', (e) => {
    const next = !store.get().soundEnabled;
    setSoundEnabled(next);
    store.setQuiet({ soundEnabled: next });
    const btn = e.currentTarget;
    btn.setAttribute('aria-pressed', String(next));
    btn.textContent = next ? 'SFX: On' : 'SFX: Off';
    if (next) playTick();
  });

  document.getElementById('v2MusicBtn')?.addEventListener('click', (e) => {
    const next = !store.get().musicEnabled;
    setMusicEnabled(next);
    store.setQuiet({ musicEnabled: next });
    const btn = e.currentTarget;
    btn.setAttribute('aria-pressed', String(next));
    btn.textContent = next ? 'Music: On' : 'Music: Off';
    if (store.get().soundEnabled) playTick();
  });

  const applyVfxMode = (mode) => {
    const safe = setVfxIntensity(mode);
    store.setQuiet({ vfxIntensity: safe });
    const btn = document.getElementById('v2VfxModeBtn');
    if (btn) btn.textContent = `VFX: ${safe === 'focus' ? 'Minimal' : safe === 'balanced' ? 'Crisp' : 'Full'}`;
    const sel = document.getElementById('v2VfxSelect');
    if (sel) sel.value = safe;
    if (store.get().soundEnabled) playTick();
  };

  document.querySelectorAll('[data-drawer-vol]').forEach((sl) => {
    sl.addEventListener('input', () => setVolumeSetting(sl.dataset.drawerVol, Number(sl.value)));
  });

  const deltaBar = document.getElementById('v2DocDeltaBar');
  if (deltaBar) {
    const baseEl = deltaBar.querySelector('.v2-delta-preview-base');
    const segEl = deltaBar.querySelector('.v2-delta-preview-seg');
    const basePct = parseFloat(baseEl?.style.width || '100') || 0;
    document.querySelectorAll('.v2-weight-btn[data-weight]').forEach((btn) => {
      btn.addEventListener('pointerenter', () => {
        const w = Number(btn.dataset.weight || 0);
        if (!segEl || !baseEl) return;
        const lo = Math.min(basePct, w);
        const diff = Math.abs(w - basePct);
        baseEl.style.width = `${lo}%`;
        segEl.style.width = `${diff}%`;
        segEl.style.opacity = diff > 0 ? '1' : '0';
      });
      btn.addEventListener('pointerleave', () => {
        if (!segEl || !baseEl) return;
        baseEl.style.width = `${basePct}%`;
        segEl.style.width = '0%';
        segEl.style.opacity = '0';
      });
    });
  }

  document.getElementById('v2VfxModeBtn')?.addEventListener('click', () => {
    const cur = store.get().vfxIntensity || 'overdrive';
    const order = ['overdrive', 'balanced', 'focus'];
    applyVfxMode(order[(order.indexOf(cur) + 1) % order.length]);
  });

  const syncAudioFocusUi = (mode) => {
    const btn = document.getElementById('v2AudioFocusBtn');
    if (btn) btn.textContent = `Audio: ${mode.replace(/^\w/, (c) => c.toUpperCase())}`;
    const sel = document.getElementById('v2AudioFocusSelect');
    if (sel) sel.value = mode;
    const sBtn = document.getElementById('v2SoundBtn');
    if (sBtn) {
      const sOn = isSoundEnabled();
      store.setQuiet({ soundEnabled: sOn });
      sBtn.setAttribute('aria-pressed', String(sOn));
      sBtn.textContent = sOn ? 'SFX: On' : 'SFX: Off';
    }
    const mBtn = document.getElementById('v2MusicBtn');
    if (mBtn) {
      const mOn = isMusicEnabled();
      store.setQuiet({ musicEnabled: mOn });
      mBtn.setAttribute('aria-pressed', String(mOn));
      mBtn.textContent = mOn ? 'Music: On' : 'Music: Off';
    }
  };

  document.getElementById('v2AudioFocusBtn')?.addEventListener('click', () => {
    const next = cycleAudioFocusMode();
    syncAudioFocusUi(next);
    if (next !== 'muted') playTick();
  });

  document.getElementById('v2AudioFocusSelect')?.addEventListener('change', (e) => {
    const next = setAudioFocusMode(e.target.value);
    syncAudioFocusUi(next);
    if (next !== 'muted') playTick();
  });

  document.getElementById('v2VfxSelect')?.addEventListener('change', (e) => {
    applyVfxMode(e.target.value);
  });

  noirVfx.ensureMounted();
  if (!window.__noirDelegatedFxBound) {
    window.__noirDelegatedFxBound = true;
    document.addEventListener('input', (e) => {
      if (e.target && (e.target.tagName === 'TEXTAREA' || e.target.isContentEditable)) {
        FX.trigger('WRITER_TYPING');
      }
    }, { passive: true });
    document.addEventListener('click', (e) => {
      const t = e.target;
      if (!t?.closest) return;
      const node = t.closest('.v2-node-row, .sw-node, .sg-node, .v2-gp-route-card, .v2-shelf-card, .v2-tl-card');
      if (node) {
        FX.trigger('NODE_SELECT', { el: node, badgeText: 'Selected' });
        return;
      }
      if (t.closest('[data-prep-auto-format], [data-lab-run-sim], #v2LabForkBtn')) {
        FX.trigger('PROC_SWEEP', { el: t.closest('button'), label: 'Processing Pass...' });
      } else if (t.closest('[data-prep-inject-lock], [data-prep-bind-law], [data-highlight-weight="100"], [data-board-save], #v2CanonApplyCorrectionsBtn, #v2ScopedApplyFixesBtn')) {
        FX.trigger('LOCK_FREEZE', { el: t.closest('button'), badgeText: 'Hard Lock' });
      } else if (t.closest('#v2PrepSendBtn')) {
        FX.trigger('COOK_COMPLETE', { title: 'PREPPED SCRIPT COMMITTED', subtitle: 'Synced to Compose & Story Graph' });
      } else if (t.closest('#v2AutoSplitBtn, [data-split-block], [data-merge-block], [data-home-route], #v2IntakeForm button[type="submit"]')) {
        FX.trigger('EXECUTE_CONFIRM', { el: t.closest('button'), badgeText: 'Executed' });
      } else if (t.closest('#v2AddEpisodeBtn, [data-timeline-subtab]')) {
        FX.trigger('TIMELINE_ADVANCE');
      } else if (t.closest('.sw-beat-btn')) {
        FX.trigger('OVERDRIVE_SURGE', { el: t.closest('button'), label: 'BRANCH SHIFT' });
      } else if (t.closest('[data-prep-tag-law], [data-jump-story-beat], [data-jump-char-graph]')) {
        FX.trigger('RETICLE_LOCK', { el: t.closest('button'), badgeText: 'Linked' });
      }
    }, { passive: true });
  }
  if (state.view === 'prep' && new URLSearchParams(location.search).get('vfx_demo') === '1' && !window.__noirVfxDemoFired) {
    window.__noirVfxDemoFired = true;
    setTimeout(() => {
      const row = document.querySelector('.v2-node-row.is-stage-direction') || document.querySelector('.v2-node-row');
      const badge = row?.querySelector('.v2-gutter-circle');
      if (row) {
        noirVfx.playEnergySweep(row, 'Optimizing Node: stage-direction 68%');
        noirVfx.playSparkBurst(row, '+1 LAW BOUND', true);
      }
      if (badge) noirVfx.playOverdriveCharge(badge);
      noirVfx.flashTelemetryDelta('lawRefs', '+1');
      noirVfx.playMilestoneRibbon('ACTION COMPLETED · OVERDRIVE SYNC', 'EffectCraft Lottie + Nuke 17.0v3 Optical Bloom');
      noirVfx.showLawInterceptToast({
        title: 'WORLD LAW INTERCEPT · HARD GUARD',
        message: '@law:kidney-price verified on Stage Direction — active across Story & Character Graphs.',
        badge: '⛨ LAW',
        accent: 'law',
      });
    }, 350);
  }

  document.getElementById('v2EngineDrawerBtn')?.addEventListener('click', () => {
    playTick();
    store.set({ engineDrawerOpen: !store.get().engineDrawerOpen });
  });

  document.getElementById('v2EngineDrawerCloseBtn')?.addEventListener('click', () => {
    playTick();
    store.set({ engineDrawerOpen: false });
  });

  document.querySelectorAll('[data-engine-view]').forEach((btn) => {
    btn.addEventListener('click', () => {
      playTick();
      const view = btn.dataset.engineView;
      store.setQuiet({ engineDrawerOpen: false });
      changeView(view);
    });
  });

  document.getElementById('v2WorkspacePicker')?.addEventListener('change', (e) => {
    playTick();
    changeView(e.currentTarget.value);
  });
  document.getElementById('v2InspectorToggle')?.addEventListener('click', () => {
    playTick();
    setPanels(false, !store.get().inspectorOpen);
  });
  document.getElementById('v2NavigationToggle')?.addEventListener('click', () => setPanels(!store.get().navigationOpen, false));
  document.getElementById('v2HighlightTool')?.addEventListener('click', () => {
    if (store.get().dirty) { store.set({ notice: { text: 'Save your text before adding a mask.', tone: 'warn' } }); return; }
    store.set({ highlightMode: !store.get().highlightMode, selectionRange: null, navigationOpen: false });
    document.querySelector('[data-mask-surface]')?.focus({ preventScroll: true });
  });

  document.querySelectorAll('.v2-tab[data-view]').forEach((btn) => {
    btn.addEventListener('click', () => {
      playTick();
      const view = btn.dataset.view;
      changeView(view);
    });
  });

  document.querySelectorAll('.v2-episode-item[data-episode-id]').forEach((btn) => {
    btn.addEventListener('click', () => {
      playSelect();
      selectEpisode(btn.dataset.episodeId);
    });
  });

  document.querySelectorAll('.v2-outline-btn[data-jump-block]').forEach((btn) => {
    btn.addEventListener('click', () => {
      playTick();
      const card = document.querySelector(`.v2-block-card[data-block-id="${CSS.escape(btn.dataset.jumpBlock)}"]`);
      if (store.get().navigationOpen) {
        setPanels(false, false);
        (card?.querySelector('[data-block-text]') || document.getElementById('v2NavigationToggle'))?.focus({ preventScroll: true });
      }
      card?.scrollIntoView({ behavior: 'smooth', block: 'start' });
    });
  });

  document.querySelectorAll('[data-rail-current]').forEach((btn) => {
    btn.addEventListener('click', () => {
      playSelect();
      const url = new URL(location.href);
      url.searchParams.set('view', 'compose');
      history.replaceState(null, '', url);
      store.set({ view: 'compose', activeDraftId: null });
    });
  });

  document.querySelectorAll('[data-rail-draft]').forEach((btn) => {
    btn.addEventListener('click', () => {
      playSelect();
      openSavedDraft(btn.dataset.railDraft);
    });
  });

  document.querySelectorAll('.v2-weight-btn[data-weight]').forEach((btn) => {
    btn.addEventListener('click', () => {
      playSelect();
      setProtectionWeight(Number(btn.dataset.weight));
    });
  });

  bindShelfAndWordMockup({ store, api: NoirApi, changeView, onPromoted: selectEpisode });

  document.getElementById('v2UndoBtn')?.addEventListener('click', () => {
    const cur = store.get();
    if (cur.projectHistory?.next_undo) {
      void stepProjectHistory('undo');
      return;
    }
    if ((cur.projectHistory?.revision || !['compose', 'beat'].includes(cur.view) || !cur.episodeState?.notebook?.can_undo) && globalHistory.canUndo()) {
      const label = globalHistory.undo();
      FX.trigger('TELEMETRY_DELTA');
      store.set({ notice: { text: `Undid: ${label}`, tone: 'ok' } });
      return;
    }
    if (!cur.projectHistory?.revision) void stepHistory('undo');
  });
  document.getElementById('v2RedoBtn')?.addEventListener('click', () => {
    const cur = store.get();
    if (cur.projectHistory?.next_redo) {
      void stepProjectHistory('redo');
      return;
    }
    if ((cur.projectHistory?.revision || !['compose', 'beat'].includes(cur.view) || !cur.episodeState?.notebook?.can_redo) && globalHistory.canRedo()) {
      const label = globalHistory.redo();
      FX.trigger('TELEMETRY_DELTA');
      store.set({ notice: { text: `Redid: ${label}`, tone: 'ok' } });
      return;
    }
    if (!cur.projectHistory?.revision) void stepHistory('redo');
  });
  document.getElementById('v2TrashBtn')?.addEventListener('click', () => {
    playTick();
    store.set({ popModal: store.get().popModal === 'trash' ? null : 'trash' });
  });
  document.querySelectorAll('[data-restore-global-trash]').forEach((btn) => {
    btn.addEventListener('click', () => {
      const label = globalHistory.restoreTrash(btn.dataset.restoreGlobalTrash);
      FX.trigger('EXECUTE_CONFIRM', { el: btn, badgeText: 'Restored' });
      store.set({ notice: { text: label ? `Restored: ${label}` : 'Restored item.', tone: 'ok' } });
    });
  });
  document.querySelectorAll('#v2CookBtn, [data-run-cook]').forEach((button) => {
    button.addEventListener('click', runCookPipeline);
  });
  bindCookRender();
  document.getElementById('v2CookCloseBtn')?.addEventListener('click', () => {
    playTick();
    store.setQuiet({ cookModalOpen: false });
    updateCookMount();
  });
  document.getElementById('v2SaveBtn')?.addEventListener('click', saveDocumentChanges);
  for (const [id, enabled] of [['v2ShowSplit',true],['v2ShowSingle',false]]) {
    document.getElementById(id)?.addEventListener('click', () => {
      store.set(state.view==='beat' ? { beatPaper: enabled } : { graphSplit: enabled, triSplit: false, soloPane: null });
    });
  }
  document.getElementById('v2ShowTriSplit')?.addEventListener('click', () => {
    playTick();
    store.set({ triSplit: true, graphSplit: false, soloPane: null });
  });
  document.querySelectorAll('[data-tri-ratio]').forEach((btn) => {
    btn.addEventListener('click', () => {
      playTick();
      store.set({ triRatio: btn.dataset.triRatio || 'balanced' });
    });
  });
  document.querySelectorAll('[data-solo-pane]').forEach((btn) => {
    btn.addEventListener('click', () => {
      playTick();
      const target = btn.dataset.soloPane;
      store.set({ soloPane: store.get().soloPane === target ? null : target });
    });
  });
  document.getElementById('v2StarterBtn')?.addEventListener('click', () => {
    playTick();
    changeView('start');
  });
  document.getElementById('v2PopLawsBtn')?.addEventListener('click', () => {
    playTick();
    store.set({ popModal: store.get().popModal === 'laws' ? null : 'laws' });
  });
  document.getElementById('v2PopMemoryBtn')?.addEventListener('click', () => {
    playTick();
    store.set({ popModal: store.get().popModal === 'memory' ? null : 'memory' });
  });
  document.getElementById('v2PopTimelineBtn')?.addEventListener('click', () => {
    playTick();
    store.set({ popModal: store.get().popModal === 'timeline' ? null : 'timeline' });
  });
  document.getElementById('v2PopMediaBtn')?.addEventListener('click', () => {
    playTick();
    if (store.get().popModal === 'media') store.set({ popModal: null });
    else openMediaVault(store);
  });
  document.getElementById('v2PopCloseBtn')?.addEventListener('click', () => {
    playTick();
    store.set({ popModal: null });
  });
  document.getElementById('v2PopModal')?.addEventListener('click', (e) => {
    if (e.target?.id === 'v2PopModal') store.set({ popModal: null });
  });
  if (state.popModal === 'laws') {
    bindLawsEvents({ store, api: NoirApi });
  } else if (state.popModal === 'media') {
    bindMediaVaultEvents({ store, api: NoirApi });
  } else if (state.popModal === 'timeline') {
    document.getElementById('v2OpenStoryTrack')?.addEventListener('click', () => selectStorySubtab('passages'));
    bindTimelineEvents({
      store, api: NoirApi, onRefreshTimeline: refreshTimeline, onView: changeView, onOpenDraft: openSavedDraft,
      onSelectEpisode: selectEpisode,
    });
  }

  document.getElementById('v2DrawerCookBtn')?.addEventListener('click', () => {
    store.setQuiet({ engineDrawerOpen: false });
    runCookPipeline();
  });

  document.getElementById('v2ComposeSplitToggle')?.addEventListener('click', () => {
    playTick();
    store.set({ composeSplitGraph: !store.get().composeSplitGraph });
  });

  document.querySelectorAll('[data-home-route]').forEach((btn) => {
    btn.addEventListener('click', () => {
      playSelect();
      changeView(btn.dataset.homeRoute);
    });
  });

  const applyL2BlockEdit = (blockId, nextText) => {
    const cur = store.get();
    const nb = cur.episodeState?.notebook;
    if (!nb) return;
    const list = (cur.draftBlocks || nb.blocks || []).map((b) => (b.id === blockId ? { ...b, text: nextText } : b));
    store.setQuiet({ draftBlocks: list, dirty: true });
    const ta = document.querySelector(`[data-block-text="${CSS.escape(blockId)}"]`);
    if (ta && ta.value !== nextText) {
      ta.value = nextText;
      ta.style.height = 'auto';
      ta.style.height = `${Math.max(26, ta.scrollHeight)}px`;
    }
    const saveBtn = document.getElementById('v2SaveBtn');
    if (saveBtn) {
      saveBtn.disabled = false;
      saveBtn.textContent = 'Save changes';
    }
  };

  if (state.view === 'compose' && state.composeSplitGraph) {
    bindStoryGraphCanvas({
      state,
      store,
      compact: true,
      onLiveL2BlockEdit: applyL2BlockEdit,
      onJumpToBlock: (blockId) => {
        if (blockId) {
          const card = document.querySelector(`.v2-block-card[data-block-id="${CSS.escape(blockId)}"]`);
          card?.scrollIntoView({ behavior: 'smooth', block: 'center' });
        }
      },
    });
  }

  bindActStructure(store, NoirApi);
  if (document.querySelector('.v2-compose-wrap')) bindComposeEvents({
    store, api: NoirApi, onReload: () => selectEpisode(store.get().episodeId), onPrepare: runCookPipeline,
    onOpenStoryBeat: (beatId) => {
      store.set({ composeSplitGraph: true, storyBeatFocus: beatId });
      requestAnimationFrame(() => {
        document.querySelector(`.sg-node[data-sg-beat="${CSS.escape(beatId)}"]`)?.scrollIntoView({ behavior: 'smooth', block: 'center' });
      });
    },
    onOpenCharacterGraph: (characterId, formId) => {
      store.setQuiet({ graphSubtab: 'switchyard', graphSelection: { type: 'character', characterId, formId: formId || null } });
      changeView('graph');
    },
    onLiveBlocksChange: () => {
      const liveState = store.get();
      if (liveState.view !== 'compose' || !liveState.composeSplitGraph) return;
      const host = document.querySelector('.v2-compose-split-right');
      if (!host) return;
      host.innerHTML = renderStoryGraphCanvas(liveState, { compact: true });
      bindStoryGraphCanvas({
        state: liveState,
        store,
        compact: true,
        onLiveL2BlockEdit: applyL2BlockEdit,
        onJumpToBlock: (blockId) => {
          if (blockId) {
            const card = document.querySelector(`.v2-block-card[data-block-id="${CSS.escape(blockId)}"]`);
            card?.scrollIntoView({ behavior: 'smooth', block: 'center' });
          }
        },
      });
    },
  });

  bindDirectorInspector({
    store,
    api: NoirApi,
    onAfterRun: async (result) => {
      await selectEpisode(result.episode);
      if (result.notice) {
        store.setQuiet({ notice: { text: result.notice, tone: result.accepted ? 'ok' : 'warn' } });
        updateNoticeDom({ text: result.notice, tone: result.accepted ? 'ok' : 'warn' });
      }
    },
  });

  if (document.getElementById('v2IntakeForm')) {
    bindIntake({ store, api: NoirApi, onCreated: async (result) => {
      const timeline = await NoirApi.getTimeline();
      store.setQuiet({ timeline });
      if (!await selectEpisode(result.episode)) return false;
      if (result.launchResult?.notice) {
        store.setQuiet({ notice: { text: result.launchResult.notice, tone: result.launchResult.accepted ? 'ok' : 'warn' } });
      }
      changeView('compose');
      return true;
    }});
  } else if (state.view === 'story') {
    document.querySelectorAll('[data-story-subtab]').forEach((btn) => btn.addEventListener('click', () => {
      playTick();
      selectStorySubtab(btn.dataset.storySubtab);
    }));
    const sub = state.storySubtab || 'graph';
    if (sub === 'laws') {
      bindLawsEvents({ store, api: NoirApi });
    } else if (sub === 'passages') {
      bindStoryTimeline({ state, onEpisodeCards: () => changeView('timeline'), onPick: pickStoryBeat,
        onClip: (storyClip) => store.set({ storyClip }), onOpen: openStoryPassage,
        onReload: (fragment) => loadStoryTimeline(fragment), onDraft: openSavedDraft });
    } else if (sub === 'rhythm') {
      bindBeatEvents({
        store,
        api: NoirApi,
        onJumpToPassage: (id) => {
          const b=store.get().beatMap?.beats.find(p=>p.id===id);
          if (!b) return;
          changeView('compose');
          let offset = 0;
          for (const block of store.get().episodeState?.notebook?.blocks || []) {
            const next=offset+[...block.text].length;
            if (offset <= b.start && b.start < next) {
              document.querySelector(`[data-block-id="${CSS.escape(block.id)}"]`)?.scrollIntoView({block:'center',inline:'nearest'});
              break;
            }
            offset=next;
          }
        },
        onReloadBeatData: async () => {
          const s = store.get();
          const ep = s.episodeState?.episode;
          if (!ep) return;
          const data = await loadBeatData(ep.id, ep.head, s.beat, s.viewpoint);
          store.set({ ...data, notice: { text: 'Beat map reloaded.', tone: 'ok' } });
        },
        onOpenDraft: openSavedDraft,
      });
    } else if (sub === 'processing') {
      document.getElementById('v2ReloadProcessing')?.addEventListener('click', loadProcessing);
    } else {
      bindStoryGraphCanvas({
        state,
        store,
        onLiveL2BlockEdit: applyL2BlockEdit,
        onJumpToBlock: (blockId) => {
          changeView('compose');
          if (blockId) {
            requestAnimationFrame(() => {
              document.querySelector(`.v2-block-card[data-block-id="${CSS.escape(blockId)}"]`)?.scrollIntoView({ behavior: 'smooth', block: 'center' });
            });
          }
        },
      });
    }
  } else if (state.view === 'timeline') {
    document.getElementById('v2OpenStoryTrack')?.addEventListener('click', () => selectStorySubtab('passages'));
      bindTimelineEvents({
        store,
        api: NoirApi,
        onSelectEpisode: selectEpisode,
        onRefreshTimeline: refreshTimeline,
        onView: changeView,
        onOpenDraft: openSavedDraft,
      });
  } else if (state.view === 'graph') {
    bindGraphEvents({
      store,
      api: NoirApi,
      onSelectEpisode: selectEpisode,
      onNotice: (notice) => {
        store.setQuiet({ notice });
        updateNoticeDom(notice);
      },
      onJumpToComposeBlock: (blockId) => {
        const cur = store.get();
        const inSplitGraph = cur.view === 'graph' && (cur.triSplit || cur.graphSplit);
        if (!inSplitGraph) {
          const url = new URL(window.location.href);
          url.searchParams.set('view', 'compose');
          window.history.replaceState({}, '', url);
          store.set({ view: 'compose' });
        }
        if (blockId) {
          requestAnimationFrame(() => {
            const card = document.querySelector(`.v2-block-card[data-block-id="${CSS.escape(blockId)}"]`);
            card?.scrollIntoView({ behavior: 'smooth', block: 'center' });
          });
        }
      },
    });
  } else if (state.view === 'prose') {
    bindProseEvents({
      store,
      api: NoirApi,
      onSelectEpisode: selectEpisode,
      onOpenDraft: openSavedDraft,
      onRefreshBookStatus: async (backend, provider) => {
        const bookStatus = await NoirApi.getBookStatus(backend, provider).catch(() => null);
        if (bookStatus) store.set({ bookStatus });
      },
    });
  } else if (state.view === 'laws') {
    bindLawsEvents({
      store,
      api: NoirApi,
      onSelectEpisode: selectEpisode,
    });
  } else if (state.view === 'lab') {
    bindAnalysisLabEvents({ store, changeView, onRunMainCooker: () => runCookPipeline() });
  }
}

const appRoot = document.getElementById('v2App');
async function changeSceneInputs(action, fields) {
  const state = store.get();
  const plan = currentScenePlan(state);
  if (!plan || state.dirty || state.busy) return;
  const episodeId = state.episodeId;
  store.set({ busy: true });
  try {
    await NoirApi.episodeCommand({
      action, ...plan.scope, timeline_revision: plan.timeline_revision, scene_plan: plan.id, ...await fields(),
    });
    const formGraph = await NoirApi.getFormGraph(episodeId);
    if (store.get().episodeId === episodeId) {
      store.set({ formGraph, busy: false, selectionRange: null, selectionPreview: null,
        notice: { text: 'Saved scene inputs. The Turn Ledger shows the current plan.', tone: 'ok' } });
    }
  } catch (err) {
    if (store.get().episodeId === episodeId) store.set({ busy: false, notice: { text: err.message, tone: 'err' } });
  }
}

appRoot.addEventListener('change', async event => {
  if (event.target.matches('[data-attach-scene-inputs]')) {
    const file = event.target.files[0];
    if (!file) return;
    const preparation = store.get().preparation?.id;
    await changeSceneInputs('scene.plan.inputs.attach', async () => {
      if (file.size > 90_000) throw new Error('Choose a scene input JSON package under 90 KB.');
      return { preparation, package: JSON.parse(await file.text()) };
    });
    return;
  }
  if (event.target.matches('[data-scene-plan-beat]')) {
    const bridgeBeatId = event.target.value;
    store.set({ bridgeBeatId });
    appRoot.querySelector('[data-scene-plan-beat]')?.focus({ preventScroll: true });
  }
});
appRoot.addEventListener('click', async event => {
  const timing = event.target.closest('[data-scene-timing-pin]');
  if (timing) {
    await changeSceneInputs('scene.plan.inputs.timing', () => ({
      pin: timing.dataset.sceneTimingPin, enabled: timing.dataset.enable === 'true',
    }));
    return;
  }
  if (event.target.closest('[data-reload-scene-plan]') && !store.get().dirty) {
    await selectEpisode(store.get().episodeId);
    return;
  }
  const mvBtn = event.target.closest('[data-open-media-vault]');
  if (mvBtn) {
    playTick();
    const target = mvBtn.dataset.mvChar && mvBtn.dataset.mvForm
      ? { character: mvBtn.dataset.mvChar, form: mvBtn.dataset.mvForm }
      : mvBtn.dataset.mvBeat
        ? { beat: mvBtn.dataset.mvBeat }
        : mvBtn.dataset.mvScene
          ? { scene: mvBtn.dataset.mvScene }
          : null;
    openMediaVault(store, target, mvBtn.dataset.mvAsset);
    return;
  }
  if (!event.target.closest('[data-use-scene-plan]')) return;
  const state = store.get();
  const plan = currentScenePlan(state);
  if (!plan || state.dirty || state.busy) return;
  const { start, end } = plan.target;
  store.setQuiet({ activeDraftId: null, selectionRange: { start, end, scenePlan: plan.id } });
  changeView('prose');
});

window.addEventListener('resize', () => {
  if (store.get().view === 'timeline') {
    requestAnimationFrame(() => drawTimelineWires(store.get().timeline));
  }
});

document.addEventListener('keydown', (e) => {
  if (e.key === 'Escape' && !e.defaultPrevented && !document.querySelector('.v2-mask-popover, #v2CookOverlay')) {
    const toggle = document.querySelector('#v2NavigationToggle[aria-expanded="true"], #v2InspectorToggle[aria-expanded="true"]');
    if (toggle?.getClientRects().length) {
      e.preventDefault();
      setPanels(false, false);
      toggle.focus({ preventScroll: true });
    }
  }
  if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 's') {
    if (store.get().dirty) {
      e.preventDefault();
      saveDocumentChanges();
    }
  }
  if (isEditableTarget(e.target) || !(e.ctrlKey || e.metaKey) || e.altKey) return;
  const key = e.key.toLowerCase();
  if (key !== 'z' && key !== 'y') return;
  const redo = key === 'y' || e.shiftKey;
  const timelineActive = store.get().view === 'timeline' || store.get().popModal === 'timeline';
  const timelineButton = timelineActive
    ? document.getElementById(redo ? 'v2TlRedoBtn' : 'v2TlUndoBtn')
    : null;
  const standardButton = document.getElementById(redo ? 'v2RedoBtn' : 'v2UndoBtn');
  const projectHistory = store.get().projectHistory?.revision;
  const button = !projectHistory && timelineButton && !timelineButton.disabled ? timelineButton : standardButton;
  if (!button || button.disabled) return;
  e.preventDefault();
  button.click();
});

async function init() {
  window.addEventListener('keydown', (e) => {
    if (e.altKey && (e.key === 'w' || e.key === 'W')) {
      e.preventDefault();
      store.set({ popModal: store.get().popModal === 'laws' ? null : 'laws' });
    } else if (e.altKey && (e.key === 'm' || e.key === 'M')) {
      e.preventDefault();
      store.set({ popModal: store.get().popModal === 'memory' ? null : 'memory' });
    } else if (e.altKey && (e.key === 't' || e.key === 'T')) {
      e.preventDefault();
      store.set({ popModal: store.get().popModal === 'timeline' ? null : 'timeline' });
    } else if (e.altKey && (e.key === 'u' || e.key === 'U')) {
      e.preventDefault();
      if (store.get().popModal === 'media') store.set({ popModal: null });
      else openMediaVault(store);
    } else if (e.key === 'Escape' && store.get().timelineImpact) {
      e.preventDefault();
      store.set({ timelineImpact: null });
    } else if (e.key === 'Escape' && store.get().popModal) {
      store.set({ popModal: null });
    }
  });
  store.subscribe(render);
  window.addEventListener('noir:history-changed', refreshProjectHistory);
  window.addEventListener('focus', refreshProjectHistory);
  void refreshProjectHistory();
  store.on('media:pinned', () => void loadStoryTimeline());
  store.on('story:beat-selected', (passage) => void refreshActStructure(store, NoirApi, { passage }));
  bindDesktopHost(store);
  render(store.get());
  try {
    const [timeline, listing] = await Promise.all([NoirApi.getTimeline(), NoirApi.getWriters().catch(() => null)]);
    const list = timeline.cards || timeline.episodes || [];
    const initialId = store.get().episodeId || list[0]?.id || '';
    store.set({ timeline, episodeId: initialId, writers: listing?.writers });
    if (initialId && await selectEpisode(initialId)) {
      await openDesktopPassage(store, composeText, revealStoryPassage);
    }
    Promise.all([
      NoirApi.getBookPolicy().catch(() => null),
      NoirApi.worldLawsAction({action:'open'}).catch(() => null),
      NoirApi.getSampleProjects().catch(() => null),
    ])
      .then(([bookPolicy, worldLaws, sampleRes]) => {
        const extras = {
          bookPolicy,
          worldLaws: store.get().worldLaws || worldLaws,
          ...(sampleRes?.projects ? { sampleProjects: sampleRes.projects } : {}),
        };
        if (['prose','laws','compose','graph','timeline'].includes(store.get().view)) store.set(extras);
        else store.setQuiet(extras);
      });
  } catch (err) {
    store.set({ notice: { text: `Failed to load timeline: ${err.message}`, tone: 'err' } });
  }
}

init();
