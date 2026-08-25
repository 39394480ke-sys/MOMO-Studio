import {
  CirclePause,
  CirclePlay,
  Eye,
  FolderPlus,
  PanelRightOpen,
  Radio,
  RotateCcw,
  ShieldCheck,
  Square,
} from 'lucide-react';

import type {
  MotionEntity,
  MotionDraftValidation,
  MotionKeyframe,
  MotionCommandStatus,
  PlaybackStatus,
  RobotStatus,
  TcpPose,
  TrajectoryPreflightReport,
  TrajectoryPreview as TrajectoryPreviewData,
} from '../../api/types';
import { TrajectoryPreview } from '../library/TrajectoryPreview';

interface StudioViewerProps {
  action: string | null;
  compileDisabledReason: string | null;
  compileError: string | null;
  currentTcp: TcpPose | null;
  currentTcpError: string | null;
  draftPreflight: TrajectoryPreflightReport | null;
  draftValidation: MotionDraftValidation | null;
  frameLimitReached: boolean;
  motionDisabledReason: string | null;
  playbackDisabledReason: string | null;
  playback: PlaybackStatus | null;
  playbackPreflight: TrajectoryPreflightReport | null;
  preview: TrajectoryPreviewData | null;
  robot: RobotStatus | null;
  runtimeMode: 'DRY RUN' | 'REAL';
  savedMotion: MotionEntity | null;
  savedMotionCurrent: boolean;
  selectedFrame: MotionKeyframe | null;
  studioCommand: MotionCommandStatus | null;
  validateDisabledReason: string | null;
  onAddPose: () => void;
  onCapture: () => void;
  onCompile: () => void;
  onOpenInspector: () => void;
  onPause: () => void;
  onPlay: () => void;
  onPreparePlayback: () => void;
  onResume: () => void;
  onStop: () => void;
  onValidate: () => void;
}

function fixed(value: number | undefined, digits = 1): string {
  return value === undefined || !Number.isFinite(value) ? '—' : value.toFixed(digits);
}

