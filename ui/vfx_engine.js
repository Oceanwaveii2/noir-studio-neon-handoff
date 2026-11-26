/* Noir Fiction Studio — Overdrive Game-Grade VFX Runtime Engine
 * Offline Lottie JSON Vector Player (EffectCraft exports) + Additive RGBA Plate/Sprite Compositor (Foundry Nuke 17.0v3)
 * Anchored to live DOM bounding rects with 3 intensity levels: 'overdrive' | 'balanced' | 'focus'
 */

import { NoirApi } from './api.js';

const VFX_MODE_KEY = 'noir-vfx-intensity-v1';
const PLATES_BASE = '/assets/vfx/plates';

const lottieCache = new Map();
const imageCache = new Map();

export function getVfxIntensity() {
  try {
    const v = localStorage.getItem(VFX_MODE_KEY);
    if (v === 'overdrive' || v === 'balanced' || v === 'focus') return v;
  } catch (_) {}
  if (typeof window !== 'undefined' && window.matchMedia?.('(prefers-reduced-motion: reduce)')?.matches) {
    return 'focus';
  }
  return 'overdrive';
}

export function setVfxIntensity(mode) {
  const safe = (mode === 'overdrive' || mode === 'balanced' || mode === 'focus') ? mode : 'overdrive';
  try { localStorage.setItem(VFX_MODE_KEY, safe); } catch (_) {}
  if (document?.body) document.body.dataset.vfx = safe;
  return safe;
}

export async function loadLottieAsset(name) {
  if (lottieCache.has(name)) return lottieCache.get(name);
  const promise = NoirApi.getLottieAsset(name)
    .catch(() => null);
  lottieCache.set(name, promise);
  return promise;
}

export function loadPlateImage(filename) {
  if (imageCache.has(filename)) return imageCache.get(filename);
  const promise = new Promise((resolve) => {
    const img = new Image();
    img.onload = () => resolve(img);
    img.onerror = () => resolve(null);
    img.src = `${PLATES_BASE}/${filename}`;
  });
  imageCache.set(filename, promise);
  return promise;
}

/* --- Compact Offline Lottie Vector Evaluator (EffectCraft v5.12 JSON) --- */

function cubicEase(t, x1 = 0.22, y1 = 1, x2 = 0.36, y2 = 1) {
  const u = Math.max(0, Math.min(1, t));
  const inv = 1 - u;
  return 3 * inv * inv * u * y1 + 3 * inv * u * u * y2 + u * u * u;
}

function evalProp(prop, frame, fallback) {
  if (!prop) return fallback;
  if (!prop.a || !Array.isArray(prop.k)) return prop.k ?? fallback;
  const keys = prop.k;
  if (!keys.length) return fallback;
  if (typeof keys[0] === 'number') return keys;
  if (frame <= (keys[0].t ?? 0)) return keys[0].s ?? fallback;
  const last = keys[keys.length - 1];
  if (frame >= (last.t ?? 0)) return last.s ?? last.e ?? keys[Math.max(0, keys.length - 2)]?.e ?? fallback;

  for (let i = 0; i < keys.length - 1; i += 1) {
    const k0 = keys[i];
    const k1 = keys[i + 1];
    const t0 = k0.t ?? 0;
    const t1 = k1.t ?? t0 + 1;
    if (frame >= t0 && frame <= t1) {
      const startVal = k0.s ?? fallback;
      const endVal = k0.e ?? k1.s ?? startVal;
      if (k0.h) return startVal;
      const raw = t1 === t0 ? 1 : (frame - t0) / (t1 - t0);
      const frac = cubicEase(raw);
      if (Array.isArray(startVal) && Array.isArray(endVal)) {
        return startVal.map((v, idx) => v + ((endVal[idx] ?? v) - v) * frac);
      }
      if (typeof startVal === 'number' && typeof endVal === 'number') {
        return startVal + (endVal - startVal) * frac;
      }
      return startVal;
    }
  }
  return fallback;
}

function rgbaStr(colorArr, opacityPct = 100) {
  const r = Math.round(Math.max(0, Math.min(1, colorArr?.[0] ?? 1)) * 255);
  const g = Math.round(Math.max(0, Math.min(1, colorArr?.[1] ?? 1)) * 255);
  const b = Math.round(Math.max(0, Math.min(1, colorArr?.[2] ?? 1)) * 255);
  const a = Math.max(0, Math.min(1, (opacityPct ?? 100) / 100));
  return `rgba(${r},${g},${b},${a.toFixed(3)})`;
}

