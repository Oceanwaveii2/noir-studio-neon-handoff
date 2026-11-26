/* Noir Fiction Studio v2 — Global Atomic Undo/Redo & Soft-Delete Trash Manager */

export function isEditableTarget(target) {
  if (!target) return false;
  const tag = String(target.tagName || '').toLowerCase();
  return tag === 'input' || tag === 'textarea' || tag === 'select' || Boolean(target.isContentEditable);
}

export function createGlobalHistory(store) {
  const undoStack = [];
  const redoStack = [];
  const trash = [];
  const MAX_DEPTH = 60;

  function syncCounts() {
    store?.setQuiet?.({
      globalUndoCount: undoStack.length,
      globalRedoCount: redoStack.length,
      globalTrashCount: trash.length,
    });
    store?.emit?.('history:changed', {
      undoCount: undoStack.length,
      redoCount: redoStack.length,
      trashCount: trash.length,
    });
  }

  function cloneValue(val) {
    return typeof structuredClone === 'function' ? structuredClone(val) : JSON.parse(JSON.stringify(val));
  }

  function commit(label, getSnap, applySnap, mutateFn) {
    const prev = cloneValue(getSnap());
    mutateFn();
    const next = cloneValue(getSnap());
    undoStack.push({ label, prev, next, applySnap });
    if (undoStack.length > MAX_DEPTH) undoStack.shift();
    redoStack.length = 0;
    syncCounts();
  }

  function softDelete(label, kind, getSnap, applySnap, removeFn, restoreFn) {
    const id = `tr_${Date.now()}_${Math.random().toString(16).slice(2, 6)}`;
    const deletedAt = new Date().toLocaleTimeString();
    commit(label, getSnap, applySnap, removeFn);
    trash.unshift({ id, label, kind, deletedAt, restoreFn });
    syncCounts();
    return id;
  }

  function undo() {
    if (!undoStack.length) return null;
    const entry = undoStack.pop();
    entry.applySnap(cloneValue(entry.prev));
    redoStack.push(entry);
    syncCounts();
    return entry.label;
  }

  function redo() {
    if (!redoStack.length) return null;
    const entry = redoStack.pop();
    entry.applySnap(cloneValue(entry.next));
    undoStack.push(entry);
    syncCounts();
    return entry.label;
  }

  function restoreTrash(id) {
    const idx = trash.findIndex((t) => t.id === id);
    if (idx < 0) return false;
    const [item] = trash.splice(idx, 1);
    try {
      item.restoreFn?.();
    } finally {
      syncCounts();
    }
    return item.label;
  }

  return {
    commit,
    softDelete,
    undo,
    redo,
    restoreTrash,
    getTrash: () => [...trash],
    canUndo: () => undoStack.length > 0,
    canRedo: () => redoStack.length > 0,
    peekUndoLabel: () => (undoStack.length ? undoStack[undoStack.length - 1].label : ''),
    peekRedoLabel: () => (redoStack.length ? redoStack[redoStack.length - 1].label : ''),
  };
}
