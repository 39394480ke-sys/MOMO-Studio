import { AlertTriangle, Camera, CameraOff, Radar, ShieldCheck, Square } from 'lucide-react';

import type { VisionFollowConfiguration, VisionProviderCapability } from '../../api/types';
import type { VisionWorkspace } from './useVisionWorkspace';

function detectorFor(workspace: VisionWorkspace, kind: 'person' | 'face') {
  return workspace.capabilities?.detectors.find(
    (candidate) => `${candidate.provider_id} ${candidate.kind}`.toLowerCase().includes(kind),
  ) ?? null;
}

function updateNumber(
  workspace: VisionWorkspace,
  key: keyof VisionFollowConfiguration,
  value: number,
) {
  if (!Number.isFinite(value)) return;
  workspace.setConfiguration((current) => ({ ...current, [key]: value }));
}

function Capability({ capability }: { capability: VisionProviderCapability }) {
  return (
    <li className="vision-capability">
      <span
        aria-hidden="true"
        className={`vision-capability__dot${capability.available ? ' vision-capability__dot--available' : ''}`}
      />
      <div>
        <strong>{capability.provider_id}</strong>
        <span>{capability.available ? capability.active ? 'Active' : 'Available' : 'Unavailable'}</span>
        <small>Model source · {capability.model_source}</small>
        <small>Notice · {capability.notice}</small>
        {capability.reason ? <small>{capability.reason}</small> : null}
      </div>
    </li>
  );
}

function NumericControl({
  label,
  value,
  min,
  max,
  step,
  disabled = false,
  onChange,
}: {
  label: string;
  value: number;
  min: number;
  max: number;
  step: number;
  disabled?: boolean;
  onChange: (value: number) => void;
}) {
  return (
    <label className="vision-number-control">
      <span>{label}</span>
      <input
        aria-label={label}
        disabled={disabled}
        max={max}
        min={min}
        onChange={(event) => onChange(event.currentTarget.valueAsNumber)}
        step={step}
        type="number"
        value={value}
      />
    </label>
  );
}

