const desktop = new URLSearchParams(location.search).get('host') === 'desktop';
if (desktop) document.body.dataset.noirHost = 'desktop';

export function bindDesktopHost(store) {
  if (!desktop) return;
  const state = () => {
    const current = store.get();
    const saved = current.episodeState?.episode;
    const ready = Boolean(saved && saved.id === current.episodeId);
    return {
      episode: ready ? saved.id : null,
      branch: ready ? saved.branch : null,
      revision: ready ? saved.head : null,
      view: current.view,
      dirty: Boolean(current.dirty || current.graphDraft),
      busy: Boolean(current.busy),
      dialog: Boolean(document.querySelector('dialog[open]')),
    };
  };
  window.noirDesktopState = state;
  if (!window.chrome?.webview) return;
  let last;
  store.subscribe(() => {
    const snapshot = state();
    const key = JSON.stringify(snapshot);
    if (key === last) return;
    last = key;
    window.chrome.webview.postMessage({ type: 'noir-workspace-state', ...snapshot });
  });
}

export async function openDesktopPassage(store, composeText, reveal) {
  if (!desktop) return;
  const url = new URL(location.href);
  const read = name => url.searchParams.get('passage-' + name);
  if (read('digest') === null) return;
  const parse = name => /^[0-9]+$/.test(read(name) || '') ? Number(read(name)) : -1;
  const start = parse('start'), end = parse('end'), revision = parse('revision');
  const expected = read('digest'), source = read('source'), branch = read('branch');
  ['start', 'end', 'revision', 'digest', 'source', 'branch'].forEach(name => url.searchParams.delete('passage-' + name));
  history.replaceState(null, '', url);
  const state = store.get();
  const book = state.episodeState?.notebook;
  const episode = state.episodeState?.episode;
  const script = state.episodeState?.script_text;
  const valid = state.view === 'compose' && episode?.head === revision && episode?.branch === branch &&
    book?.timeline_revision === revision && !book.stale && typeof script === 'string' &&
    episode.script_sha256 === source && composeText(book.blocks) === script && start >= 0 && end > start;
  if (valid) {
    const points = [...script];
    if (end <= points.length) {
      const text = points.slice(start, end).join('');
      const bytes = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(text));
      const digest = Array.from(new Uint8Array(bytes), value => value.toString(16).padStart(2, '0')).join('');
      const latest = store.get();
      if (digest === expected && latest.episodeState === state.episodeState && !latest.dirty &&
          reveal(book.blocks, { start, end, text })) return;
    }
  }
  store.set({ notice: { text: 'The saved passage no longer matches this notebook. Reopen it from Story Beats.', tone: 'warn' } });
}
