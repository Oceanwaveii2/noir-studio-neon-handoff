/**
 * NOIR Studio WebAudio Multi-Bus, Multi-Stem & Interactive SFX Engine
 * Supports:
 * - 4 Audio Focus Modes (overdrive | balanced | focus | muted)
 * - Independent Master / BGM / SFX volume sliders persisted in localStorage
 * - Track A 4-stem vertical remixing (Writer Focus attenuates drums & lead, typing auto-ducks)
 * - Bar-quantized Track D -> A -> B -> C state switching (125 BPM)
 * - Sidechain ducking (stingers -4 dB, comms -2 dB, media clip playback ducking)
 * - Runtime ±3% pitch & ±1.5 dB gain micro-jitter, cooldowns, max-8 polyphony, & WebAudio fallback
 */

import { NoirApi } from './api.js';

const SOUND_KEY = 'noir_v2_sound_enabled';
const MUSIC_KEY = 'noir_v2_music_enabled';
const FOCUS_KEY = 'noir_v2_audio_focus';
const VOL_MASTER_KEY = 'noir_v2_vol_master';
const VOL_BGM_KEY = 'noir_v2_vol_bgm';
const VOL_SFX_KEY = 'noir_v2_vol_sfx';

const FOCUS_MODES = ['overdrive', 'balanced', 'focus', 'muted'];
const MAX_POLYPHONY = 8;

let _ctx = null;
let _buses = null;
let _manifest = null;
let _manifestPromise = null;
const _buffers = new Map();
const _lastPlayed = new Map();
const _rrIndex = new Map();
let _activeVoices = 0;

let _currentZone = 'nontrack';
let _musicNodes = [];
let _musicEpoch = 0;
let _musicStartTime = 0;
let _stemGains = { drums: null, bass: null, keys_chords: null, lead_sparkle: null };
let _driftLoopNodes = null;
let _typingTimer = null;
let _mediaHooked = false;
let _mediaPlayingCount = 0;

function readBool(key, fallback) {
  try {
    const raw = localStorage.getItem(key);
    if (raw === null) return fallback;
    return raw === '1' || raw === 'true';
  } catch {
    return fallback;
  }
}

function writeBool(key, val) {
  try { localStorage.setItem(key, val ? '1' : '0'); } catch {}
}

function readFloat(key, fallback) {
  try {
    const raw = localStorage.getItem(key);
    if (raw === null) return fallback;
    const n = Number(raw);
    return Number.isFinite(n) ? Math.max(0, Math.min(1, n)) : fallback;
  } catch {
    return fallback;
  }
}

export function getVolumeSettings() {
  return {
    master: readFloat(VOL_MASTER_KEY, 0.9),
    bgm: readFloat(VOL_BGM_KEY, 0.8),
    sfx: readFloat(VOL_SFX_KEY, 0.9),
  };
}

export function setVolumeSetting(bus, val) {
  const safe = Math.max(0, Math.min(1, Number(val)));
  const key = bus === 'master' ? VOL_MASTER_KEY : bus === 'bgm' ? VOL_BGM_KEY : VOL_SFX_KEY;
  try { localStorage.setItem(key, String(safe)); } catch {}
  applyFocusGains();
  return getVolumeSettings();
}

export function getAudioFocusMode() {
  try {
    const raw = localStorage.getItem(FOCUS_KEY);
    if (raw && FOCUS_MODES.includes(raw)) return raw;
  } catch {}
  if (!readBool(SOUND_KEY, true) && !readBool(MUSIC_KEY, false)) return 'muted';
  return 'balanced';
}

export function setAudioFocusMode(mode) {
  const next = FOCUS_MODES.includes(mode) ? mode : 'balanced';
  try { localStorage.setItem(FOCUS_KEY, next); } catch {}
  if (next === 'muted') {
    writeBool(SOUND_KEY, false);
    writeBool(MUSIC_KEY, false);
  } else {
    writeBool(SOUND_KEY, true);
    if (next === 'overdrive') writeBool(MUSIC_KEY, true);
  }
  applyFocusGains();
  return next;
}

export function cycleAudioFocusMode() {
  const cur = getAudioFocusMode();
  return setAudioFocusMode(FOCUS_MODES[(FOCUS_MODES.indexOf(cur) + 1) % FOCUS_MODES.length]);
}

