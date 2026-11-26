/**
 * Unified NOIR Semantic FX Bus (VFX + SFX synchronized)
 */
import { noirVfx } from './vfx_engine.js';
import {
  playCue,
  playVictoryStinger,
  setMusicZone,
  setStemMix,
  pulseWriterTyping,
  startDriftLoop,
  stopDriftLoop,
} from './sound.js';

export const FX = {
  trigger(eventName, payload = {}) {
    switch (eventName) {
      case 'TAB_SWITCH':
        playCue('SFX_WIPE_RIBBON_SLASH', { gain: 0.65 });
        if (payload.zone) setMusicZone(payload.zone);
        break;
      case 'NODE_SELECT':
        playCue('SFX_UI_NODE_SELECT');
        if (payload.el) noirVfx.playSparkBurst?.(payload.el, payload.badgeText || 'Selected', false);
        break;
      case 'EXECUTE_CONFIRM':
        playCue('SFX_UI_EXECUTE_CONFIRM');
        noirVfx.playSparkBurst?.(payload.el || document.body, payload.badgeText || 'Confirmed', false);
        break;
      case 'LOCK_FREEZE':
        playCue('SFX_COMPONENT_LOCK_INSTALL');
        noirVfx.playSparkBurst?.(payload.el || document.body, payload.badgeText || 'Hard Lock', true);
        break;
      case 'PROC_SWEEP':
        playCue('SFX_PROC_UPGRADE_SWEEP');
        if (payload.el) noirVfx.playEnergySweep?.(payload.el, payload.label || 'Processing...');
        break;
      case 'COMET_IMPACT':
        playCue('SFX_VFX_COMET_IMPACT');
        if (payload.key) noirVfx.flashTelemetryDelta?.(payload.key, payload.delta || '+1');
        break;
      case 'RETICLE_LOCK':
        playCue('SFX_RETICLE_LOCKON_PING');
        if (payload.el) noirVfx.playSparkBurst?.(payload.el, payload.badgeText || 'Locked', false);
        break;
      case 'TIMELINE_ADVANCE':
        playCue('SFX_TIMELINE_DAY_ADVANCE');
        break;
      case 'STANDBY_WHOOSH':
        playCue('SFX_LOADING_PREP_WHOOSH');
        break;
      case 'COOK_START':
        playCue('SFX_PROC_UPGRADE_SWEEP');
        setMusicZone('ontrack_main');
        startDriftLoop();
        noirVfx.playOverdriveCharge?.(payload.el || document.body, payload.label || 'OVERDRIVE');
        break;
      case 'FINAL_LAP':
        playCue('SFX_FINAL_LAP_ESCALATION');
        setMusicZone('ontrack_final');
        break;
      case 'COOK_COMPLETE':
        stopDriftLoop();
        playCue('SFX_BANNER_COMPLETE_STINGER');
        setMusicZone('nontrack');
        noirVfx.playMilestoneRibbon?.(
          payload.title || 'COOK COMPLETE',
          payload.subtitle || 'Canon & style guards verified',
        );
        break;
      case 'SIM_COUNTDOWN':
        playCue('SFX_SIM_COUNTDOWN_BEEP');
        setMusicZone('ontrack_grid');
        break;
      case 'SIM_IGNITION':
        playCue('SFX_SIM_LAUNCH_IGNITION');
        setMusicZone('ontrack_main');
        noirVfx.playSparkBurst?.(payload.el || document.body, payload.badgeText || 'SIMULATION IGNITION', false);
        break;
      case 'OVERDRIVE_SURGE':
        playCue('SFX_OVERDRIVE_BOOST_SURGE');
        noirVfx.playOverdriveCharge?.(payload.el || document.body, payload.label || 'OVERDRIVE SURGE');
        break;
      case 'ORB_READY':
        playCue('SFX_ORB_CHARGE_READY');
        break;
      case 'FINISH_TRIUMPH':
        stopDriftLoop();
        playCue('SFX_FINISH_TRIUMPH_SLAM');
        playVictoryStinger();
        noirVfx.playMilestoneRibbon?.(
          payload.title || 'CHAPTER FINISHED',
          payload.subtitle || 'All beats converged & mastered',
        );
        break;
      case 'COMMS_TOAST':
        playCue('SFX_COMMS_TOAST_BLIP');
        noirVfx.showLawInterceptToast?.(payload);
        break;
      case 'LAW_INTERCEPT':
        playCue('SFX_IMPACT_ENERGY_HIT');
        playCue('SFX_COMMS_TOAST_BLIP', { gain: 0.7 });
        noirVfx.showLawInterceptToast?.(payload);
        if (payload.el) noirVfx.triggerValidationShake?.(payload.el);
        break;
      case 'VALIDATION_ERROR':
        playCue('SFX_IMPACT_ENERGY_HIT');
        if (payload.el) noirVfx.triggerValidationShake?.(payload.el);
        break;
      case 'TELEMETRY_DELTA':
        playCue('SFX_TALLY_SCORE_TICK', { gain: 0.5 });
        if (payload.key) noirVfx.flashTelemetryDelta?.(payload.key, payload.delta || '+1');
        break;
      case 'DRIFT_START':
        startDriftLoop();
        break;
      case 'DRIFT_STOP':
        stopDriftLoop();
        break;
      case 'WRITER_TYPING':
        pulseWriterTyping();
        break;
      case 'STEM_MIX':
        setStemMix(payload);
        break;
      default:
        playCue('SFX_UI_TAB_TICK', { gain: 0.6 });
    }
  },
};

window.NOIR_FX = FX;