function drawPolygonPath(ctx, cx, cy, pts, radius, rotDeg) {
  const n = Math.max(3, Math.round(pts || 5));
  const rot = ((rotDeg || 0) - 90) * (Math.PI / 180);
  ctx.beginPath();
  for (let i = 0; i < n; i += 1) {
    const a = rot + (i * Math.PI * 2) / n;
    const x = cx + Math.cos(a) * radius;
    const y = cy + Math.sin(a) * radius;
    if (i === 0) ctx.moveTo(x, y);
    else ctx.lineTo(x, y);
  }
  ctx.closePath();
}

export function renderLottieFrame(ctx, anim, frame, rect, alphaMult = 1) {
  if (!anim || !Array.isArray(anim.layers)) return;
  const scaleX = rect.w / (anim.w || 256);
  const scaleY = rect.h / (anim.h || 256);

  ctx.save();
  ctx.translate(rect.x, rect.y);
  ctx.scale(scaleX, scaleY);

  // Draw bottom-to-top (Lottie layer order: index 0 is topmost)
  for (let li = anim.layers.length - 1; li >= 0; li -= 1) {
    const layer = anim.layers[li];
    if (frame < (layer.ip ?? 0) || frame > (layer.op ?? anim.op ?? 60)) continue;
    const ks = layer.ks || {};
    const lp = evalProp(ks.p, frame, [0, 0]);
    const la = evalProp(ks.a, frame, [0, 0]);
    const ls = evalProp(ks.s, frame, [100, 100]);
    const lr = evalProp(ks.r, frame, 0);
    const lo = evalProp(ks.o, frame, 100);
    const lOp = (Array.isArray(lo) ? lo[0] : lo) / 100;
    if (lOp <= 0.005) continue;

    ctx.save();
    ctx.globalAlpha *= lOp * alphaMult;
    ctx.translate(lp[0] || 0, lp[1] || 0);
    ctx.rotate(((Array.isArray(lr) ? lr[0] : lr) || 0) * (Math.PI / 180));
    ctx.scale((ls[0] ?? 100) / 100, (ls[1] ?? 100) / 100);
    ctx.translate(-(la[0] || 0), -(la[1] || 0));

    for (const grp of layer.shapes || []) {
      const items = grp.it || [grp];
      const tr = items.find((it) => it.ty === 'tr');
      const fl = items.find((it) => it.ty === 'fl');
      const st = items.find((it) => it.ty === 'st');
      const geom = items.filter((it) => it.ty === 'rc' || it.ty === 'el' || it.ty === 'sr');

      ctx.save();
      if (tr) {
        const gp = evalProp(tr.p, frame, [0, 0]);
        const ga = evalProp(tr.a, frame, [0, 0]);
        const gs = evalProp(tr.s, frame, [100, 100]);
        const gr = evalProp(tr.r, frame, 0);
        const go = evalProp(tr.o, frame, 100);
        const gOp = (Array.isArray(go) ? go[0] : go) / 100;
        ctx.globalAlpha *= gOp;
        ctx.translate(gp[0] || 0, gp[1] || 0);
        ctx.rotate(((Array.isArray(gr) ? gr[0] : gr) || 0) * (Math.PI / 180));
        ctx.scale((gs[0] ?? 100) / 100, (gs[1] ?? 100) / 100);
        ctx.translate(-(ga[0] || 0), -(ga[1] || 0));
      }

      for (const sh of geom) {
        const sp = evalProp(sh.p, frame, [0, 0]);
        if (sh.ty === 'rc') {
          const sz = evalProp(sh.s, frame, [100, 100]);
          const w = sz[0] || 0;
          const h = sz[1] || 0;
          ctx.beginPath();
          ctx.rect((sp[0] || 0) - w / 2, (sp[1] || 0) - h / 2, w, h);
        } else if (sh.ty === 'el') {
          const sz = evalProp(sh.s, frame, [100, 100]);
          ctx.beginPath();
          ctx.ellipse(sp[0] || 0, sp[1] || 0, Math.abs(sz[0] || 0) / 2, Math.abs(sz[1] || 0) / 2, 0, 0, Math.PI * 2);
        } else if (sh.ty === 'sr') {
          const orVal = evalProp(sh.or, frame, 30);
          const ptsVal = evalProp(sh.pt, frame, 5);
          const rotVal = evalProp(sh.r, frame, 0);
          drawPolygonPath(
            ctx,
            sp[0] || 0,
            sp[1] || 0,
            Array.isArray(ptsVal) ? ptsVal[0] : ptsVal,
            Array.isArray(orVal) ? orVal[0] : orVal,
            Array.isArray(rotVal) ? rotVal[0] : rotVal
          );
        }
        if (fl) {
          const fc = evalProp(fl.c, frame, [1, 1, 1, 1]);
          const fo = evalProp(fl.o, frame, 100);
          ctx.fillStyle = rgbaStr(fc, Array.isArray(fo) ? fo[0] : fo);
          ctx.fill();
        }
        if (st) {
          const sc = evalProp(st.c, frame, [1, 1, 1, 1]);
          const so = evalProp(st.o, frame, 100);
          const sw = evalProp(st.w, frame, 2);
          ctx.strokeStyle = rgbaStr(sc, Array.isArray(so) ? so[0] : so);
          ctx.lineWidth = Array.isArray(sw) ? sw[0] : sw;
          ctx.stroke();
        }
      }
      ctx.restore();
    }
    ctx.restore();
  }
  ctx.restore();
}