export function isSoundEnabled() {
  return getAudioFocusMode() !== 'muted' && readBool(SOUND_KEY, true);
}

export function setSoundEnabled(enabled) {
  writeBool(SOUND_KEY, Boolean(enabled));
  if (!enabled && !isMusicEnabled()) {
    try { localStorage.setItem(FOCUS_KEY, 'muted'); } catch {}
  } else if (enabled && getAudioFocusMode() === 'muted') {
    try { localStorage.setItem(FOCUS_KEY, 'balanced'); } catch {}
  }
  applyFocusGains();
}

export function isMusicEnabled() {
  return getAudioFocusMode() !== 'muted' && readBool(MUSIC_KEY, false);
}

export function setMusicEnabled(enabled) {
  const on = Boolean(enabled);
  writeBool(MUSIC_KEY, on);
  if (on && getAudioFocusMode() === 'muted') {
    try { localStorage.setItem(FOCUS_KEY, 'balanced'); } catch {}
  }
  if (on) startMusicZone(_currentZone);
  else stopMusic();
  applyFocusGains();
}

function hookMediaDucking() {
  if (_mediaHooked || typeof document === 'undefined') return;
  _mediaHooked = true;
  document.addEventListener('play', (e) => {
    if (e.target && (e.target.tagName === 'VIDEO' || e.target.tagName === 'AUDIO')) {
      _mediaPlayingCount += 1;
      applyFocusGains();
    }
  }, true);
  const onStop = (e) => {
    if (e.target && (e.target.tagName === 'VIDEO' || e.target.tagName === 'AUDIO')) {
      _mediaPlayingCount = Math.max(0, _mediaPlayingCount - 1);
      applyFocusGains();
    }
  };
  document.addEventListener('pause', onStop, true);
  document.addEventListener('ended', onStop, true);
}

function ensureContext() {
  hookMediaDucking();
  if (_ctx) {
    if (_ctx.state === 'suspended') _ctx.resume().catch(() => {});
    return _ctx;
  }
  const AC = window.AudioContext || window.webkitAudioContext;
  if (!AC) return null;
  _ctx = new AC();

  const master = _ctx.createGain();
  master.connect(_ctx.destination);

  const music = _ctx.createGain();
  const musicFilter = _ctx.createBiquadFilter();
  musicFilter.type = 'lowpass';
  musicFilter.frequency.value = 20000;
  music.connect(musicFilter);
  musicFilter.connect(master);

  const sfx = _ctx.createGain();
  sfx.connect(master);

  const comms = _ctx.createGain();
  comms.connect(master);

  const stinger = _ctx.createGain();
  stinger.connect(master);

  _buses = { master, music, musicFilter, sfx, comms, stinger };
  applyFocusGains();
  loadManifest().catch(() => {});
  return _ctx;
}

function targetMusicBase() {
  const mode = getAudioFocusMode();
  const musOn = isMusicEnabled();
  const vols = getVolumeSettings();
  const modeFactor = { overdrive: 0.72, balanced: 0.50, focus: 0.34, muted: 0 }[mode] ?? 0.50;
  const mediaDuck = _mediaPlayingCount > 0 ? 0.14 : 1.0;
  return musOn ? modeFactor * vols.bgm * mediaDuck : 0;
}

function applyFocusGains() {
  if (!_ctx || !_buses) return;
  const now = _ctx.currentTime;
  const mode = getAudioFocusMode();
  const sfxOn = isSoundEnabled();
  const vols = getVolumeSettings();

  const sfxScale = sfxOn ? vols.sfx : 0;
  const sfxMode = { overdrive: 1.0, balanced: 0.84, focus: 0.58, muted: 0 }[mode] ?? 0.84;

  _buses.master.gain.setTargetAtTime(mode === 'muted' ? 0 : vols.master, now, 0.04);
  _buses.music.gain.setTargetAtTime(targetMusicBase(), now, 0.08);
  _buses.musicFilter.frequency.setTargetAtTime(mode === 'focus' ? 6800 : 20000, now, 0.12);
  _buses.sfx.gain.setTargetAtTime(sfxScale * sfxMode, now, 0.04);
  _buses.comms.gain.setTargetAtTime(sfxScale * Math.min(1, sfxMode * 1.05), now, 0.04);
  _buses.stinger.gain.setTargetAtTime(sfxScale * (mode === 'muted' ? 0 : 0.92), now, 0.04);

  if (_currentZone === 'nontrack') {
    if (mode === 'focus') {
      setStemMix({ drums: 0.05, bass: 0.55, keys_chords: 0.95, lead_sparkle: 0.15 });
    } else {
      setStemMix({ drums: 1.0, bass: 1.0, keys_chords: 1.0, lead_sparkle: 1.0 });
    }
  }
}

