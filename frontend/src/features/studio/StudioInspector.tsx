import {
  ArrowDownToLine,
  ArrowUpToLine,
  Copy,
  LocateFixed,
  RefreshCcw,
  Radio,
  Trash2,
  X,
} from 'lucide-react';
import { useEffect, useRef } from 'react';

import type { MotionEasing, MotionKeyframe, MotionMode } from '../../api/types';

interface StudioInspectorProps {
  busy: boolean;
  frame: MotionKeyframe | null;
  frameIndex: number;
  frameLimitReached: boolean;
  mobileOpen: boolean;
  motionDisabledReason: string | null;
  runtimeMode: 'DRY RUN' | 'REAL';
  onAddAfter: (frameId: string) => void;
  onAddBefore: (frameId: string) => void;
  onCaptureAfter: (frameId: string) => void;
  onCaptureBefore: (frameId: string) => void;
  onCloseMobile: () => void;
  onDelete: (frameId: string) => void;
  onDuplicate: (frameId: string) => void;
  onEasingChange: (frameId: string, easing: MotionEasing) => void;
  onGoto: (frameId: string) => void;
  onHoldChange: (frameId: string, holdS: number) => void;
  onLabelChange: (frameId: string, label: string) => void;
  onModeChange: (frameId: string, mode: MotionMode) => void;
  onReplace: (frameId: string) => void;
  onTransitionDurationChange: (frameId: string, durationS: number) => void;
}

function finite(value: number): string {
  return Number.isFinite(value) ? value.toFixed(2) : '—';
}