/* --- Full-Viewport GPU-Accelerated Additive Overlay Director --- */

class NoirVfxDirector {
  constructor() {
    this.canvas = null;
    this.ctx = null;
    this.domLayer = null;
    this.effects = [];
    this.particles = [];
    this.rafId = 0;
    this.lastTs = 0;
    this.preloaded = false;
  }

  ensureMounted() {
    if (typeof document === 'undefined') return false;
    setVfxIntensity(getVfxIntensity());
    if (!this.canvas || !this.canvas.isConnected) {
      this.canvas = document.getElementById('v2VfxCanvas');
      if (!this.canvas) {
        this.canvas = document.createElement('canvas');
        this.canvas.id = 'v2VfxCanvas';
        this.canvas.className = 'v2-vfx-canvas';
        this.canvas.setAttribute('aria-hidden', 'true');
        document.body.appendChild(this.canvas);
      }
      this.ctx = this.canvas.getContext('2d');
      this.resize();
      window.addEventListener('resize', () => this.resize());
    }
    if (!this.domLayer || !this.domLayer.isConnected) {
      this.domLayer = document.getElementById('v2VfxDomLayer');
      if (!this.domLayer) {
        this.domLayer = document.createElement('div');
        this.domLayer.id = 'v2VfxDomLayer';
        this.domLayer.className = 'v2-vfx-dom-layer';
        this.domLayer.setAttribute('aria-hidden', 'true');
        document.body.appendChild(this.domLayer);
      }
    }
    if (!this.preloaded) {
      this.preloaded = true;
      ['speed_ribbon_wipe', 'node_hover_sheen', 'chevron_progress_beam', 'overdrive_charge_ring', 'milestone_ribbon_confetti']
        .forEach((n) => loadLottieAsset(n));
      ['optical_starburst_flare.png', 'spark_burst_sheet.png', 'overdrive_chromatic_streak.png', 'hard_lock_shield_bloom.png']
        .forEach((p) => loadPlateImage(p));
    }
    return true;
  }

  resize() {
    if (!this.canvas) return;
    const dpr = Math.min(2, window.devicePixelRatio || 1);
    const w = window.innerWidth;
    const h = window.innerHeight;
    this.canvas.width = Math.round(w * dpr);
    this.canvas.height = Math.round(h * dpr);
    this.canvas.style.width = `${w}px`;
    this.canvas.style.height = `${h}px`;
    if (this.ctx) this.ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  }

  startLoop() {
    if (this.rafId) return;
    this.lastTs = performance.now();
    const tick = (now) => {
      const dt = Math.min(0.05, (now - this.lastTs) / 1000);
      this.lastTs = now;
      this.renderFrame(now, dt);
      if (this.effects.length || this.particles.length) {
        this.rafId = requestAnimationFrame(tick);
      } else {
        this.rafId = 0;
        if (this.ctx && this.canvas) {
          this.ctx.clearRect(0, 0, window.innerWidth, window.innerHeight);
        }
      }
    };
    this.rafId = requestAnimationFrame(tick);
  }

