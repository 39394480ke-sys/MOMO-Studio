import { Crosshair, ScanSearch } from 'lucide-react';

import type {
  CartesianFrame,
  ForwardKinematicsResponse,
  InverseKinematicsResponse,
  Vector3,
} from '../../api/types';
import { quaternionToRpyDegrees } from './controlMath';
import type { ControlParameters, MotionAvailability, PoseEditorValue } from './controlTypes';

type Axis = keyof Vector3;

interface CartesianControlPanelProps {
  fk: ForwardKinematicsResponse | null;
  fkLoading: boolean;
  frame: CartesianFrame;
  target: PoseEditorValue;
  parameters: ControlParameters;
  availability: MotionAvailability;
  pending: string | null;
  motionLocked: boolean;
  ikPending: boolean;
  ikResult: InverseKinematicsResponse | null;
  ikError: string | null;
  onFrameChange: (frame: CartesianFrame) => void;
  onPositionChange: (axis: Axis, value: number) => void;
  onRotationChange: (axis: Axis, value: number) => void;
  onCartesianJog: (kind: 'translation' | 'rotation', axis: Axis, direction: -1 | 1) => Promise<void>;
  onSolveIk: () => Promise<void>;
  onMovePose: () => Promise<void>;
}

function TcpSummary({ fk }: { fk: ForwardKinematicsResponse | null }) {
  if (!fk) return <p className="empty-state">Waiting for current FK from the backend.</p>;
  const position = fk.tcp_pose.position_mm;
  const orientation = fk.tcp_pose.orientation_quaternion_xyzw;
  const rotation = quaternionToRpyDegrees(orientation);
  return (
    <dl className="tcp-summary">
      <div>
        <dt>XYZ</dt>
        <dd>{position.x.toFixed(2)}, {position.y.toFixed(2)}, {position.z.toFixed(2)} mm</dd>
      </div>
      <div>
        <dt>Quaternion XYZW</dt>
        <dd>{orientation.x.toFixed(4)}, {orientation.y.toFixed(4)}, {orientation.z.toFixed(4)}, {orientation.w.toFixed(4)}</dd>
      </div>
      <div>
        <dt>RPY</dt>
        <dd>{rotation.x.toFixed(2)}, {rotation.y.toFixed(2)}, {rotation.z.toFixed(2)} deg</dd>
      </div>
      <div>
        <dt>State sequence</dt>
        <dd>{fk.state_sequence}</dd>
      </div>
      <div>
        <dt>Kinematics</dt>
        <dd><code>{fk.kinematics_fingerprint.slice(0, 12)}…</code></dd>
      </div>
    </dl>
  );
}

function JogAxisGroup({
  title,
  kind,
  disabled,
  onJog,
}: {
  title: string;
  kind: 'translation' | 'rotation';
  disabled: boolean;
  onJog: CartesianControlPanelProps['onCartesianJog'];
}) {
  const labels: Record<Axis, string> = kind === 'translation'
    ? { x: 'X', y: 'Y', z: 'Z' }
    : { x: 'Rx', y: 'Ry', z: 'Rz' };
  return (
    <fieldset className="cartesian-jog-group" disabled={disabled}>
      <legend>{title}</legend>
      {(['x', 'y', 'z'] as const).map((axis) => (
        <div key={axis}>
          <span>{labels[axis]}</span>
          <button
            aria-label={`Jog ${labels[axis]} negative`}
            onClick={() => void onJog(kind, axis, -1)}
            type="button"
          >−</button>
          <button
            aria-label={`Jog ${labels[axis]} positive`}
            onClick={() => void onJog(kind, axis, 1)}
            type="button"
          >+</button>
        </div>
      ))}
    </fieldset>
  );
}

