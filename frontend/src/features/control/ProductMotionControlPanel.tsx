import { useCallback, useEffect, useMemo, useRef, useState, type ButtonHTMLAttributes, type KeyboardEvent, type PointerEvent } from 'react';

import type {
  CartesianFrame,
  ForwardKinematicsResponse,
  InverseKinematicsResponse,
  ProfileJointDefinition,
  RobotStatus,
  Vector3,
} from '../../api/types';
import type {
  ControlParameterChange,
  ControlParameters,
  MotionAvailability,
  PoseEditorValue,
} from './controlTypes';

type Axis = keyof Vector3;
type ControlMode = 'JOINT' | 'CARTESIAN';

interface JogIntentView {
  jointId: string;
  direction: -1 | 1;
}

interface ProductMotionControlPanelProps {
  robot: RobotStatus;
  definitions: ProfileJointDefinition[];
  jointTargets: Record<string, number>;
  parameters: ControlParameters;
  jointAvailability: MotionAvailability;
  cartesianAvailability: MotionAvailability;
  stopAllowed: boolean;
  pending: string | null;
  motionLocked: boolean;
  activeJog: JogIntentView | null;
  startingJog: JogIntentView | null;
  frame: CartesianFrame;
  poseTarget: PoseEditorValue;
  fk: ForwardKinematicsResponse | null;
  ikPending: boolean;
  ikResult: InverseKinematicsResponse | null;
  ikError: string | null;
  holdHandlers: (
    jointId: string,
    direction: -1 | 1,
  ) => ButtonHTMLAttributes<HTMLButtonElement>;
  onJointTargetChange: (jointId: string, value: number) => void;
  onStepJog: (jointId: string, direction: -1 | 1) => Promise<void>;
  onMoveJoints: () => Promise<void>;
  onFrameChange: (frame: CartesianFrame) => void;
  onCartesianJog: (
    kind: 'translation' | 'rotation',
    axis: Axis,
    direction: -1 | 1,
  ) => Promise<void>;
  onPositionChange: (axis: Axis, value: number) => void;
  onRotationChange: (axis: Axis, value: number) => void;
  onSolveIk: () => Promise<void>;
  onMovePose: () => Promise<void>;
  onParameterChange: ControlParameterChange;
  onHome: () => Promise<void>;
  onStop: () => Promise<void>;
}

const SPEED_LEVELS = [
  { label: '极低', scale: 0.15, jointStep: 0.5, railStep: 1, rotationStep: 0.5 },
  { label: '低', scale: 0.3, jointStep: 1, railStep: 2.5, rotationStep: 1 },
  { label: '中', scale: 0.5, jointStep: 2, railStep: 5, rotationStep: 3 },
  { label: '高', scale: 0.75, jointStep: 3, railStep: 10, rotationStep: 4 },
  { label: '极高', scale: 1, jointStep: 5, railStep: 15, rotationStep: 5 },
] as const;

const LONG_PRESS_MS = 260;

function isIntent(
  intent: JogIntentView | null,
  jointId: string,
  direction: -1 | 1,
): boolean {
  return intent?.jointId === jointId && intent.direction === direction;
}

function finite(value: number | undefined, digits = 1): string {
  return value === undefined || !Number.isFinite(value) ? '—' : value.toFixed(digits);
}