  renderFrame(now, dt) {
    if (!this.ctx) return;
    const ctx = this.ctx;
    ctx.clearRect(0, 0, window.innerWidth, window.innerHeight);

    const alive = [];
    for (const fx of this.effects) {
      const elapsed = (now - fx.start) / 1000;
      if (elapsed >= fx.duration) continue;
      alive.push(fx);
      const progress = Math.max(0, Math.min(1, elapsed / fx.duration));
      const rect = typeof fx.getRect === 'function' ? fx.getRect() : fx.rect;
      if (!rect) continue;

      ctx.save();
      ctx.globalCompositeOperation = fx.blend || 'source-over';
      if (fx.type === 'lottie' && fx.anim) {
        const frame = (fx.anim.ip || 0) + progress * ((fx.anim.op || 60) - (fx.anim.ip || 0));
        renderLottieFrame(ctx, fx.anim, frame, rect, fx.alpha ?? 1);
      } else if (fx.type === 'plate' && fx.img) {
        const fade = Math.sin(progress * Math.PI);
        const scale = (fx.scaleFrom ?? 0.65) + ((fx.scaleTo ?? 1.25) - (fx.scaleFrom ?? 0.65)) * cubicEase(progress);
        const cx = rect.x + rect.w / 2;
        const cy = rect.y + rect.h / 2;
        const dw = rect.w * scale;
        const dh = rect.h * scale;
        ctx.globalAlpha = fade * (fx.alpha ?? 0.92);
        ctx.translate(cx, cy);
        if (fx.rotateDeg) ctx.rotate((fx.rotateDeg * progress) * (Math.PI / 180));
        ctx.drawImage(fx.img, -dw / 2, -dh / 2, dw, dh);
      } else if (fx.type === 'spritesheet' && fx.img) {
        const frames = fx.frames || 8;
        const idx = Math.min(frames - 1, Math.floor(progress * frames));
        const fw = fx.img.naturalWidth / frames;
        const fh = fx.img.naturalHeight;
        ctx.globalAlpha = fx.alpha ?? 0.95;
        ctx.drawImage(fx.img, idx * fw, 0, fw, fh, rect.x, rect.y, rect.w, rect.h);
      }
      ctx.restore();
    }
    this.effects = alive;

    // Lightweight drift sparks streaming off the gutter conduit spine
    const liveParts = [];
    for (const p of this.particles) {
      p.age += dt;
      if (p.age >= p.life) continue;
      liveParts.push(p);
      p.x += p.vx * dt;
      p.y += p.vy * dt;
      p.vy += p.gravity * dt;
      const a = 1 - p.age / p.life;
      ctx.save();
      ctx.globalCompositeOperation = 'lighter';
      ctx.globalAlpha = a * 0.92;
      ctx.strokeStyle = p.color;
      ctx.lineWidth = p.size;
      ctx.beginPath();
      ctx.moveTo(p.x, p.y);
      ctx.lineTo(p.x - p.vx * 0.045, p.y - p.vy * 0.045);
      ctx.stroke();
      ctx.restore();
    }
    this.particles = liveParts;
  }

  /* 1. Diagonal Kinetic Speed-Ribbon Transition */
  async playSpeedRibbonWipe() {
    const mode = getVfxIntensity();
    if (mode === 'focus' || !this.ensureMounted()) return;
    const [anim, streak] = await Promise.all([
      loadLottieAsset('speed_ribbon_wipe'),
      loadPlateImage('overdrive_chromatic_streak.png'),
    ]);
    const fullRect = () => ({ x: 0, y: 0, w: window.innerWidth, h: window.innerHeight });
    if (anim) {
      this.effects.push({ type: 'lottie', anim, start: performance.now(), duration: 0.62, getRect: fullRect, alpha: mode === 'overdrive' ? 0.96 : 0.72, blend: 'source-over' });
    }
    if (streak && mode === 'overdrive') {
      this.effects.push({
        type: 'plate', img: streak, start: performance.now() + 60, duration: 0.48,
        getRect: () => ({ x: window.innerWidth * 0.05, y: window.innerHeight * 0.34, w: window.innerWidth * 0.9, h: 240 }),
        scaleFrom: 0.9, scaleTo: 1.18, rotateDeg: -14, alpha: 0.82, blend: 'lighter',
      });
    }
    this.startLoop();
  }

  /* 2. Node Hover Sheen */
  async playNodeHoverSheen(el) {
    const mode = getVfxIntensity();
    if (mode === 'focus' || !el || !this.ensureMounted()) return;
    const anim = await loadLottieAsset('node_hover_sheen');
    if (!anim) return;
    this.effects.push({
      type: 'lottie', anim, start: performance.now(), duration: 0.45,
      getRect: () => {
        const r = el.getBoundingClientRect();
        return { x: r.left, y: r.top, w: r.width, h: Math.min(46, r.height) };
      },
      alpha: mode === 'overdrive' ? 0.68 : 0.42,
      blend: 'lighter',
    });
    this.startLoop();
  }