export function VisionControls({ workspace }: { workspace: VisionWorkspace }) {
  const person = detectorFor(workspace, 'person');
  const face = detectorFor(workspace, 'face');
  const follow = workspace.status?.follow;
  const targetLocked = workspace.status?.tracking?.status === 'LOCKED';
  const robotConnected = workspace.status?.robot_state === 'CONNECTED';
  const sourceOperational = workspace.status?.source_state === 'READY'
    || workspace.status?.source_state === 'STREAMING';
  const liveCameraOpen = workspace.readOnlyLiveCamera && sourceOperational;
  const latestFrame = workspace.status?.latest_frame ?? null;
  const frameFresh = latestFrame !== null
    && latestFrame.age_ms <= workspace.configuration.frame_freshness_limit_s * 1000;
  const sourceAvailable = workspace.capabilities?.camera_access_policy !== 'DISABLED'
    && workspace.capabilities?.source.available === true
    && workspace.capabilities.stream.available;
  let detectionBlockReason: string | null = null;
  if (!workspace.online) detectionBlockReason = 'Backend unavailable';
  else if (!workspace.statusReachable) detectionBlockReason = 'Vision status unavailable';
  else if (!sourceAvailable) detectionBlockReason = 'Vision source unavailable';
  else if (workspace.streamFailed) detectionBlockReason = 'Vision stream disconnected';
  else if (!sourceOperational) detectionBlockReason = 'Vision source is not operational';
  else if (!frameFresh) detectionBlockReason = 'Wait for a fresh frame';
  let startReason: string | null = null;
  if (!workspace.followAllowed) {
    startReason = workspace.followBlockedReason ?? 'Backend capability is not authorized';
  } else if (!workspace.online) startReason = 'Backend unavailable';
  else if (!workspace.statusReachable) startReason = 'Vision status unavailable';
  else if (!workspace.capabilities) startReason = 'Provider capability is still loading';
  else if (
    workspace.runtimeMode === 'REAL' &&
    !workspace.capabilities.real_follow_allowed
  ) {
    startReason = workspace.capabilities.real_follow_blocked_reason;
  }
  else if (!sourceAvailable) startReason = 'Vision source or bounded stream is unavailable';
  else if (workspace.streamFailed) startReason = 'Vision stream is disconnected';
  else if (!workspace.mapping) startReason = 'Active Profile has no verified pan/tilt mapping';
  else if (!robotConnected) {
    startReason = workspace.runtimeMode === 'REAL'
      ? 'Backend reports the Real robot disconnected'
      : 'Connect the Dry Run robot';
  }
  else if (!sourceOperational) {
    startReason = `Vision source is ${workspace.status?.source_state ?? 'not ready'}`;
  } else if (!frameFresh) startReason = 'Wait for a fresh frame';
  else if (!targetLocked) startReason = 'Select and lock a fresh target';
  else if (follow?.active) startReason = 'Follow is already active';
  const startDisabled = startReason !== null || workspace.busy !== null;
  const stopAvailable = follow?.active || workspace.busy === 'start-follow';
  const tuningDisabled = workspace.readOnlyLiveCamera
    || follow?.active === true
    || workspace.busy === 'start-follow';

  return (
    <aside className="vision-controls" aria-label="Vision controls">
      <section className="vision-control-card">
        <div className="vision-control-card__heading">
          <ShieldCheck aria-hidden="true" />
          <div><p className="eyebrow">Access boundary</p><h2>Source & policy</h2></div>
        </div>
        <dl className="vision-definition-list">
          <div><dt>Source</dt><dd>{workspace.capabilities?.source.provider_id ?? 'Waiting'}</dd></div>
          <div><dt>Camera policy</dt><dd>{workspace.capabilities?.camera_access_policy ?? 'Unavailable'}</dd></div>
          <div><dt>Source state</dt><dd>{workspace.status?.source_state ?? (workspace.online ? 'Waiting' : 'OFFLINE')}</dd></div>
          <div><dt>Mode</dt><dd>{workspace.runtimeMode}</dd></div>
          <div>
            <dt>Live camera</dt>
            <dd>{workspace.readOnlyLiveCamera ? liveCameraOpen ? 'Open · read only' : 'Closed' : 'Not configured'}</dd>
          </div>
        </dl>
        {workspace.readOnlyLiveCamera ? (
          <>
            <div className="vision-follow-actions">
              <button
                className="command-button command-button--primary"
                disabled={!workspace.online || liveCameraOpen || workspace.busy !== null}
                onClick={() => void workspace.openCamera()}
                type="button"
              >
                <Camera aria-hidden="true" />
                {workspace.busy === 'open-camera' ? 'Opening…' : 'Open live camera'}
              </button>
              <button
                className="command-button"
                disabled={!liveCameraOpen || workspace.busy !== null}
                onClick={() => void workspace.closeCamera()}
                type="button"
              >
                <CameraOff aria-hidden="true" />
                {workspace.busy === 'close-camera' ? 'Closing…' : 'Close live camera'}
              </button>
            </div>
            <p className="vision-provider-note">
              Read-only preview only. Selection, detection, tracking, recording, and Follow remain disabled.
            </p>
          </>
        ) : null}
        <p className="vision-blocked-reason">
          {workspace.capabilities?.real_follow_blocked_reason
            ?? workspace.status?.real_follow_blocked_reason
            ?? 'Real Follow remains blocked pending field acceptance.'}
        </p>
      </section>

      <section className="vision-control-card">
        <div className="vision-control-card__heading">
          <Radar aria-hidden="true" />
          <div><p className="eyebrow">Target</p><h2>Select & detect</h2></div>
        </div>
        <div className="vision-button-grid">
          <button
            className="command-button"
            disabled={workspace.readOnlyLiveCamera || !workspace.status?.selection || workspace.busy !== null}
            onClick={() => void workspace.clearTarget()}
            type="button"
          >Clear selection</button>
          <button
            className="command-button"
            disabled={workspace.readOnlyLiveCamera || !workspace.status?.selection || workspace.busy !== null}
            onClick={() => void workspace.resetTracking()}
            type="button"
          >Reset tracker</button>
          <button
            className="command-button"
            disabled={workspace.readOnlyLiveCamera || !person?.available || detectionBlockReason !== null || workspace.busy !== null}
            onClick={() => void workspace.detect('person')}
            title={!person?.available
              ? person?.reason ?? 'Person provider unavailable'
              : detectionBlockReason ?? 'Detect a person in the exact current frame'}
            type="button"
          >Person detect</button>
          <button
            className="command-button"
            disabled={workspace.readOnlyLiveCamera || !face?.available || detectionBlockReason !== null || workspace.busy !== null}
            onClick={() => void workspace.detect('face')}
            title={!face?.available
              ? face?.reason ?? 'Face provider unavailable'
              : detectionBlockReason ?? 'Detect a face in the exact current frame'}
            type="button"
          >Face detect</button>
        </div>
        {!person?.available || !face?.available ? (
          <p className="vision-provider-note">Unavailable providers stay disabled; no model is downloaded automatically.</p>
        ) : null}
      </section>

      <section className="vision-control-card">
        <p className="eyebrow">Provider capability</p>
        <h2>Local providers</h2>
        <ul className="vision-capabilities">
          {workspace.capabilities ? (
            [workspace.capabilities.source, workspace.capabilities.stream, ...workspace.capabilities.trackers, ...workspace.capabilities.detectors]
              .map((capability) => <Capability capability={capability} key={`${capability.kind}-${capability.provider_id}`} />)
          ) : <li className="vision-capability vision-capability--empty">Waiting for capability discovery</li>}
        </ul>
      </section>

      <section className="vision-control-card">
        <p className="eyebrow">{workspace.runtimeMode === 'REAL' ? 'Real capability controller' : 'Dry Run controller'}</p>
        <h2>Follow tuning</h2>
        <div className="vision-follow-grid">
          <NumericControl disabled={tuningDisabled} label="EMA alpha" min={0.05} max={1} step={0.05} value={workspace.configuration.ema_alpha} onChange={(value) => updateNumber(workspace, 'ema_alpha', value)} />
          <NumericControl disabled={tuningDisabled} label="Dead zone X" min={0} max={0.4} step={0.01} value={workspace.configuration.dead_zone_x} onChange={(value) => updateNumber(workspace, 'dead_zone_x', value)} />
          <NumericControl disabled={tuningDisabled} label="Dead zone Y" min={0} max={0.4} step={0.01} value={workspace.configuration.dead_zone_y} onChange={(value) => updateNumber(workspace, 'dead_zone_y', value)} />
          <NumericControl disabled={tuningDisabled} label="Gain" min={0.05} max={2} step={0.05} value={workspace.configuration.gain} onChange={(value) => updateNumber(workspace, 'gain', value)} />
          <NumericControl disabled={tuningDisabled} label="Max step" min={0.1} max={10} step={0.1} value={workspace.configuration.max_step} onChange={(value) => updateNumber(workspace, 'max_step', value)} />
          <NumericControl disabled={tuningDisabled} label="Max rate" min={0.2} max={20} step={0.1} value={workspace.configuration.max_rate} onChange={(value) => updateNumber(workspace, 'max_rate', value)} />
        </div>
        {tuningDisabled ? <p className="vision-provider-note">Tuning is locked for the active lease.</p> : null}
        <dl className="vision-error-readout" aria-label="Follow error readout">
          <div><dt>Error X / Y</dt><dd>{follow?.error_x?.toFixed(3) ?? '—'} / {follow?.error_y?.toFixed(3) ?? '—'}</dd></div>
          <div><dt>EMA X / Y</dt><dd>{follow?.ema_error_x?.toFixed(3) ?? '—'} / {follow?.ema_error_y?.toFixed(3) ?? '—'}</dd></div>
          <div><dt>Mapping</dt><dd>{workspace.mapping ? `${workspace.mapping.pan_joint} / ${workspace.mapping.tilt_joint}` : 'Unavailable'}</dd></div>
          <div><dt>Mapping status</dt><dd>{workspace.mapping?.verification_status ?? 'Unavailable'}</dd></div>
        </dl>
        <div className="vision-follow-actions">
          <button
            className="command-button command-button--primary"
            disabled={startDisabled}
            onClick={() => void workspace.startFollow()}
            title={startReason ?? `Start a lease-bound ${workspace.runtimeMode === 'REAL' ? 'Real' : 'Dry Run'} Follow session`}
            type="button"
          >Start {workspace.runtimeMode === 'REAL' ? 'Real' : 'Dry Run'} Follow</button>
          <button
            className="command-button command-button--stop"
            disabled={!stopAvailable || workspace.busy === 'stop-follow'}
            onClick={() => void workspace.stopFollow()}
            type="button"
          ><Square aria-hidden="true" /> Stop Follow</button>
        </div>
        {startReason && !follow?.active ? <p className="vision-disabled-reason">Follow unavailable · {startReason}</p> : null}
        {follow?.stop_reason ? <p className="vision-stop-reason">Last stop · {follow.stop_reason}</p> : null}
      </section>

      {workspace.error ? (
        <div className="vision-error" role="alert">
          <AlertTriangle aria-hidden="true" />
          <span>{workspace.error}</span>
          <button aria-label="Dismiss Vision error" onClick={workspace.clearError} type="button">×</button>
        </div>
      ) : null}
    </aside>
  );
}