function PressJogButton({
  active,
  disabled,
  direction,
  jointId,
  starting,
  handlers,
  onStep,
}: {
  active: boolean;
  disabled: boolean;
  direction: -1 | 1;
  jointId: string;
  starting: boolean;
  handlers: ButtonHTMLAttributes<HTMLButtonElement>;
  onStep: () => Promise<void>;
}) {
  const timerRef = useRef<number | null>(null);
  const holdingRef = useRef(false);
  const pointerIntentRef = useRef<{ pointerId: number; target: HTMLButtonElement } | null>(null);
  const keyboardIntentRef = useRef<{ key: ' ' | 'Enter' } | null>(null);
  const handlersRef = useRef(handlers);
  const disabledRef = useRef(disabled);
  const onStepRef = useRef(onStep);
  handlersRef.current = handlers;
  disabledRef.current = disabled;
  onStepRef.current = onStep;

  const clearTimer = useCallback(() => {
    if (timerRef.current !== null) window.clearTimeout(timerRef.current);
    timerRef.current = null;
  }, []);

  const beginPointer = (event: PointerEvent<HTMLButtonElement>) => {
    if (disabled) return;
    event.preventDefault();
    pointerIntentRef.current = { pointerId: event.pointerId, target: event.currentTarget };
    if (typeof event.currentTarget.setPointerCapture === 'function') {
      event.currentTarget.setPointerCapture(event.pointerId);
    }
    clearTimer();
    timerRef.current = window.setTimeout(() => {
      timerRef.current = null;
      const pendingIntent = pointerIntentRef.current;
      const latestHandlers = handlersRef.current;
      if (
        disabledRef.current ||
        !pendingIntent ||
        typeof latestHandlers.onPointerDown !== 'function'
      ) {
        pointerIntentRef.current = null;
        return;
      }
      holdingRef.current = true;
      latestHandlers.onPointerDown({
        currentTarget: pendingIntent.target,
        pointerId: pendingIntent.pointerId,
        preventDefault: () => undefined,
      } as PointerEvent<HTMLButtonElement>);
    }, LONG_PRESS_MS);
  };

  const finishPointer = (event: PointerEvent<HTMLButtonElement>) => {
    const quickPress = timerRef.current !== null && !holdingRef.current && !disabledRef.current;
    clearTimer();
    pointerIntentRef.current = null;
    const latestHandlers = handlersRef.current;
    if (holdingRef.current && typeof latestHandlers.onPointerUp === 'function') {
      latestHandlers.onPointerUp(event);
    }
    holdingRef.current = false;
    if (quickPress) void onStepRef.current();
  };

  const cancel = useCallback(() => {
    clearTimer();
    pointerIntentRef.current = null;
    keyboardIntentRef.current = null;
    if (holdingRef.current && typeof handlersRef.current.onPointerCancel === 'function') {
      handlersRef.current.onPointerCancel({} as PointerEvent<HTMLButtonElement>);
    } else if (holdingRef.current && typeof handlersRef.current.onBlur === 'function') {
      handlersRef.current.onBlur({} as never);
    }
    holdingRef.current = false;
  }, [clearTimer]);

  const beginKeyboard = (event: KeyboardEvent<HTMLButtonElement>) => {
    if (disabled || event.repeat || (event.key !== ' ' && event.key !== 'Enter')) return;
    event.preventDefault();
    keyboardIntentRef.current = { key: event.key as ' ' | 'Enter' };
    clearTimer();
    timerRef.current = window.setTimeout(() => {
      timerRef.current = null;
      const pendingIntent = keyboardIntentRef.current;
      const latestHandlers = handlersRef.current;
      if (
        disabledRef.current ||
        !pendingIntent ||
        typeof latestHandlers.onKeyDown !== 'function'
      ) {
        keyboardIntentRef.current = null;
        return;
      }
      holdingRef.current = true;
      latestHandlers.onKeyDown({
        key: pendingIntent.key,
        repeat: false,
        preventDefault: () => undefined,
      } as KeyboardEvent<HTMLButtonElement>);
    }, LONG_PRESS_MS);
  };

  const finishKeyboard = (event: KeyboardEvent<HTMLButtonElement>) => {
    if (event.key !== ' ' && event.key !== 'Enter') return;
    event.preventDefault();
    const quickPress = timerRef.current !== null && !holdingRef.current;
    clearTimer();
    keyboardIntentRef.current = null;
    const latestHandlers = handlersRef.current;
    if (holdingRef.current && typeof latestHandlers.onKeyUp === 'function') {
      latestHandlers.onKeyUp(event);
    }
    holdingRef.current = false;
    if (quickPress && !disabledRef.current) void onStepRef.current();
  };

  useEffect(() => {
    if (disabled && timerRef.current !== null) cancel();
  }, [cancel, disabled]);

  useEffect(() => () => cancel(), [cancel]);

  const directionLabel = direction < 0 ? 'negative' : 'positive';
  return (
    <button
      aria-describedby={`${jointId}-${directionLabel}-jog-help`}
      aria-label={`Step ${jointId.toUpperCase()} ${directionLabel}`}
      aria-pressed={active}
      className={`axis-step-button${active || starting ? ' axis-step-button--active' : ''}`}
      disabled={disabled && !active && !starting}
      onBlur={cancel}
      onKeyDown={beginKeyboard}
      onKeyUp={finishKeyboard}
      onLostPointerCapture={cancel}
      onPointerCancel={cancel}
      onPointerDown={beginPointer}
      onPointerUp={finishPointer}
      title="短按单步；长按启动 Deadman 连续点动"
      type="button"
    >
      {direction < 0 ? '−' : '+'}
      <span className="visually-hidden" id={`${jointId}-${directionLabel}-jog-help`}>
        短按执行安全单步，长按启动带租约和心跳的连续点动；松开、失焦或页面隐藏会停止。
      </span>
    </button>
  );
}

