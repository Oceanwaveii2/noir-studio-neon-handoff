/* Noir Fiction Studio — Star Rail Sampled UI Audio + Web Audio Fallback */

let audioCtx = null;
let bgmAudio = null;
const sfxCache = new Map();

const SFX_PATHS = {
  hover: '/assets/v2/audio/sfx/sfx_hover.wav',
  click: '/assets/v2/audio/sfx/sfx_click.wav',
  latch: '/assets/v2/audio/sfx/sfx_latch.wav',
  execute: '/assets/v2/audio/sfx/sfx_execute.wav',
  complete: '/assets/v2/audio/sfx/sfx_complete.wav',
  wipe: '/assets/v2/audio/sfx/sfx_wipe.wav',
  alert: '/assets/v2/audio/sfx/sfx_alert.wav',
};

function ensureContext() {
  if (!isSoundEnabled()) return null;
  if (typeof window === 'undefined') return null;
  const Ctor = window.AudioContext || window.webkitAudioContext;
  if (!Ctor) return null;
  if (!audioCtx) {
    try {
      audioCtx = new Ctor();
    } catch (_) {
      return null;
    }
  }
  if (audioCtx.state === 'suspended') {
    audioCtx.resume().catch(() => {});
  }
  return audioCtx;
}

export function isSoundEnabled() {
  try {
    return localStorage.getItem('noir-sound') === 'on';
  } catch (_) {
    return false;
  }
}

export function setSoundEnabled(enabled) {
  try {
    localStorage.setItem('noir-sound', enabled ? 'on' : 'off');
  } catch (_) {}
}

export function isMusicEnabled() {
  try {
    return localStorage.getItem('noir-music') === 'on';
  } catch (_) {
    return false;
  }
}

export function setMusicEnabled(enabled) {
  try {
    localStorage.setItem('noir-music', enabled ? 'on' : 'off');
  } catch (_) {}
  if (typeof Audio === 'undefined') return;
  if (!bgmAudio) {
    bgmAudio = new Audio('/assets/v2/audio/music/bgm_loop.mp3');
    bgmAudio.loop = true;
    bgmAudio.volume = 0.24;
  }
  if (enabled) {
    bgmAudio.play().catch(() => {});
  } else {
    bgmAudio.pause();
  }
}

function playSample(key, volume = 0.42, fallbackFn = null) {
  if (!isSoundEnabled()) return;
  const src = SFX_PATHS[key];
  if (typeof Audio !== 'undefined' && src) {
    try {
      let base = sfxCache.get(key);
      if (!base) {
        base = new Audio(src);
        base.preload = 'auto';
        sfxCache.set(key, base);
      }
      const clip = base.cloneNode();
      clip.volume = volume;
      const p = clip.play();
      if (p && typeof p.catch === 'function') {
        p.catch(() => { if (fallbackFn) fallbackFn(); });
      }
      return;
    } catch (_) {}
  }
  if (fallbackFn) fallbackFn();
}

function playTone(ctx, { freq, endFreq = null, type = 'triangle', start = 0, duration = 0.05, gain = 0.045 }) {
  const t0 = ctx.currentTime + start;
  const osc = ctx.createOscillator();
  const amp = ctx.createGain();
  osc.type = type;
  osc.frequency.setValueAtTime(freq, t0);
  if (endFreq !== null) {
    osc.frequency.exponentialRampToValueAtTime(Math.max(40, endFreq), t0 + duration);
  }
  const level = Math.min(0.035, Math.max(0.0005, gain));
  amp.gain.setValueAtTime(0.0001, t0);
  amp.gain.linearRampToValueAtTime(level, t0 + 0.005);
  amp.gain.exponentialRampToValueAtTime(0.0001, t0 + duration);
  osc.connect(amp);
  amp.connect(ctx.destination);
  osc.start(t0);
  osc.stop(t0 + duration + 0.01);
}

/** Subtle hover cue. */
export function playHover() {
  playSample('hover', 0.22);
}

/** Crisp menu/tab switch tick. */
export function playTick() {
  playSample('click', 0.36, () => {
    const ctx = ensureContext();
    if (ctx) playTone(ctx, { freq: 1320, endFreq: 980, type: 'triangle', duration: 0.032, gain: 0.035 });
  });
}

/** Tactile two-tone lock-in click for cards and episode selection. */
export function playSelect() {
  playSample('latch', 0.4, () => {
    const ctx = ensureContext();
    if (!ctx) return;
    playTone(ctx, { freq: 520, endFreq: 860, type: 'sine', duration: 0.045, gain: 0.04 });
    playTone(ctx, { freq: 160, endFreq: 92, type: 'triangle', start: 0.01, duration: 0.055, gain: 0.035 });
  });
}

/** Rising synth spool when starting Cook Pipeline. */
export function playCookStart() {
  playSample('execute', 0.45, () => {
    const ctx = ensureContext();
    if (!ctx) return;
    playTone(ctx, { freq: 240, endFreq: 560, type: 'sawtooth', duration: 0.18, gain: 0.025 });
    playTone(ctx, { freq: 480, endFreq: 960, type: 'sine', start: 0.04, duration: 0.16, gain: 0.03 });
  });
}

/** Ascending 3-note chime when Cook Completed ribbon appears. */
export function playCookComplete() {
  playSample('complete', 0.48, () => {
    const ctx = ensureContext();
    if (!ctx) return;
    playTone(ctx, { freq: 523.25, type: 'triangle', start: 0.0, duration: 0.12, gain: 0.045 });
    playTone(ctx, { freq: 659.25, type: 'triangle', start: 0.07, duration: 0.14, gain: 0.045 });
    playTone(ctx, { freq: 783.99, endFreq: 1046.5, type: 'sine', start: 0.14, duration: 0.24, gain: 0.05 });
  });
}

/** Crisp magnetic snap click when a wire locks onto a compatible port. */
export function playPortSnap() {
  playSample('latch', 0.42, () => {
    const ctx = ensureContext();
    if (ctx) playTone(ctx, { freq: 940, endFreq: 1420, type: 'sine', duration: 0.038, gain: 0.04 });
  });
}

/** Low mechanical thud when Y-knife cuts wires or transition wipes. */
export function playWireCut() {
  playSample('wipe', 0.44, () => {
    const ctx = ensureContext();
    if (ctx) playTone(ctx, { freq: 185, endFreq: 68, type: 'triangle', duration: 0.075, gain: 0.05 });
  });
}

/** Firewall reject / canon warning alert cue. */
export function playAlert() {
  playSample('alert', 0.46, () => {
    const ctx = ensureContext();
    if (ctx) playTone(ctx, { freq: 340, endFreq: 190, type: 'sawtooth', duration: 0.14, gain: 0.035 });
  });
}