export function CartesianControlPanel({
  fk,
  fkLoading,
  frame,
  target,
  parameters,
  availability,
  pending,
  motionLocked,
  ikPending,
  ikResult,
  ikError,
  onFrameChange,
  onPositionChange,
  onRotationChange,
  onCartesianJog,
  onSolveIk,
  onMovePose,
}: CartesianControlPanelProps) {
  const disabled = !availability.allowed || pending !== null || motionLocked || !fk;
  return (
    <section className="control-panel control-panel--cartesian" aria-labelledby="cartesian-title">
      <div className="section-heading section-heading--compact">
        <div>
          <p className="section-kicker">TCP / Cartesian</p>
          <h2 id="cartesian-title">Pose and jog</h2>
        </div>
        <div className="frame-selector" aria-label="Cartesian reference frame">
          {(['BASE', 'TOOL'] as const).map((candidate) => (
            <button
              aria-pressed={frame === candidate}
              className={frame === candidate ? 'frame-selector__active' : ''}
              disabled={disabled}
              key={candidate}
              onClick={() => onFrameChange(candidate)}
              type="button"
            >{candidate}</button>
          ))}
        </div>
      </div>

      {fkLoading && !fk ? <p className="inline-status">Computing current FK…</p> : <TcpSummary fk={fk} />}

      <div className="cartesian-jog-grid">
        <JogAxisGroup disabled={disabled} kind="translation" onJog={onCartesianJog} title="Position jog · mm" />
        <JogAxisGroup disabled={disabled} kind="rotation" onJog={onCartesianJog} title="Orientation jog · deg" />
      </div>
      <p className="control-hint">
        {frame} increments: {parameters.cartesianStepMm} mm translation and {parameters.rotationStepDeg} deg rotation.
      </p>

      <div className="pose-editor">
        <fieldset>
          <legend>Target position · mm</legend>
          {(['x', 'y', 'z'] as const).map((axis) => (
            <label key={axis}>{axis.toUpperCase()}
              <input
                aria-label={`Target ${axis.toUpperCase()} (mm)`}
                disabled={disabled}
                onChange={(event) => onPositionChange(axis, event.currentTarget.valueAsNumber)}
                step="0.1"
                type="number"
                value={target.positionMm[axis]}
              />
            </label>
          ))}
        </fieldset>
        <fieldset>
          <legend>Target RPY · deg</legend>
          {(['x', 'y', 'z'] as const).map((axis, index) => (
            <label key={axis}>{['Roll', 'Pitch', 'Yaw'][index]}
              <input
                aria-label={`Target ${['roll', 'pitch', 'yaw'][index]} (deg)`}
                disabled={disabled}
                onChange={(event) => onRotationChange(axis, event.currentTarget.valueAsNumber)}
                step="0.1"
                type="number"
                value={target.rotationDeg[axis]}
              />
            </label>
          ))}
        </fieldset>
      </div>

      <div className="panel-actions">
        <button
          className="command-button"
          disabled={disabled || ikPending}
          onClick={() => void onSolveIk()}
          type="button"
        >
          <ScanSearch aria-hidden="true" /> {ikPending ? 'Solving…' : 'Check IK'}
        </button>
        <button
          className="command-button command-button--primary"
          disabled={disabled}
          onClick={() => void onMovePose()}
          type="button"
        >
          <Crosshair aria-hidden="true" /> {pending === 'move-pose' ? 'Submitting…' : 'Move Pose'}
        </button>
      </div>

      {ikResult ? (
        <div className={`ik-result ik-result--${ikResult.success ? 'success' : 'failure'}`} role="status">
          <strong>{ikResult.success ? 'IK reachable' : 'IK not reachable'}</strong>
          <span>{ikResult.termination_reason}</span>
          <span>Position residual {ikResult.position_error_mm.toFixed(3)} mm · {ikResult.iterations} iterations</span>
          {ikResult.orientation_error_deg !== null ? <span>Orientation residual {ikResult.orientation_error_deg.toFixed(3)} deg</span> : null}
          {ikResult.warnings.length > 0 ? <span>{ikResult.warnings.join(' · ')}</span> : null}
        </div>
      ) : null}
      {ikError ? <p className="motion-disabled-reason" role="alert">{ikError}</p> : null}
    </section>
  );
}