  /* 3. Sweeping Energy Progress Beam + Telemetry Pill */
  async playEnergySweep(el, label = 'Optimizing Node: 100%') {
    const mode = getVfxIntensity();
    if (mode === 'focus' || !el || !this.ensureMounted()) return;
    const anim = await loadLottieAsset('chevron_progress_beam');
    if (anim) {
      this.effects.push({
        type: 'lottie', anim, start: performance.now(), duration: 0.78,
        getRect: () => {
          const r = el.getBoundingClientRect();
          return { x: r.left, y: r.top, w: r.width, h: r.height };
        },
        alpha: mode === 'overdrive' ? 0.72 : 0.45,
        blend: 'lighter',
      });
      this.startLoop();
    }
    const r = el.getBoundingClientRect();
    const pill = document.createElement('div');
    pill.className = 'v2-vfx-float-pill';
    pill.textContent = label;
    pill.style.left = `${Math.max(16, Math.min(window.innerWidth - 280, r.left + r.width * 0.5 - 120))}px`;
    pill.style.top = `${Math.max(60, r.top - 14)}px`;
    this.domLayer.appendChild(pill);
    setTimeout(() => pill.remove(), 1200);
  }

  /* 4A. Local Action-Completed Spark Burst + Floating Badge */
  async playSparkBurst(el, badgeText = 'Action Completed', isHardLock = false) {
    const mode = getVfxIntensity();
    if (mode === 'focus' || !el || !this.ensureMounted()) return;
    const [sheet, lockBloom] = await Promise.all([
      loadPlateImage('spark_burst_sheet.png'),
      isHardLock ? loadPlateImage('hard_lock_shield_bloom.png') : Promise.resolve(null),
    ]);
    const r = el.getBoundingClientRect();
    const cx = r.left + Math.min(84, r.width * 0.16);
    const cy = r.top + r.height * 0.5;
    if (sheet) {
      this.effects.push({
        type: 'spritesheet', img: sheet, frames: 8, start: performance.now(), duration: 0.56,
        rect: { x: cx - 108, y: cy - 108, w: 216, h: 216 },
        alpha: mode === 'overdrive' ? 0.96 : 0.7,
        blend: 'lighter',
      });
    }
    if (lockBloom && mode === 'overdrive') {
      this.effects.push({
        type: 'plate', img: lockBloom, start: performance.now(), duration: 0.72,
        rect: { x: cx - 96, y: cy - 96, w: 192, h: 192 },
        scaleFrom: 0.55, scaleTo: 1.35, alpha: 0.85, blend: 'lighter',
      });
    }
    this.startLoop();

    const badge = document.createElement('div');
    badge.className = `v2-vfx-action-badge ${isHardLock ? 'is-law' : ''}`;
    badge.textContent = badgeText;
    badge.style.left = `${Math.max(20, Math.min(window.innerWidth - 220, cx + 24))}px`;
    badge.style.top = `${Math.max(64, cy - 26)}px`;
    this.domLayer.appendChild(badge);
    setTimeout(() => badge.remove(), 1350);
  }

  /* 4B. Major Commit Checkered Gold Victory Ribbon + Nuke Starburst + Confetti */
  async playMilestoneRibbon(title = 'PREPPED SCRIPT COMMITTED', subtitle = 'Synced to Story & Character Graphs') {
    const mode = getVfxIntensity();
    if (mode === 'focus' || !this.ensureMounted()) return;
    const [confetti, starburst] = await Promise.all([
      loadLottieAsset('milestone_ribbon_confetti'),
      loadPlateImage('optical_starburst_flare.png'),
    ]);
    if (confetti && mode === 'overdrive') {
      this.effects.push({
        type: 'lottie', anim: confetti, start: performance.now(), duration: 1.35,
        getRect: () => ({ x: 0, y: 42, w: window.innerWidth, h: 240 }),
        alpha: 0.92, blend: 'source-over',
      });
    }
    if (starburst) {
      this.effects.push({
        type: 'plate', img: starburst, start: performance.now(), duration: 0.92,
        getRect: () => ({ x: window.innerWidth * 0.5 - 190, y: -30, w: 380, h: 240 }),
        scaleFrom: 0.45, scaleTo: 1.35, rotateDeg: 18, alpha: mode === 'overdrive' ? 0.95 : 0.6, blend: 'lighter',
      });
    }
    this.startLoop();

    const banner = document.createElement('div');
    banner.className = 'v2-vfx-victory-ribbon';
    banner.title = 'Click to dismiss';
    banner.innerHTML = `<span class="v2-vfx-ribbon-check" aria-hidden="true"></span><div><strong>${title}</strong><small>${subtitle}</small></div><span class="v2-vfx-ribbon-check" aria-hidden="true"></span>`;
    banner.addEventListener('click', () => banner.remove(), { once: true });
    this.domLayer.appendChild(banner);
    setTimeout(() => banner.remove(), 1750);
  }

