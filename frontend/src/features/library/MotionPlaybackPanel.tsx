import { CirclePause, CirclePlay, RotateCcw, ShieldCheck, Square } from 'lucide-react';

import type {
  MotionEntity,
  PlaybackStatus,
  TrajectoryPreflightReport,
  TrajectoryPreview as TrajectoryPreviewData,
} from '../../api/types';
import { playbackLocksLibrary } from './playbackState';
import { TrajectoryPreview } from './TrajectoryPreview';

const RATE_OPTIONS = [0.25, 0.5, 1, 1.5, 2] as const;

interface MotionPlaybackPanelProps {
  actionKey: string | null;
  disabledReason: string | null;
  error: string | null;
  loop: boolean;
  motion: MotionEntity;
  onLoopChange: (loop: boolean) => void;
  onDismissError: () => void;
  onPause: () => void;
  onPlay: () => void;
  onPreflight: () => void;
  onRateChange: (rate: number) => void;
  onResume: () => void;
  onStop: () => void;
  playback: PlaybackStatus | null;
  preflight: TrajectoryPreflightReport | null;
  preview: TrajectoryPreviewData | null;
  previewLoading: boolean;
  rate: number;
  stopDisabled: boolean;
}

function seconds(value: number): string {
  return `${value.toFixed(2)} s`;
}