function duckMusic(depth = 0.62, holdS = 0.35, attackS = 0.02, releaseS = 0.35) {
  if (!_ctx || !_buses || !isMusicEnabled()) return;
  const now = _ctx.currentTime;
  const base = targetMusicBase();
  _buses.music.gain.cancelScheduledValues(now);
  _buses.music.gain.setTargetAtTime(base * depth, now, attackS);
  _buses.music.gain.setTargetAtTime(base, now + holdS, releaseS * 0.4);
}

async function loadManifest() {
  if (_manifest) return _manifest;
  if (_manifestPromise) return _manifestPromise;
  _manifestPromise = NoirApi.getAudioManifest()
    .then((data) => {
      _manifest = data;
      return data;
    })
    .catch(() => null);
  return _manifestPromise;
}

async function getBuffer(url) {
  if (_buffers.has(url)) return _buffers.get(url);
  const ctx = ensureContext();
  if (!ctx) return null;
  try {
    const buf = await ctx.decodeAudioData(await NoirApi.getAudioBytes(url));
    _buffers.set(url, buf);
    return buf;
  } catch {
    return null;
  }
}

function synthFallback(freq = 660, dur = 0.09, type = 'triangle', gainVal = 0.12) {
  const ctx = ensureContext();
  if (!ctx || !_buses) return;
  const now = ctx.currentTime;
  const osc = ctx.createOscillator();
  const g = ctx.createGain();
  osc.type = type;
  osc.frequency.setValueAtTime(freq, now);
  g.gain.setValueAtTime(0.0001, now);
  g.gain.exponentialRampToValueAtTime(gainVal, now + 0.008);
  g.gain.exponentialRampToValueAtTime(0.0001, now + dur);
  osc.connect(g);
  g.connect(_buses.sfx);
  osc.start(now);
  osc.stop(now + dur + 0.01);
}

export async function playCue(cueId, { gain = 1.0, detuneCents = 0 } = {}) {
  if (!isSoundEnabled()) return;
  const ctx = ensureContext();
  if (!ctx || !_buses) return;
  if (_activeVoices >= MAX_POLYPHONY) return;

  const manifest = await loadManifest();
  const meta = manifest?.sfx?.[cueId];
  const nowMs = performance.now();
  const cooldown = meta?.cooldown_ms ?? 45;
  const prevMs = _lastPlayed.get(cueId) ?? 0;
  if (nowMs - prevMs < cooldown) return;
  _lastPlayed.set(cueId, nowMs);

  const mode = getAudioFocusMode();
  if (mode === 'focus' && meta?.focus_min === 'overdrive') return;

  if (!meta?.variants?.length) {
    synthFallback(cueId.includes('ALERT') || cueId.includes('IMPACT') ? 240 : 660, 0.1);
    return;
  }

  const idx = ((_rrIndex.get(cueId) ?? -1) + 1) % meta.variants.length;
  _rrIndex.set(cueId, idx);
  const buf = await getBuffer(meta.variants[idx]);
  if (!buf) {
    synthFallback(620, 0.09);
    return;
  }

  const src = ctx.createBufferSource();
  src.buffer = buf;

  // Runtime ±3% pitch (±50 cents) & ±1.5 dB gain micro-jitter to prevent ear fatigue
  const pJitter = Number(meta.pitch_jitter || 0);
  const gJitterDb = Number(meta.gain_jitter_db || 0);
  const randCents = pJitter > 0 ? (Math.random() * 2 - 1) * (pJitter * 1731) : 0;
  const randGain = gJitterDb > 0 ? Math.pow(10, ((Math.random() * 2 - 1) * gJitterDb) / 20) : 1.0;

  src.detune.value = detuneCents + randCents;
  const vGain = ctx.createGain();
  vGain.gain.value = gain * (meta.gain ?? 0.75) * randGain;

  const busName = meta.bus === 'comms' ? 'comms' : meta.bus === 'stinger' ? 'stinger' : 'sfx';
  src.connect(vGain);
  vGain.connect(_buses[busName]);

  if (busName === 'stinger') {
    duckMusic(0.56, Math.min(1.4, buf.duration * 0.7), 0.02, 0.35);
  } else if (busName === 'comms') {
    duckMusic(0.79, Math.min(0.6, buf.duration), 0.02, 0.25);
  }

  _activeVoices += 1;
  src.onended = () => {
    _activeVoices = Math.max(0, _activeVoices - 1);
  };
  src.start();
}