  /* 5. Overdrive Radial Charge Rings + Spine Drift Sparks */
  async playOverdriveCharge(badgeEl) {
    const mode = getVfxIntensity();
    if (mode === 'focus' || !badgeEl || !this.ensureMounted()) return;
    const ring = await loadLottieAsset('overdrive_charge_ring');
    const r = badgeEl.getBoundingClientRect();
    const cx = r.left + r.width / 2;
    const cy = r.top + r.height / 2;
    if (ring) {
      this.effects.push({
        type: 'lottie', anim: ring, start: performance.now(), duration: 0.85,
        rect: { x: cx - 92, y: cy - 92, w: 184, h: 184 },
        alpha: mode === 'overdrive' ? 0.95 : 0.65,
        blend: 'lighter',
      });
    }
    if (mode === 'overdrive') {
      const palette = ['#FFB830', '#FF6B35', '#5CE1E6', '#E879F9'];
      for (let i = 0; i < 18; i += 1) {
        const ang = (Math.PI * 0.25) + Math.random() * (Math.PI * 0.5);
        const speed = 110 + Math.random() * 210;
        this.particles.push({
          x: cx + (Math.random() - 0.5) * 16,
          y: cy + (Math.random() - 0.5) * 16,
          vx: (Math.random() - 0.35) * 160,
          vy: Math.sin(ang) * speed,
          gravity: 240,
          size: 1.8 + Math.random() * 1.8,
          color: palette[i % palette.length],
          age: 0,
          life: 0.42 + Math.random() * 0.38,
        });
      }
    }
    this.startLoop();
  }

  /* 6. Live Comms / World-Law Intercept Toast */
  showLawInterceptToast({ title = 'WORLD LAW INTERCEPT', message = '', badge = '⛨ LAW', accent = 'law' }) {
    if (!this.ensureMounted()) return;
    const toast = document.createElement('div');
    toast.className = `v2-vfx-comms-toast is-${accent}`;
    toast.innerHTML = `
      <div class="v2-vfx-comms-emblem">${badge}</div>
      <div class="v2-vfx-comms-body">
        <strong>${title}</strong>
        <p>${message}</p>
      </div>
    `;
    this.domLayer.appendChild(toast);
    setTimeout(() => {
      toast.classList.add('is-leaving');
      setTimeout(() => toast.remove(), 260);
    }, 3200);
  }

  /* Telemetry Delta Bar Flash */
  flashTelemetryDelta(key, deltaText = '+1') {
    const cell = document.querySelector(`.v2-prep-signal-cell[data-telemetry-key="${key}"]`);
    if (!cell) return;
    const deltaEl = cell.querySelector('.v2-prep-signal-delta');
    if (deltaEl) deltaEl.textContent = deltaText;
    cell.classList.remove('is-delta-flash');
    void cell.offsetWidth;
    cell.classList.add('is-delta-flash');
    const pips = cell.querySelectorAll('.v2-seg-pip');
    const firstUnlit = Array.from(pips).find((p) => !p.classList.contains('is-lit'));
    if (firstUnlit) firstUnlit.classList.add('is-delta');
    setTimeout(() => {
      cell.classList.remove('is-delta-flash');
      if (firstUnlit) firstUnlit.classList.remove('is-delta');
    }, 1100);
  }

  /* Validation / Intercept Shake */
  triggerValidationShake(el) {
    if (!el || typeof el.classList === 'undefined') return;
    el.classList.remove('v2-vfx-shake');
    void el.offsetWidth;
    el.classList.add('v2-vfx-shake');
    setTimeout(() => el.classList.remove('v2-vfx-shake'), 460);
  }
}

export const noirVfx = new NoirVfxDirector();
