/* Noir Fiction Studio v2 — Central Observable State Store */

export function createStore(initialState) {
  let state = { ...initialState };
  const listeners = new Set();
  const channels = new Map();

  return {
    get() {
      return state;
    },
    set(patch) {
      state = { ...state, ...patch };
      for (const listener of listeners) {
        listener(state);
      }
    },
    setQuiet(patch) {
      state = { ...state, ...patch };
    },
    subscribe(listener) {
      listeners.add(listener);
      return () => listeners.delete(listener);
    },
    emit(eventName, detail = {}) {
      const set = channels.get(eventName);
      if (!set) return;
      for (const handler of set) {
        handler(detail, state);
      }
    },
    on(eventName, handler) {
      if (!channels.has(eventName)) channels.set(eventName, new Set());
      const set = channels.get(eventName);
      set.add(handler);
      return () => set.delete(handler);
    },
  };
}

const VALID_THEMES = new Set(['noir-v4', 'racing', 'classic']);

export function resolveInitialTheme() {
  const urlTheme = new URLSearchParams(location.search).get('theme');
  if (VALID_THEMES.has(urlTheme)) return urlTheme;
  try {
    const saved = localStorage.getItem('noir-theme');
    if (VALID_THEMES.has(saved)) return saved;
  } catch (_) {}
  return 'racing';
}

export function resolveInitialView() {
  const query = new URLSearchParams(location.search);
  const urlView = query.get('view');
  if (urlView === 'beat' || (urlView === 'timeline' && query.get('track') === 'story')) return 'story';
  const valid = new Set(['start', 'lab', 'prep', 'compose', 'story', 'timeline', 'graph', 'beat', 'prose', 'laws']);
  return valid.has(urlView) ? urlView : 'compose';
}