function SpeedSelector({
  parameters,
  disabled,
  onChange,
}: {
  parameters: ControlParameters;
  disabled: boolean;
  onChange: ProductMotionControlPanelProps['onParameterChange'];
}) {
  const selected = useMemo(() => {
    let best = 0;
    SPEED_LEVELS.forEach((level, index) => {
      if (
        Math.abs(level.scale - parameters.speedScale)
        < Math.abs(SPEED_LEVELS[best].scale - parameters.speedScale)
      ) best = index;
    });
    return best;
  }, [parameters.speedScale]);

  const select = (index: number) => {
    const level = SPEED_LEVELS[index];
    if (!level) return;
    onChange('speedScale', level.scale);
    onChange('jointStepDeg', level.jointStep);
    onChange('railStepMm', level.railStep);
    onChange('continuousSpeedDegS', 45 * level.scale);
    onChange('railSpeedMmS', 50 * level.scale);
    onChange('cartesianStepMm', level.railStep);
    onChange('rotationStepDeg', level.rotationStep);
  };

  return (
    <div className="speed-selector" aria-label="五档共享速度">
      <div className="speed-selector__label">
        <span>Speed</span>
        <strong>{SPEED_LEVELS[selected].label}</strong>
      </div>
      <div className="speed-selector__steps" role="radiogroup" aria-label="共享速度档位">
        {SPEED_LEVELS.map((level, index) => (
          <button
            aria-checked={selected === index}
            aria-label={`速度 ${index + 1}：${level.label}`}
            className={selected === index ? 'is-selected' : ''}
            disabled={disabled}
            key={level.label}
            onClick={() => select(index)}
            role="radio"
            type="button"
          ><span /></button>
        ))}
      </div>
    </div>
  );
}