export function StudioViewer({
  action,
  compileDisabledReason,
  compileError,
  currentTcp,
  currentTcpError,
  draftPreflight,
  draftValidation,
  frameLimitReached,
  motionDisabledReason,
  playbackDisabledReason,
  playback,
  playbackPreflight,
  preview,
  robot,
  runtimeMode,
  savedMotion,
  savedMotionCurrent,
  selectedFrame,
  studioCommand,
  validateDisabledReason,
  onAddPose,
  onCapture,
  onCompile,
  onOpenInspector,
  onPause,
  onPlay,
  onPreparePlayback,
  onResume,
  onStop,
  onValidate,
}: StudioViewerProps) {
  const selectedTcp = selectedFrame?.pose_snapshot.tcp_pose;
  const state = playback?.state ?? 'IDLE';
  const playbackBelongsHere = Boolean(
    savedMotion && (!playback?.motion_id || playback.motion_id === savedMotion.id),
  );
  const playbackPrepared = Boolean(
    savedMotion &&
    playbackPreflight?.passed &&
    savedMotionCurrent &&
    playbackPreflight.digest &&
    playbackPreflight.motion_id === savedMotion.id &&
    playbackPreflight.motion_revision === savedMotion.revision &&
    playback?.state === 'READY' &&
    playback.trajectory_digest === playbackPreflight.digest,
  );
  const playbackActive =
    state === 'PREFLIGHTING' || state === 'READY' || state === 'PLAYING' || state === 'PAUSED';
  const stopAvailable =
    action === 'prepare-playback' ||
    playbackActive;
  const foreignPlaybackActive = playbackActive && !playbackBelongsHere;
  const studioCommandActive = Boolean(
    studioCommand &&
    ['ACCEPTED', 'PREFLIGHTING', 'READY', 'RUNNING', 'PLAYING', 'PAUSED', 'STOPPING'].includes(studioCommand.state),
  );
  const priorityStopAvailable = stopAvailable || action === 'goto' || studioCommandActive;
  const busy = action !== null;

  return (
    <section aria-labelledby="studio-viewer-heading" className="studio-viewer">
      <header className="studio-panel-heading">
        <div>
          <p className="section-kicker">{runtimeMode === 'REAL' ? 'Real capability' : 'Dry Run'} viewer</p>
          <h2 id="studio-viewer-heading">Robot state & trajectory</h2>
        </div>
        <div className="studio-viewer__badges">
          <span className="dry-run-badge">{runtimeMode}</span>
          <span className={`playback-state playback-state--${state.toLowerCase()}`}>{state}</span>
          <button
            aria-label="Open keyframe Inspector"
            className="mini-command studio-viewer__inspector-button"
            disabled={!selectedFrame}
            onClick={onOpenInspector}
            type="button"
          >
            <PanelRightOpen aria-hidden="true" />
          </button>
        </div>
      </header>

      <div className="studio-viewer__overview">
        <section aria-label={`Current ${runtimeMode} robot`} className="studio-viewer-card">
          <span>Current robot</span>
          <strong>{robot ? `${robot.variant} · ${robot.connection_state}` : 'Unavailable'}</strong>
          <small>
            {robot ? `${Object.keys(robot.positions).length} enabled joints · state ${robot.state_sequence}` : 'Backend state required'}
          </small>
          <div className="studio-viewer-card__actions">
            <button
              className="command-button command-button--primary"
              disabled={busy || motionDisabledReason !== null || frameLimitReached}
              onClick={onCapture}
              title={frameLimitReached
                ? 'The draft has reached the 1000-keyframe limit'
                : motionDisabledReason ?? 'Capture one coherent backend-owned snapshot'}
              type="button"
            >
              <Radio aria-hidden="true" /> {action === 'capture' ? 'Capturing…' : 'Capture current'}
            </button>
            <button className="command-button" disabled={busy || frameLimitReached} onClick={onAddPose} type="button">
              <FolderPlus aria-hidden="true" /> Add Pose
            </button>
          </div>
          {motionDisabledReason ? <small>Capture unavailable · {motionDisabledReason}</small> : null}
          {frameLimitReached ? <small>Capture and insert unavailable · 1000-keyframe draft limit reached</small> : null}
          {currentTcp ? (
            <dl className="studio-viewer-tcp" aria-label="Current robot TCP">
              <div><dt>X</dt><dd>{fixed(currentTcp.position_mm.x)} mm</dd></div>
              <div><dt>Y</dt><dd>{fixed(currentTcp.position_mm.y)} mm</dd></div>
              <div><dt>Z</dt><dd>{fixed(currentTcp.position_mm.z)} mm</dd></div>
            </dl>
          ) : <small>{currentTcpError ?? 'Waiting for current backend FK.'}</small>}
        </section>

        <section aria-label="Selected keyframe TCP" className="studio-viewer-card">
          <span>Selected keyframe</span>
          <strong>{selectedFrame?.label ?? 'None selected'}</strong>
          {selectedTcp ? (
            <dl className="studio-viewer-tcp">
              <div><dt>X</dt><dd>{fixed(selectedTcp.position_mm.x)} mm</dd></div>
              <div><dt>Y</dt><dd>{fixed(selectedTcp.position_mm.y)} mm</dd></div>
              <div><dt>Z</dt><dd>{fixed(selectedTcp.position_mm.z)} mm</dd></div>
            </dl>
          ) : (
            <small>Select a keyframe on the Timeline.</small>
          )}
        </section>

        <section aria-label="Compiled trajectory summary" className="studio-viewer-card">
          <span>Draft compile</span>
          <strong>
            {draftPreflight
              ? draftPreflight.passed
                ? 'Preflight passed'
                : 'Preflight rejected'
              : 'Not compiled'}
          </strong>
          <small>
            {draftPreflight
              ? `${draftPreflight.segment_count} segments · ${draftPreflight.sample_count} samples · ${fixed(draftPreflight.duration_s, 2)} s`
              : 'Backend compiler is the only interpolation source.'}
          </small>
          <div className="studio-viewer-card__actions">
            <button
              className="command-button"
              disabled={busy || validateDisabledReason !== null}
              onClick={onValidate}
              title={validateDisabledReason ?? 'Validate the persisted draft boundary'}
              type="button"
            >
              <ShieldCheck aria-hidden="true" /> {action === 'validate' ? 'Validating…' : 'Validate draft'}
            </button>
            <button
              className="command-button"
              disabled={busy || compileDisabledReason !== null}
              onClick={onCompile}
              title={compileDisabledReason ?? 'Validate and compile a bounded, non-executable draft preview'}
              type="button"
            >
              <Eye aria-hidden="true" /> {action === 'compile' ? 'Compiling…' : 'Compile preview'}
            </button>
          </div>
          {validateDisabledReason ? <small>Validate unavailable · {validateDisabledReason}</small> : null}
          {compileDisabledReason ? <small>Compile unavailable · {compileDisabledReason}</small> : null}
        </section>
      </div>

      {compileError ? <p className="playback-error" role="alert">{compileError}</p> : null}

      {draftValidation ? (
        <section
          aria-label="Studio draft validation result"
          className={draftValidation.valid ? 'preflight-report preflight-report--passed' : 'preflight-report'}
        >
          <header>
            <strong>{draftValidation.valid ? 'Draft structure is valid' : 'Draft structure needs attention'}</strong>
            <code>draft rev {draftValidation.draft_revision}</code>
          </header>
          {draftValidation.issues.length > 0 ? (
            <ul className="studio-compile-issues">
              {draftValidation.issues.map((issue, index) => (
                <li key={`${issue.code}-${index}`}><code>{issue.code}</code> {issue.message}</li>
              ))}
            </ul>
          ) : <small className="studio-non-executable-note">Validation does not make a draft executable.</small>}
        </section>
      ) : null}

      {draftPreflight ? (
        <section
          aria-label="Studio draft preflight result"
          className={draftPreflight.passed ? 'preflight-report preflight-report--passed' : 'preflight-report'}
        >
          <header>
            <strong>{draftPreflight.passed ? 'Draft path accepted' : 'Draft path rejected'}</strong>
            <code>{draftPreflight.digest ?? 'no digest'}</code>
          </header>
          <dl className="preflight-metrics">
            <div><dt>Duration</dt><dd>{fixed(draftPreflight.duration_s, 2)} s</dd></div>
            <div><dt>Segments</dt><dd>{draftPreflight.segment_count}</dd></div>
            <div><dt>Samples</dt><dd>{draftPreflight.sample_count}</dd></div>
            <div><dt>Rate</dt><dd>{draftPreflight.sample_rate_hz} Hz</dd></div>
          </dl>
          {draftPreflight.violations.length > 0 ? (
            <ul className="studio-compile-issues">
              {draftPreflight.violations.map((violation, index) => (
                <li key={`${violation.code}-${index}`}>
                  <code>{violation.code}</code> {violation.message}
                </li>
              ))}
            </ul>
          ) : null}
          {draftPreflight.checks.length > 0 ? (
            <details className="preflight-checks">
              <summary>Compiler checks ({draftPreflight.checks.length})</summary>
              <ul>
                {draftPreflight.checks.map((check, index) => (
                  <li key={`${check.name}-${index}`}>
                    <strong>{check.passed ? 'Passed' : 'Failed'} · {check.name}</strong>
                    <span>{check.detail}</span>
                  </li>
                ))}
              </ul>
            </details>
          ) : null}
          <small className="studio-non-executable-note">
            Draft preview is non-executable. Save it as a formal Motion, then run the normal digest-bound playback preflight.
          </small>
        </section>
      ) : null}

      {preview ? <TrajectoryPreview preview={preview} /> : null}

      <section aria-labelledby="studio-playback-heading" className="studio-playback">
        <header>
          <div>
            <p className="section-kicker">Saved Motion only</p>
            <h3 id="studio-playback-heading">{runtimeMode === 'REAL' ? 'Authorized Real' : 'Dry Run'} playback</h3>
          </div>
          <span>{savedMotion ? `${savedMotion.name} · rev ${savedMotion.revision}` : 'Save required'}</span>
        </header>
        <div className="studio-playback__buttons">
          <button
            className="command-button"
            disabled={busy || !savedMotion || !savedMotionCurrent || playbackDisabledReason !== null || stopAvailable || studioCommandActive}
            onClick={onPreparePlayback}
            title={!savedMotion
              ? 'Save this draft as a formal Motion first'
              : !savedMotionCurrent
                ? 'Save the current edits before preparing playback'
                : 'Run immutable Motion playback preflight'}
            type="button"
          >
            <ShieldCheck aria-hidden="true" /> {action === 'prepare-playback' ? 'Preparing…' : 'Prepare playback'}
          </button>
          <button
            className="command-button command-button--primary"
            disabled={busy || !playbackPrepared || playbackDisabledReason !== null}
            onClick={onPlay}
            title={playbackPrepared
              ? `Play the prepared trajectory through the ${runtimeMode === 'REAL' ? 'Real capability' : 'Dry Run'} gateway`
              : 'Prepare playback first'}
            type="button"
          >
            <CirclePlay aria-hidden="true" /> Play
          </button>
          <button className="command-button" disabled={busy || !playbackBelongsHere || state !== 'PLAYING'} onClick={onPause} type="button">
            <CirclePause aria-hidden="true" /> Pause
          </button>
          <button className="command-button" disabled={busy || !playbackBelongsHere || state !== 'PAUSED'} onClick={onResume} type="button">
            <RotateCcw aria-hidden="true" /> Resume
          </button>
          <button className="command-button command-button--danger" disabled={action === 'stop' || !priorityStopAvailable} onClick={onStop} type="button">
            <Square aria-hidden="true" /> Stop
          </button>
        </div>
        {savedMotion && !savedMotionCurrent ? (
          <p className="studio-field-note">Playback preparation is locked until current edits are saved. An already active immutable playback can still be stopped.</p>
        ) : null}
        {foreignPlaybackActive ? (
          <p className="studio-field-note">Another immutable Motion owns the active playback session. Editing controls stay isolated; priority Stop remains available.</p>
        ) : null}
        {studioCommand ? (
          <p className="studio-field-note">Studio keyframe Goto · {studioCommand.state} · command {studioCommand.command_id}</p>
        ) : null}
        {playbackDisabledReason ? (
          <p className="studio-field-note">New playback actions unavailable · {playbackDisabledReason}</p>
        ) : null}
        <div className="studio-playback-progress" aria-live="polite">
          <progress aria-label="Studio playback progress" max="1" value={playbackBelongsHere ? playback?.progress ?? 0 : 0} />
          <span>{Math.round((playbackBelongsHere ? playback?.progress ?? 0 : 0) * 100)}%</span>
          <small>{runtimeMode === 'REAL'
            ? 'backend REAL_PLAYBACK capability required'
            : 'hardware_accessed=false · real preview rejected'}</small>
        </div>
      </section>
    </section>
  );
}