export function stopMusic() {
  _musicEpoch += 1;
  for (const node of _musicNodes) {
    try { node.stop(); } catch {}
    try { node.disconnect(); } catch {}
  }
  _musicNodes = [];
  _stemGains = { drums: null, bass: null, keys_chords: null, lead_sparkle: null };
}

function nextBarQuantizedTime(bpm = 125) {
  if (!_ctx || _musicNodes.length === 0 || !_musicStartTime) return (_ctx?.currentTime || 0) + 0.04;
  const beatS = 60.0 / bpm;
  const elapsed = Math.max(0, _ctx.currentTime - _musicStartTime);
  const nextBeat = Math.ceil(elapsed / beatS) * beatS;
  return _musicStartTime + Math.min(nextBeat, elapsed + 0.48);
}

export async function startMusicZone(zone = 'nontrack') {
  _currentZone = zone;
  if (!isMusicEnabled()) return;
  const ctx = ensureContext();
  if (!ctx || !_buses) return;
  const manifest = await loadManifest();
  if (!manifest?.music) return;

  const epoch = ++_musicEpoch;
  const startAt = nextBarQuantizedTime(125);

  if (zone === 'nontrack') {
    const stems = manifest.music.nontrack_lounge?.stems || {};
    const decoded = await Promise.all(Object.entries(stems).map(async ([k, u]) => [k, await getBuffer(u)]));
    if (!isMusicEnabled() || _currentZone !== 'nontrack' || epoch !== _musicEpoch) return;
    for (const node of _musicNodes) { try { node.stop(startAt); } catch {} }
    _musicNodes = [];
    _stemGains = { drums: null, bass: null, keys_chords: null, lead_sparkle: null };
    const t0 = Math.max(ctx.currentTime + 0.03, startAt);
    _musicStartTime = t0;
    const focus = getAudioFocusMode();
    for (const [key, buf] of decoded) {
      if (!buf) continue;
      const src = ctx.createBufferSource();
      src.buffer = buf;
      src.loop = true;
      const g = ctx.createGain();
      g.gain.value = focus === 'focus'
        ? ({ drums: 0.05, bass: 0.55, keys_chords: 0.95, lead_sparkle: 0.15 }[key] ?? 0.5)
        : 1.0;
      src.connect(g);
      g.connect(_buses.music);
      src.start(t0);
      _musicNodes.push(src);
      _stemGains[key] = g;
    }
    return;
  }

  const urlMap = {
    lobby: manifest.music.ambience?.lobby_pad,
    ontrack_grid: manifest.music.ontrack_overdrive?.grid_intro,
    ontrack_main: manifest.music.ontrack_overdrive?.main_loop,
    ontrack_final: manifest.music.ontrack_overdrive?.final_lap,
    podium: manifest.music.victory_fanfare?.podium_tally,
  };
  const url = urlMap[zone] || manifest.music.nontrack_lounge?.full;
  if (!url) return;
  const buf = await getBuffer(url);
  if (!buf || !isMusicEnabled() || epoch !== _musicEpoch) return;
  for (const node of _musicNodes) { try { node.stop(startAt); } catch {} }
  _musicNodes = [];
  _stemGains = { drums: null, bass: null, keys_chords: null, lead_sparkle: null };
  const t0 = Math.max(ctx.currentTime + 0.03, startAt);
  _musicStartTime = t0;
  const src = ctx.createBufferSource();
  src.buffer = buf;
  src.loop = zone !== 'ontrack_grid';
  src.connect(_buses.music);
  src.start(t0);
  _musicNodes.push(src);
}

