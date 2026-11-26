/* Noir Fiction Studio v2 — G3 Graph Controller Adapter (Layer 2: Bridges GraphKernel <-> Store <-> API; ZERO Canvas2D) */

import {
  createGraphKernel,
  toBackendGraph,
  getOperatorSpec,
  computeDirtySet,
  OPERATOR_SPECS,
  PORT_TYPES,
  canConnectPorts,
} from './graph_engine.js';

export function createGraphController({ store, api, onSelectEpisode, onNotify, onStageChange, onInspectorChange }) {
  let kernel = null;
  let sessionKey = '';
  let revisionCounter = 0;
  let savedRevisionCounter = 0;
  const viewSubscribers = new Set();

  function getRawBackendGraph(state) {
    return {
      nodes: state?.graphDraft?.nodes ?? state?.episodeState?.nodes ?? [],
      edges: state?.graphDraft?.edges ?? state?.episodeState?.connections ?? [],
      networkBoxes: state?.graphDraft?.networkBoxes ?? state?.episodeState?.networkBoxes ?? [],
    };
  }

  function isDirty() {
    return revisionCounter !== savedRevisionCounter || Boolean(store.get()?.graphDraft);
  }

  function buildViewModel() {
    const s = store.get() || {};
    return {
      snapshot: kernel ? kernel.getSnapshot() : { subnetId: null, nodes: [], edges: [], networkBoxes: [] },
      selectedNodeId: s.graphSelectedNodeId || '',
      selectedEdgeId: s.graphSelectedEdgeId || '',
      dirty: isDirty(),
      canUndo: kernel ? kernel.canUndo() : false,
      canRedo: kernel ? kernel.canRedo() : false,
    };
  }

  function emitView() {
    const vm = buildViewModel();
    for (const fn of viewSubscribers) {
      fn(vm);
    }
  }

  function syncWithState(state) {
    const ep = state?.episodeState?.episode;
    const epId = ep?.id || '';
    const epHead = ep?.head ?? 0;
    const nextKey = `${epId}:${epHead}`;
    const rawGraph = getRawBackendGraph(state);

    const needsReset =
      !kernel ||
      sessionKey !== nextKey ||
      (state?.graphDraft === null && revisionCounter !== savedRevisionCounter);

    if (needsReset) {
      sessionKey = nextKey;
      kernel = createGraphKernel({
        ...rawGraph,
        nodes: rawGraph.nodes.map(node => ({ ...node, eval: node.eval?.status ? node.eval : { status: 'dirty' } })),
      });
      revisionCounter = state?.graphDraft ? 1 : 0;
      savedRevisionCounter = 0;
      emitView();
    }
    return buildViewModel();
  }

  function selectNode(nodeId = '') {
    store.setQuiet({
      graphSelectedNodeId: nodeId || '',
      graphSelectedEdgeId: '',
    });
    emitView();
    onInspectorChange?.(buildViewModel());
  }

  function selectEdge(edgeId = '') {
    store.setQuiet({
      graphSelectedNodeId: '',
      graphSelectedEdgeId: edgeId || '',
    });
    emitView();
    onInspectorChange?.(buildViewModel());
  }

  function dispatch(action, { noticeText = '', noticeTone = 'warn', refreshInspector = true, refreshStage = false } = {}) {
    if (!kernel) syncWithState(store.get());
    const prevNodeCount = kernel.getSnapshot().nodes.length;
    const res = kernel.dispatch(action);
    if (!res.ok) {
      onNotify?.(res.error || 'Graph action failed.', 'err');
      return res;
    }

    if (action.type === 'UNDO') {
      revisionCounter = Math.max(0, revisionCounter - 1);
    } else if (action.type === 'REDO') {
      revisionCounter += 1;
    } else if (action.type !== 'SET_COOK_STATE' && action.type !== 'ENTER_SUBNET') {
      revisionCounter += 1;
    }

    const snap = res.snapshot || kernel.getSnapshot();
    const isNowDirty = revisionCounter !== savedRevisionCounter;
    const patch = {
      graphDraft: isNowDirty ? toBackendGraph(snap) : null,
    };

    if (action.type === 'ADD_NODE' && res.nodeId) {
      patch.graphSelectedNodeId = res.nodeId;
      patch.graphSelectedEdgeId = '';
    } else if (action.type === 'REMOVE_SELECTION') {
      const stillValid = snap.nodes.some((n) => n.id === store.get()?.graphSelectedNodeId);
      if (!stillValid) {
        patch.graphSelectedNodeId = snap.nodes[0]?.id || '';
      }
      patch.graphSelectedEdgeId = '';
    }

    const crossedEmptyBoundary =
      (prevNodeCount === 0 && snap.nodes.length > 0) ||
      (prevNodeCount > 0 && snap.nodes.length === 0);

    if (refreshStage || crossedEmptyBoundary) {
      store.set({
        ...patch,
        ...(noticeText ? { notice: { text: noticeText, tone: noticeTone } } : {}),
      });
      return res;
    }

    store.setQuiet(patch);
    emitView();
    if (refreshInspector) {
      onInspectorChange?.(buildViewModel());
    }
    if (noticeText) {
      onNotify?.(noticeText, noticeTone);
    }
    return res;
  }

  async function saveGraph() {
    const s = store.get();
    const ep = s?.episodeState?.episode;
    if (!ep || !kernel) return { ok: false, error: 'No active episode.' };
    const graphPayload = toBackendGraph(kernel.getSnapshot());
    store.setQuiet({ busy: true });
    try {
      await api.timelineAction({
        action: 'save',
        id: ep.id,
        expected_revision: ep.head,
        graph: graphPayload,
      });
      savedRevisionCounter = revisionCounter;
      store.setQuiet({ graphDraft: null });
      await onSelectEpisode(ep.id);
      store.set({ busy: false, notice: { text: `Saved story graph for ${ep.title}.`, tone: 'ok' } });
      return { ok: true };
    } catch (err) {
      store.setQuiet({ busy: false });
      onNotify?.(err.message, 'err');
      return { ok: false, error: err.message };
    }
  }

  async function cookScoped({ mode = 'selected', nodeId = '' } = {}) {
    const s = store.get();
    const ep = s?.episodeState?.episode;
    if (!ep || !kernel) return { ok: false, error: 'No active episode.' };
    const targetId = nodeId || s.graphSelectedNodeId || null;
    const cookingKernel = kernel;
    const graphInput = JSON.stringify(toBackendGraph(kernel.getSnapshot()));
    try {
      if (isDirty()) throw new Error('Save the graph changes before checking its structure.');
      onNotify?.('Checking saved graph structure…', 'warn');
      const result = await api.episodeCommand({
        action: 'graph.cook', episode: ep.id, revision: ep.head, target: targetId, mode,
      });
      const receipt = result.receipt;
      if (result.status !== 'CHECKED' || receipt?.kind !== 'graph-structure' || !receipt.id ||
          receipt.episode !== ep.id || receipt.revision !== ep.head || receipt.target !== targetId ||
          receipt.mode !== mode || !Array.isArray(receipt.checked_nodes)) {
        throw new Error('The server did not return a matching graph receipt.');
      }
      if (kernel !== cookingKernel || isDirty() || JSON.stringify(toBackendGraph(kernel.getSnapshot())) !== graphInput) {
        throw new Error('The graph changed during Cook. Check the current revision again.');
      }
      const updates = Object.fromEntries(receipt.checked_nodes.map(id =>
        [id, { status: 'clean', dirtyReason: null }]));
      kernel.dispatch({ type: 'SET_COOK_STATE', updates });
      emitView();
      onInspectorChange?.(buildViewModel());
      onNotify?.(`Graph structure checked for ${receipt.checked_nodes.length} node(s).`, 'ok');
      return { ok: true, receipt, reused: result.reused };
    } catch (err) {
      onNotify?.(err.message || 'Cook failed.', 'err');
      return { ok: false, error: err.message };
    }
  }

  return {
    syncWithState,
    getViewModel: buildViewModel,
    getSnapshot: () => (kernel ? kernel.getSnapshot() : { subnetId: null, nodes: [], edges: [], networkBoxes: [] }),
    canUndo: () => Boolean(kernel?.canUndo()),
    canRedo: () => Boolean(kernel?.canRedo()),
    isDirty,
    selectNode,
    selectEdge,
    dispatch,
    saveGraph,
    cookScoped,
    computeDirtySet: (targetId = null) => (kernel ? computeDirtySet(kernel.getSnapshot(), targetId) : []),
    getOperatorSpec,
    OPERATOR_SPECS,
    PORT_TYPES,
    canConnectPorts: (args) => (kernel ? canConnectPorts(kernel.getSnapshot(), args) : { ok: false }),
    subscribe(fn) {
      viewSubscribers.add(fn);
      return () => viewSubscribers.delete(fn);
    },
    destroy() {
      viewSubscribers.clear();
    },
  };
}