export function MotionPlaybackPanel({
  actionKey,
  disabledReason,
  error,
  loop,
  motion,
  onLoopChange,
  onDismissError,
  onPause,
  onPlay,
  onPreflight,
  onRateChange,
  onResume,
  onStop,
  playback,
  preflight,
  preview,
  previewLoading,
  rate,
  stopDisabled,
}: MotionPlaybackPanelProps) {
  const actionBusy = actionKey !== null;
  const playbackBelongsHere = !playback?.motion_id || playback.motion_id === motion.id;
  const relevantPlayback = playbackBelongsHere ? playback : null;
  const foreignPlaybackActive = !playbackBelongsHere && playbackLocksLibrary(playback);
  const state = relevantPlayback?.state ?? 'IDLE';
  const sessionActive = playbackLocksLibrary(relevantPlayback);
  const hasPreparedTrajectory = Boolean(
    preflight?.passed &&
    preflight.digest &&
    preflight.motion_id === motion.id &&
    preflight.motion_revision === motion.revision,
  );
  const keyframeLabel = motion.keyframes.find(
    (keyframe) => keyframe.id === relevantPlayback?.current_keyframe_id,
  )?.label;
  const progress = relevantPlayback?.progress ?? 0;
  const displayedDuration = relevantPlayback?.motion_id === motion.id
    ? relevantPlayback.duration_s
    : preflight?.duration_s ?? 0;
  const preflightDisabled = actionBusy || disabledReason !== null || sessionActive || foreignPlaybackActive;
  const orchestrationReady = Boolean(
    state === 'READY' &&
    relevantPlayback?.session_id == null &&
    relevantPlayback?.motion_id === motion.id &&
    relevantPlayback?.trajectory_digest === preflight?.digest,
  );
  const playDisabled =
    actionBusy ||
    disabledReason !== null ||
    !hasPreparedTrajectory ||
    !orchestrationReady ||
    foreignPlaybackActive;
  const stopInFlight = actionKey === `stop-motion-${motion.id}`;
  const stopAvailable =
    state === 'PREFLIGHTING' ||
    state === 'READY' ||
    state === 'PLAYING' ||
    state === 'PAUSED';
  const optionsAvailable =
    state === 'IDLE' ||
    state === 'READY' ||
    state === 'PLAYING' ||
    state === 'PAUSED';
  const shownError = error ?? relevantPlayback?.error;

  return (
    <section aria-labelledby="motion-playback-heading" className="motion-playback-panel">
      <header>
        <div>
          <p className="section-kicker">Stage 5 safety workflow</p>
          <h4 id="motion-playback-heading">Preflight & playback</h4>
        </div>
        <span className={`playback-state playback-state--${state.toLowerCase()}`}>{state}</span>
      </header>

      <p className="motion-playback-panel__intro">
        Compile and verify the immutable Motion first. Playback remains inside the reviewed Dry Run gateway and never accesses hardware.
      </p>

      {disabledReason ? (
        <p className="playback-blocker" role="status">Playback unavailable · {disabledReason}</p>
      ) : null}
      {foreignPlaybackActive ? (
        <p className="playback-blocker" role="status">
          Another Motion ({playback?.motion_id}) owns the active playback session. Stop it before preparing this Motion.
        </p>
      ) : null}
      {shownError ? (
        <div className="playback-error" role="alert">
          <span>{shownError}</span>
          {error ? (
            <button
              aria-label="Dismiss playback error"
              className="command-button"
              onClick={onDismissError}
              type="button"
            >
              Dismiss
            </button>
          ) : null}
        </div>
      ) : null}

      <div className="preflight-actions">
        <button
          className="command-button command-button--primary"
          disabled={preflightDisabled}
          onClick={onPreflight}
          type="button"
        >
          <ShieldCheck aria-hidden="true" />
          {actionKey === `preflight-motion-${motion.id}` ? 'Preflighting…' : 'Run preflight'}
        </button>
        <span>Revision {motion.revision} · bounded compiler sampling</span>
      </div>

      {preflight ? (
        <section
          aria-label="Preflight result"
          className={preflight.passed ? 'preflight-report preflight-report--passed' : 'preflight-report preflight-report--failed'}
        >
          <header>
            <strong>{preflight.passed ? 'Preflight passed' : 'Preflight rejected'}</strong>
            <code title={preflight.digest ?? 'No trajectory digest'}>{preflight.digest ?? 'no digest'}</code>
          </header>
          <dl className="preflight-metrics">
            <div><dt>Duration</dt><dd>{seconds(preflight.duration_s)}</dd></div>
            <div><dt>Segments</dt><dd>{preflight.segment_count}</dd></div>
            <div><dt>Samples</dt><dd>{preflight.sample_count}</dd></div>
            <div><dt>Sample rate</dt><dd>{preflight.sample_rate_hz} Hz</dd></div>
          </dl>
          {preflight.violations.length > 0 ? (
            <div className="preflight-violations">
              <strong>Violations</strong>
              <ul>
                {preflight.violations.map((violation, index) => (
                  <li key={`${violation.code}-${violation.segment_index ?? 'motion'}-${index}`}>
                    <code>{violation.code}</code>
                    <span>{violation.message}</span>
                    {violation.segment_index !== null && violation.segment_index !== undefined
                      ? <small>Segment {violation.segment_index + 1}</small>
                      : null}
                    {violation.keyframe_id ? <small>Keyframe {violation.keyframe_id}</small> : null}
                    {violation.check ? <small>Check {violation.check}</small> : null}
                    {violation.sample_index !== null && violation.sample_index !== undefined
                      ? <small>Sample {violation.sample_index}</small>
                      : null}
                    {violation.joint_id ? (
                      <small>
                        Joint {violation.joint_id}
                        {violation.actual !== null && violation.actual !== undefined
                          ? ` · actual ${violation.actual}${violation.unit ? ` ${violation.unit}` : ''}`
                          : ''}
                        {violation.limit !== null && violation.limit !== undefined
                          ? ` · limit ${violation.limit}${violation.unit ? ` ${violation.unit}` : ''}`
                          : ''}
                      </small>
                    ) : null}
                  </li>
                ))}
              </ul>
            </div>
          ) : null}
          {preflight.checks.length > 0 ? (
            <details className="preflight-checks">
              <summary>Safety checks · {preflight.checks.filter((check) => check.passed).length}/{preflight.checks.length} passed</summary>
              <ul>
                {preflight.checks.map((check, index) => (
                  <li key={`${check.name}-${index}`}>
                    <strong>{check.passed ? 'PASS' : 'FAIL'} · {check.name}</strong>
                    <span>{check.detail}</span>
                  </li>
                ))}
              </ul>
            </details>
          ) : null}
        </section>
      ) : null}

      {previewLoading ? <p className="trajectory-loading" role="status">Loading bounded trajectory preview…</p> : null}
      {preview ? <TrajectoryPreview preview={preview} /> : null}

      <section aria-labelledby="playback-controls-heading" className="playback-controls">
        <header>
          <h5 id="playback-controls-heading">Playback controls</h5>
          <span>{hasPreparedTrajectory ? 'Prepared digest verified' : 'Preflight required'}</span>
        </header>
        <div className="playback-controls__buttons">
          <button className="command-button command-button--primary" disabled={playDisabled} onClick={onPlay} type="button">
            <CirclePlay aria-hidden="true" /> Play
          </button>
          <button className="command-button" disabled={actionBusy || state !== 'PLAYING' || disabledReason !== null} onClick={onPause} type="button">
            <CirclePause aria-hidden="true" /> Pause
          </button>
          <button className="command-button" disabled={actionBusy || state !== 'PAUSED' || disabledReason !== null} onClick={onResume} type="button">
            <RotateCcw aria-hidden="true" /> Resume
          </button>
          <button
            className="command-button command-button--danger"
            disabled={stopDisabled || stopInFlight || !stopAvailable}
            onClick={onStop}
            type="button"
          >
            <Square aria-hidden="true" /> Stop
          </button>
        </div>
        <div className="playback-options">
          <label>
            <span>Rate</span>
            <select
              aria-label="Playback rate"
              disabled={actionBusy || disabledReason !== null || foreignPlaybackActive || !optionsAvailable}
              onChange={(event) => onRateChange(Number(event.target.value))}
              value={rate}
            >
              {RATE_OPTIONS.map((option) => <option key={option} value={option}>{option}×</option>)}
            </select>
          </label>
          <label className="playback-loop-toggle">
            <input
              checked={loop}
              disabled={actionBusy || disabledReason !== null || foreignPlaybackActive || !optionsAvailable}
              onChange={(event) => onLoopChange(event.target.checked)}
              type="checkbox"
            />
            <span>Loop playback</span>
          </label>
        </div>

        <div aria-live="polite" className="playback-progress">
          <div>
            <strong>{state}</strong>
            <span>{Math.round(progress * 100)}%</span>
          </div>
          <progress aria-label="Playback progress" max={1} value={progress} />
          <dl>
            <div><dt>Elapsed</dt><dd>{seconds(relevantPlayback?.elapsed_s ?? 0)} / {seconds(displayedDuration)}</dd></div>
            <div><dt>Keyframe</dt><dd title={keyframeLabel ?? relevantPlayback?.current_keyframe_id ?? undefined}>{keyframeLabel ?? relevantPlayback?.current_keyframe_id ?? '—'}</dd></div>
            <div><dt>Segment</dt><dd>{relevantPlayback?.current_segment_index === null || relevantPlayback?.current_segment_index === undefined ? '—' : relevantPlayback.current_segment_index + 1}</dd></div>
            <div><dt>Sample</dt><dd>{relevantPlayback?.current_sample_index ?? '—'}</dd></div>
          </dl>
          <small>Rate {rate}× · {loop ? 'loop on' : 'loop off'} · hardware_accessed=false</small>
        </div>
      </section>
    </section>
  );
}