export function setMusicZone(zone) {
  if (zone === _currentZone && _musicNodes.length > 0) return;
  startMusicZone(zone);
}

export function setStemMix(mix = {}) {
  if (!_ctx) return;
  const now = _ctx.currentTime;
  for (const [k, val] of Object.entries(mix)) {
    const g = _stemGains[k];
    if (g) g.gain.setTargetAtTime(Math.max(0, Math.min(1.2, Number(val))), now, 0.18);
  }
}

export function pulseWriterTyping() {
  if (!isMusicEnabled() || _currentZone !== 'nontrack') return;
  setStemMix({ drums: 0.18, bass: 0.65, keys_chords: 1.0, lead_sparkle: 0.28 });
  clearTimeout(_typingTimer);
  _typingTimer = setTimeout(() => {
    if (getAudioFocusMode() === 'focus') {
      setStemMix({ drums: 0.05, bass: 0.55, keys_chords: 0.95, lead_sparkle: 0.15 });
    } else {
      setStemMix({ drums: 1.0, bass: 1.0, keys_chords: 1.0, lead_sparkle: 1.0 });
    }
  }, 2400);
}

export async function playVictoryStinger() {
  if (!isSoundEnabled()) return;
  const ctx = ensureContext();
  if (!ctx || !_buses) return;
  const manifest = await loadManifest();
  const url = manifest?.music?.victory_fanfare?.race_complete;
  if (!url) {
    playCue('SFX_BANNER_COMPLETE_STINGER');
    return;
  }
  const buf = await getBuffer(url);
  if (!buf) {
    playCue('SFX_BANNER_COMPLETE_STINGER');
    return;
  }
  duckMusic(0.35, Math.min(3.0, buf.duration * 0.8), 0.02, 0.4);
  const src = ctx.createBufferSource();
  src.buffer = buf;
  src.connect(_buses.stinger);
  src.start();
}

export async function startDriftLoop() {
  if (!isSoundEnabled() || getAudioFocusMode() === 'focus' || _driftLoopNodes) return;
  const ctx = ensureContext();
  const manifest = await loadManifest();
  const url = manifest?.sfx?.SFX_DRIFT_CHARGE_LOOP?.variants?.[0];
  if (!ctx || !url) return;
  const buf = await getBuffer(url);
  if (!buf || _driftLoopNodes) return;
  const src = ctx.createBufferSource();
  src.buffer = buf;
  src.loop = true;
  const g = ctx.createGain();
  g.gain.setValueAtTime(0.001, ctx.currentTime);
  g.gain.linearRampToValueAtTime(0.42, ctx.currentTime + 0.18);
  src.connect(g);
  g.connect(_buses.sfx);
  src.start();
  _driftLoopNodes = { src, g };
}

export function stopDriftLoop() {
  if (!_driftLoopNodes || !_ctx) return;
  const { src, g } = _driftLoopNodes;
  _driftLoopNodes = null;
  try {
    g.gain.setTargetAtTime(0.0001, _ctx.currentTime, 0.08);
    setTimeout(() => { try { src.stop(); } catch {} }, 240);
  } catch {}
}

// Preserved legacy exports mapped to the upgraded 21-cue library
export function playHover() { playCue('SFX_UI_TAB_TICK', { gain: 0.42 }); }
export function playTick() { playCue('SFX_UI_TAB_TICK', { gain: 0.72 }); }
export function playSelect() { playCue('SFX_UI_NODE_SELECT'); }
export function playCookStart() { playCue('SFX_PROC_UPGRADE_SWEEP'); }
export function playCookComplete() { playCue('SFX_BANNER_COMPLETE_STINGER'); }
export function playPortSnap() { playCue('SFX_COMPONENT_LOCK_INSTALL'); }
export function playWireCut() { playCue('SFX_WIPE_RIBBON_SLASH', { gain: 0.75 }); }
export function playAlert() { playCue('SFX_IMPACT_ENERGY_HIT'); }