export function StudioInspector({
  busy,
  frame,
  frameIndex,
  frameLimitReached,
  mobileOpen,
  motionDisabledReason,
  runtimeMode,
  onAddAfter,
  onAddBefore,
  onCaptureAfter,
  onCaptureBefore,
  onCloseMobile,
  onDelete,
  onDuplicate,
  onEasingChange,
  onGoto,
  onHoldChange,
  onLabelChange,
  onModeChange,
  onReplace,
  onTransitionDurationChange,
}: StudioInspectorProps) {
  const inspectorRef = useRef<HTMLElement | null>(null);
  const closeRef = useRef(onCloseMobile);
  closeRef.current = onCloseMobile;
  const position = frame?.pose_snapshot.tcp_pose.position_mm;
  const orientation = frame?.pose_snapshot.tcp_pose.orientation_quaternion_xyzw;
  const transition = frame?.incoming_transition;

  useEffect(() => {
    if (!mobileOpen) return;
    const previousFocus = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    const inspector = inspectorRef.current;
    const focusable = () => Array.from(inspector?.querySelectorAll<HTMLElement>(
      'button:not(:disabled), input:not(:disabled), select:not(:disabled), [tabindex]:not([tabindex="-1"])',
    ) ?? []);
    const first = focusable()[0] ?? inspector;
    first?.focus();
    const onKeyDown = (event: globalThis.KeyboardEvent) => {
      if (event.key === 'Escape') {
        event.preventDefault();
        closeRef.current();
        return;
      }
      if (event.key !== 'Tab') return;
      const controls = focusable();
      if (controls.length === 0) {
        event.preventDefault();
        inspector?.focus();
        return;
      }
      const firstControl = controls[0];
      const lastControl = controls.at(-1);
      if (event.shiftKey && document.activeElement === firstControl) {
        event.preventDefault();
        lastControl?.focus();
      } else if (!event.shiftKey && document.activeElement === lastControl) {
        event.preventDefault();
        firstControl.focus();
      }
    };
    document.addEventListener('keydown', onKeyDown);
    return () => {
      document.removeEventListener('keydown', onKeyDown);
      previousFocus?.focus();
    };
  }, [mobileOpen]);

  return (
    <>
    <div aria-hidden="true" className={`studio-inspector-scrim${mobileOpen ? ' studio-inspector-scrim--open' : ''}`} onClick={onCloseMobile} />
    <aside
      aria-labelledby="studio-inspector-heading"
      aria-modal={mobileOpen ? 'true' : undefined}
      className={`studio-inspector${mobileOpen ? ' studio-inspector--mobile-open' : ''}`}
      ref={inspectorRef}
      role={mobileOpen ? 'dialog' : undefined}
      tabIndex={-1}
    >
      <header className="studio-panel-heading">
        <div>
          <p className="section-kicker">Keyframe details</p>
          <h2 id="studio-inspector-heading">Inspector</h2>
        </div>
        <button
          aria-label="Close Inspector"
          className="mini-command studio-inspector__close"
          onClick={onCloseMobile}
          type="button"
        >
          <X aria-hidden="true" />
        </button>
      </header>

      {!frame ? (
        <p className="studio-inspector-empty">Select a keyframe to inspect and edit its immutable snapshot metadata.</p>
      ) : (
        <div className="studio-inspector__body">
          <label className="studio-field">
            <span>Keyframe label</span>
            <input
              aria-label="Keyframe label"
              disabled={busy}
              maxLength={200}
              onChange={(event) => onLabelChange(frame.id, event.target.value)}
              value={frame.label}
            />
          </label>

          <div className="studio-field-grid">
            <label className="studio-field">
              <span>Hold</span>
              <span className="studio-number-field">
                <input
                  aria-label="Keyframe hold seconds"
                  disabled={busy}
                  max="600"
                  min="0"
                  onChange={(event) => onHoldChange(frame.id, Number(event.target.value))}
                  step="0.05"
                  type="number"
                  value={frame.hold_s}
                />
                <span>s</span>
              </span>
            </label>
            <label className="studio-field">
              <span>Incoming duration</span>
              <span className="studio-number-field">
                <input
                  aria-describedby={!transition ? 'first-frame-transition-note' : undefined}
                  aria-label="Incoming transition duration seconds"
                  disabled={busy || !transition}
                  max="600"
                  min="0.05"
                  onChange={(event) => onTransitionDurationChange(frame.id, Number(event.target.value))}
                  step="0.05"
                  type="number"
                  value={transition?.duration_s ?? 0}
                />
                <span>s</span>
              </span>
            </label>
          </div>
          {!transition ? (
            <p className="studio-field-note" id="first-frame-transition-note">
              The first keyframe has no incoming transition.
            </p>
          ) : null}

          <div className="studio-field-grid">
            <label className="studio-field">
              <span>Motion mode</span>
              <select
                aria-label="Incoming transition motion mode"
                disabled={busy || !transition}
                onChange={(event) => onModeChange(frame.id, event.target.value as MotionMode)}
                value={transition?.motion_mode ?? 'JOINT'}
              >
                <option value="JOINT">Joint</option>
                <option value="CARTESIAN_LINEAR">Cartesian Linear</option>
              </select>
            </label>
            <label className="studio-field">
              <span>Easing</span>
              <select
                aria-label="Incoming transition easing"
                disabled={busy || !transition}
                onChange={(event) => onEasingChange(frame.id, event.target.value as MotionEasing)}
                value={transition?.easing ?? 'SMOOTHSTEP'}
              >
                <option value="LINEAR">Linear</option>
                <option value="SMOOTHSTEP">Smoothstep</option>
                <option value="EASE_IN_OUT">Ease in/out</option>
              </select>
            </label>
          </div>

          <section className="studio-snapshot" aria-labelledby="studio-tcp-heading">
            <header>
              <strong id="studio-tcp-heading">TCP · {frame.pose_snapshot.tcp_pose.frame}</strong>
              <span>{frame.pose_snapshot.robot_variant}</span>
            </header>
            <dl>
              <div><dt>X</dt><dd>{finite(position?.x ?? Number.NaN)} mm</dd></div>
              <div><dt>Y</dt><dd>{finite(position?.y ?? Number.NaN)} mm</dd></div>
              <div><dt>Z</dt><dd>{finite(position?.z ?? Number.NaN)} mm</dd></div>
              <div className="studio-snapshot__wide">
                <dt>Quaternion XYZW</dt>
                <dd>
                  {finite(orientation?.x ?? Number.NaN)}, {finite(orientation?.y ?? Number.NaN)}, {finite(orientation?.z ?? Number.NaN)}, {finite(orientation?.w ?? Number.NaN)}
                </dd>
              </div>
            </dl>
          </section>

          <section className="studio-snapshot" aria-labelledby="studio-joints-heading">
            <header>
              <strong id="studio-joints-heading">Joint snapshot</strong>
              <span>{Object.keys(frame.pose_snapshot.joint_state.positions).length} enabled</span>
            </header>
            <dl>
              {Object.entries(frame.pose_snapshot.joint_state.positions).map(([jointId, value]) => (
                <div key={jointId}>
                  <dt>{jointId.toUpperCase()}</dt>
                  <dd>{finite(value)} {frame.pose_snapshot.joint_state.units[jointId]}</dd>
                </div>
              ))}
            </dl>
          </section>

          <dl className="studio-provenance">
            <div>
              <dt>Source Pose</dt>
              <dd>{frame.source_pose_id ?? 'Captured / embedded'}</dd>
            </div>
            <div>
              <dt>Captured</dt>
              <dd>{frame.pose_snapshot.captured_at}</dd>
            </div>
            <div>
              <dt>Profile</dt>
              <dd>{frame.pose_snapshot.profile_fingerprint}</dd>
            </div>
          </dl>

          <div className="studio-inspector__actions">
            <button className="command-button" disabled={busy || frameLimitReached} onClick={() => onAddBefore(frame.id)} type="button">
              <ArrowUpToLine aria-hidden="true" /> Add before
            </button>
            <button className="command-button" disabled={busy || frameLimitReached} onClick={() => onAddAfter(frame.id)} type="button">
              <ArrowDownToLine aria-hidden="true" /> Add after
            </button>
            <button className="command-button" disabled={busy || frameLimitReached} onClick={() => onDuplicate(frame.id)} type="button">
              <Copy aria-hidden="true" /> Duplicate
            </button>
            <button className="command-button" disabled={busy || frameLimitReached || motionDisabledReason !== null} onClick={() => onCaptureBefore(frame.id)} type="button">
              <Radio aria-hidden="true" /> Capture before
            </button>
            <button className="command-button" disabled={busy || frameLimitReached || motionDisabledReason !== null} onClick={() => onCaptureAfter(frame.id)} type="button">
              <Radio aria-hidden="true" /> Capture after
            </button>
            <button
              className="command-button command-button--primary"
              disabled={busy || motionDisabledReason !== null}
              onClick={() => onGoto(frame.id)}
              title={motionDisabledReason ?? `Send this snapshot through the ${runtimeMode === 'REAL' ? 'Real capability' : 'Dry Run'} gateway`}
              type="button"
            >
              <LocateFixed aria-hidden="true" /> {runtimeMode === 'REAL' ? 'Real' : 'Dry Run'} Goto
            </button>
            <button
              className="command-button"
              disabled={busy || motionDisabledReason !== null}
              onClick={() => onReplace(frame.id)}
              title={motionDisabledReason ?? `Replace with a coherent current ${runtimeMode} snapshot`}
              type="button"
            >
              <RefreshCcw aria-hidden="true" /> Replace current
            </button>
            <button className="command-button command-button--danger" disabled={busy} onClick={() => onDelete(frame.id)} type="button">
              <Trash2 aria-hidden="true" /> Delete
            </button>
          </div>
          <p className="studio-field-note">Keyframe {frameIndex + 1} · snapshot data remains embedded and independent of its source Pose.</p>
          {motionDisabledReason ? <p className="studio-field-note">Robot actions unavailable · {motionDisabledReason}</p> : null}
          {frameLimitReached ? <p className="studio-field-note">Insert and duplicate unavailable · 1000-keyframe draft limit reached.</p> : null}
        </div>
      )}
    </aside>
    </>
  );
}
