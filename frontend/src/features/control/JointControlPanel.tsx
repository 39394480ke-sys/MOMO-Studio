import { MoveHorizontal, RotateCcw } from 'lucide-react';
import type { ButtonHTMLAttributes } from 'react';

import type { ProfileJointDefinition, RobotStatus } from '../../api/types';
import type { ControlParameters, MotionAvailability } from './controlTypes';

interface JogIntentView {
  jointId: string;
  direction: -1 | 1;
}

interface JointControlPanelProps {
  robot: RobotStatus;
  definitions: ProfileJointDefinition[];
  targets: Record<string, number>;
  parameters: ControlParameters;
  availability: MotionAvailability;
  pending: string | null;
  motionLocked: boolean;
  activeJog: JogIntentView | null;
  startingJog: JogIntentView | null;
  onTargetChange: (jointId: string, value: number) => void;
  onResetTargets: () => void;
  onMoveJoints: () => Promise<void>;
  onStepJog: (jointId: string, direction: -1 | 1) => Promise<void>;
  holdHandlers: (
    jointId: string,
    direction: -1 | 1,
  ) => ButtonHTMLAttributes<HTMLButtonElement>;
}

function isIntent(
  intent: JogIntentView | null,
  jointId: string,
  direction: -1 | 1,
): boolean {
  return intent?.jointId === jointId && intent.direction === direction;
}

export function JointControlPanel({
  robot,
  definitions,
  targets,
  parameters,
  availability,
  pending,
  motionLocked,
  activeJog,
  startingJog,
  onTargetChange,
  onResetTargets,
  onMoveJoints,
  onStepJog,
  holdHandlers,
}: JointControlPanelProps) {
  const disabled = !availability.allowed || pending !== null || motionLocked;
  return (
    <section className="control-panel control-panel--joints" aria-labelledby="joint-control-title">
      <div className="section-heading section-heading--compact">
        <div>
          <p className="section-kicker">Joint Control</p>
          <h2 id="joint-control-title">Keyed joints</h2>
        </div>
        <span className="read-only-label">{robot.variant}</span>
      </div>

      <div className="joint-control-grid">
        {definitions.map((definition) => {
          const jointId = definition.joint_id;
          const unit = definition.domain_unit;
          const current = robot.positions[jointId] ?? definition.home;
          const target = targets[jointId] ?? current;
          return (
            <article className="joint-control-card" key={jointId}>
              <header>
                <div>
                  <strong>{jointId.toUpperCase()}</strong>
                  <span>{definition.joint_type === 'PRISMATIC' ? 'Linear rail' : 'Revolute'}</span>
                </div>
                <p>
                  <span>Current</span>
                  <strong>{current.toFixed(2)}</strong>
                  <span>{unit}</span>
                </p>
              </header>
              <label>
                Target ({unit})
                <input
                  aria-label={`${jointId.toUpperCase()} target (${unit})`}
                  disabled={disabled}
                  max={definition.maximum}
                  min={definition.minimum}
                  onChange={(event) => onTargetChange(jointId, event.currentTarget.valueAsNumber)}
                  step="0.1"
                  type="number"
                  value={target}
                />
              </label>
              <div className="joint-command-row" aria-label={`${jointId.toUpperCase()} step jog`}>
                {([-1, 1] as const).map((direction) => (
                  <button
                    aria-label={`Step ${jointId.toUpperCase()} ${direction < 0 ? 'negative' : 'positive'}`}
                    className="mini-command"
                    disabled={disabled}
                    key={`step-${direction}`}
                    onClick={() => void onStepJog(jointId, direction)}
                    type="button"
                  >
                    {direction < 0 ? '− Step' : '+ Step'}
                  </button>
                ))}
              </div>
              <div className="joint-command-row" aria-label={`${jointId.toUpperCase()} continuous jog`}>
                {([-1, 1] as const).map((direction) => {
                  const active = isIntent(activeJog, jointId, direction);
                  const starting = isIntent(startingJog, jointId, direction);
                  return (
                    <button
                      {...holdHandlers(jointId, direction)}
                      aria-label={`Hold ${jointId.toUpperCase()} ${direction < 0 ? 'negative' : 'positive'} jog`}
                      aria-pressed={active}
                      className={`mini-command mini-command--hold${active ? ' mini-command--active' : ''}`}
                      disabled={disabled && !active && !starting}
                      key={`hold-${direction}`}
                      type="button"
                    >
                      <MoveHorizontal aria-hidden="true" />
                      {starting ? 'Starting…' : direction < 0 ? 'Hold −' : 'Hold +'}
                    </button>
                  );
                })}
              </div>
            </article>
          );
        })}
      </div>

      <div className="panel-actions">
        <button className="command-button" disabled={disabled} onClick={onResetTargets} type="button">
          <RotateCcw aria-hidden="true" /> Reset targets
        </button>
        <button
          className="command-button command-button--primary"
          disabled={disabled}
          onClick={() => void onMoveJoints()}
          type="button"
        >
          {pending === 'move-joints' ? 'Submitting…' : 'Move all joints'}
        </button>
      </div>
      {!availability.allowed ? (
        <p className="motion-disabled-reason" role="status">{availability.reason}</p>
      ) : null}
      <p className="control-hint">
        Step uses {parameters.jointStepDeg} deg for revolute joints and {parameters.railStepMm} mm for the rail.
        Hold buttons require a live lease; release, blur, hide, or network loss stops the jog.
      </p>
    </section>
  );
}