export function ProductMotionControlPanel({
  robot,
  definitions,
  jointTargets,
  parameters,
  jointAvailability,
  cartesianAvailability,
  stopAllowed,
  pending,
  motionLocked,
  activeJog,
  startingJog,
  frame,
  poseTarget,
  fk,
  ikPending,
  ikResult,
  ikError,
  holdHandlers,
  onJointTargetChange,
  onStepJog,
  onMoveJoints,
  onFrameChange,
  onCartesianJog,
  onPositionChange,
  onRotationChange,
  onSolveIk,
  onMovePose,
  onParameterChange,
  onHome,
  onStop,
}: ProductMotionControlPanelProps) {
  const [mode, setMode] = useState<ControlMode>('JOINT');
  const [homeConfirmationOpen, setHomeConfirmationOpen] = useState(false);
  const jointDisabled = !jointAvailability.allowed || pending !== null || motionLocked;
  const cartesianDisabled = !cartesianAvailability.allowed || pending !== null || motionLocked || !fk;
  const activeAvailability = mode === 'JOINT' ? jointAvailability : cartesianAvailability;

  useEffect(() => {
    if (jointDisabled) setHomeConfirmationOpen(false);
  }, [jointDisabled]);

  return (
    <section className="product-motion-panel" aria-labelledby="motion-control-title">
      <header className="product-panel-header product-motion-panel__header">
        <h2 id="motion-control-title">运动控制</h2>
        <div className="segmented-control" aria-label="运动控制模式">
          {(['JOINT', 'CARTESIAN'] as const).map((candidate) => (
            <button
              aria-pressed={mode === candidate}
              className={mode === candidate ? 'is-selected' : ''}
              key={candidate}
              onClick={() => setMode(candidate)}
              type="button"
            >{candidate === 'JOINT' ? 'Joint' : 'Cartesian'}</button>
          ))}
        </div>
      </header>

      {mode === 'JOINT' ? (
        <div className="axis-control-list" data-testid="joint-axis-list">
          {definitions.map((definition) => {
            const jointId = definition.joint_id;
            const current = robot.positions[jointId] ?? definition.home;
            const target = jointTargets[jointId] ?? current;
            const unit = definition.domain_unit;
            return (
              <div className="axis-control-row" key={jointId}>
                <strong>{jointId.toUpperCase()}</strong>
                <PressJogButton
                  active={isIntent(activeJog, jointId, -1)}
                  disabled={jointDisabled}
                  direction={-1}
                  handlers={holdHandlers(jointId, -1)}
                  jointId={jointId}
                  onStep={() => onStepJog(jointId, -1)}
                  starting={isIntent(startingJog, jointId, -1)}
                />
                <input
                  aria-label={`${jointId.toUpperCase()} target (${unit})`}
                  disabled={jointDisabled}
                  max={definition.maximum}
                  min={definition.minimum}
                  onChange={(event) => onJointTargetChange(jointId, event.currentTarget.valueAsNumber)}
                  step="0.1"
                  type="range"
                  value={target}
                />
                <PressJogButton
                  active={isIntent(activeJog, jointId, 1)}
                  disabled={jointDisabled}
                  direction={1}
                  handlers={holdHandlers(jointId, 1)}
                  jointId={jointId}
                  onStep={() => onStepJog(jointId, 1)}
                  starting={isIntent(startingJog, jointId, 1)}
                />
                <output><strong>{finite(current)}</strong><span>{unit}</span></output>
              </div>
            );
          })}
          <button
            aria-label="移动全部关节"
            className="product-inline-action"
            disabled={jointDisabled}
            onClick={() => void onMoveJoints()}
            type="button"
          >应用目标</button>
        </div>
      ) : (
        <div className="cartesian-product-control" data-testid="cartesian-axis-list">
          <div className="reference-frame-row">
            <span>Reference frame</span>
            <div className="segmented-control segmented-control--compact" aria-label="笛卡尔参考坐标系">
              {(['BASE', 'TOOL'] as const).map((candidate) => (
                <button
                  aria-pressed={frame === candidate}
                  className={frame === candidate ? 'is-selected' : ''}
                  disabled={cartesianDisabled}
                  key={candidate}
                  onClick={() => onFrameChange(candidate)}
                  type="button"
                >{candidate}</button>
              ))}
            </div>
          </div>
          {([
            ['translation', 'x', 'X', 'mm'],
            ['translation', 'y', 'Y', 'mm'],
            ['translation', 'z', 'Z', 'mm'],
            ['rotation', 'x', 'RX', 'deg'],
            ['rotation', 'y', 'RY', 'deg'],
            ['rotation', 'z', 'RZ', 'deg'],
          ] as const).map(([kind, axis, label, unit]) => {
            const value = kind === 'translation'
              ? poseTarget.positionMm[axis]
              : poseTarget.rotationDeg[axis];
            return (
              <div className="axis-control-row" key={label}>
                <strong>{label}</strong>
                <button
                  aria-label={`Jog ${kind === 'translation' ? label : `R${axis}`} negative`}
                  className="axis-step-button"
                  disabled={cartesianDisabled}
                  onClick={() => void onCartesianJog(kind, axis, -1)}
                  type="button"
                >−</button>
                <input
                  aria-label={`Target ${kind === 'translation' ? label : ['roll', 'pitch', 'yaw'][['x', 'y', 'z'].indexOf(axis)]} (${unit})`}
                  disabled={cartesianDisabled}
                  onChange={(event) => {
                    const next = event.currentTarget.valueAsNumber;
                    if (kind === 'translation') onPositionChange(axis, next);
                    else onRotationChange(axis, next);
                  }}
                  step="0.1"
                  type="number"
                  value={value}
                />
                <button
                  aria-label={`Jog ${kind === 'translation' ? label : `R${axis}`} positive`}
                  className="axis-step-button"
                  disabled={cartesianDisabled}
                  onClick={() => void onCartesianJog(kind, axis, 1)}
                  type="button"
                >+</button>
                <output><strong>{finite(value)}</strong><span>{unit}</span></output>
              </div>
            );
          })}
          <div className="cartesian-product-actions">
            <button disabled={cartesianDisabled || ikPending} onClick={() => void onSolveIk()} type="button">
              {ikPending ? '求解中…' : '检查逆解'}
            </button>
            <button disabled={cartesianDisabled} onClick={() => void onMovePose()} type="button">
              移动到位姿
            </button>
          </div>
          {ikResult ? (
            <div className={ikResult.success ? 'inline-feedback inline-feedback--success' : 'inline-feedback inline-feedback--danger'} role="status">
              <strong>{ikResult.success ? '逆解可达' : '逆解不可达'}</strong>
              <span>{ikResult.termination_reason}</span>
              <span>位置残差 {ikResult.position_error_mm.toFixed(3)} mm · {ikResult.iterations} 次迭代</span>
              {ikResult.orientation_error_deg === null ? null : (
                <span>姿态残差 {ikResult.orientation_error_deg.toFixed(3)} deg</span>
              )}
              {ikResult.warnings.map((warning) => <span key={warning}>{warning}</span>)}
            </div>
          ) : null}
          {ikError ? <p className="inline-feedback inline-feedback--danger" role="alert">{ikError}</p> : null}
        </div>
      )}

      <footer className="product-motion-panel__footer">
        <div className="product-motion-actions">
          <button
            aria-label="机器人回零"
            className="is-primary"
            disabled={jointDisabled}
            onClick={() => setHomeConfirmationOpen(true)}
            type="button"
          >Home</button>
          <button
            aria-label="停止运动（面板）"
            className="is-danger"
            disabled={!stopAllowed}
            onClick={() => void onStop()}
            type="button"
          >Stop</button>
          <button disabled title="当前版本没有经过审核的释放力矩接口" type="button">Free</button>
        </div>
        <SpeedSelector
          disabled={motionLocked || pending !== null}
          onChange={onParameterChange}
          parameters={parameters}
        />
      </footer>

      {!activeAvailability.allowed ? (
        <p className="product-motion-disabled" role="status">{activeAvailability.reason}</p>
      ) : null}

      {homeConfirmationOpen ? (
        <div aria-label="确认回零" className="home-confirmation product-home-confirmation" role="alertdialog">
          <strong>让所有已启用关节回到 Home？</strong>
          <p>只会通过当前运行模式对应的受控执行入口提交。</p>
          <div>
            <button onClick={() => setHomeConfirmationOpen(false)} type="button">取消回零</button>
            <button
              onClick={() => {
                setHomeConfirmationOpen(false);
                void onHome();
              }}
              type="button"
            >确认回零</button>
          </div>
        </div>
      ) : null}
    </section>
  );
}
