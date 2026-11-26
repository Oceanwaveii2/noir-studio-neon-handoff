/* Noir Fiction Studio v2 — Central Observable State Store */

export function createStore(initialState) {
  let state = { ...initialState };
  const listeners = new Set();

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
  };
}

export function resolveInitialTheme() {
  const urlTheme = new URLSearchParams(location.search).get('theme');
  if (urlTheme === 'classic' || urlTheme === 'racing') return urlTheme;
  try {
    const saved = localStorage.getItem('noir-theme');
    if (saved === 'classic' || saved === 'racing') return saved;
  } catch (_) {}
  return 'racing';
}

export function resolveInitialView() {
  const urlView = new URLSearchParams(location.search).get('view');
  const valid = new Set(['start', 'compose', 'timeline', 'graph', 'beat', 'prose', 'laws']);
  return valid.has(urlView) ? urlView : 'compose';
}
