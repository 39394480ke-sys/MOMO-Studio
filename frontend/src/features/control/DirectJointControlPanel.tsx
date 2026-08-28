import { Crosshair, Hand, MoveHorizontal, ScanSearch, Square } from 'lucide-react';
import { useCallback, useEffect, useMemo, useRef, useState, type PointerEvent } from 'react';

import {
  directCommissioningStep,
  getCommissioningDirectJointState,
  getForwardKinematicsForState,
  getCommissioningMotionStatus,
  heartbeatCommissioningDirectJog,
  moveCommissioningDirectJoints,
  solveInverseKinematics,
  startCommissioningDirectJog,
  startCommissioningMotionSession,
  stopCommissioningDirectJog,
} from '../../api/client';
import type {
  CommissioningDirectControlResponse,
  CommissioningDirectJointStateResponse,
  CommissioningMotionStatus,
  ForwardKinematicsResponse,
  InverseKinematicsResponse,
  ProfileJointDefinition,
} from '../../api/types';
import { useRealSession } from '../../components/realSessionContext';
import { useRuntimeStatus } from '../../components/runtimeStatusContext';
import { quaternionToRpyDegrees, rpyDegreesToQuaternion } from './controlMath';

const HEARTBEAT_INTERVAL_MS = 150;
const LEGACY_CONTINUOUS_UPDATE_HZ = 50;
const DEFAULT_CONTROL_LEVEL_INDEX = 3;

interface ControlLevel {
  label: string;
  step: number;
  stepSpeed: number;
  continuousSpeed: number;
}

const CONTROL_LEVELS: readonly ControlLevel[] = [
  { label: '低', step: 0.5, stepSpeed: 1, continuousSpeed: 1 },
  { label: '中低', step: 1, stepSpeed: 5, continuousSpeed: 5 },
  { label: '中', step: 1.5, stepSpeed: 10, continuousSpeed: 10 },
  { label: '高', step: 2, stepSpeed: 25, continuousSpeed: 25 },
  { label: '极高', step: 3, stepSpeed: 50, continuousSpeed: 50 },
];

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : '直接控制请求失败。';
}

interface ActiveDirection {
  jointId: string;
  direction: -1 | 1;
}

type Axis = 'x' | 'y' | 'z';
type CartesianFrame = 'BASE' | 'TOOL';

interface PoseTarget {
  positionMm: Record<Axis, number>;
  rotationDeg: Record<Axis, number>;
}

function multiplyQuaternion(
  left: { x: number; y: number; z: number; w: number },
  right: { x: number; y: number; z: number; w: number },
) {
  return {
    x: left.w * right.x + left.x * right.w + left.y * right.z - left.z * right.y,
    y: left.w * right.y - left.x * right.z + left.y * right.w + left.z * right.x,
    z: left.w * right.z + left.x * right.y - left.y * right.x + left.z * right.w,
    w: left.w * right.w - left.x * right.x - left.y * right.y - left.z * right.z,
  };
}

function axisQuaternion(axis: Axis, angleDeg: number) {
  const half = angleDeg * Math.PI / 360;
  const sine = Math.sin(half);
  return {
    x: axis === 'x' ? sine : 0,
    y: axis === 'y' ? sine : 0,
    z: axis === 'z' ? sine : 0,
    w: Math.cos(half),
  };
}

function rotateVector(
  quaternion: { x: number; y: number; z: number; w: number },
  vector: Record<Axis, number>,
) {
  const pure = { ...vector, w: 0 };
  const inverse = { x: -quaternion.x, y: -quaternion.y, z: -quaternion.z, w: quaternion.w };
  const rotated = multiplyQuaternion(multiplyQuaternion(quaternion, pure), inverse);
  return { x: rotated.x, y: rotated.y, z: rotated.z };
}

export function DirectJointControlPanel() {
  const runtime = useRuntimeStatus();
  const { authorize, pendingAction, summary } = useRealSession();
  const [status, setStatus] = useState<CommissioningMotionStatus | null>(null);
  const [mode, setMode] = useState<'STEP' | 'CONTINUOUS'>('STEP');
  const [controlLevelIndex, setControlLevelIndex] = useState(DEFAULT_CONTROL_LEVEL_INDEX);
  const [busyJoint, setBusyJoint] = useState<string | null>(null);
  const [active, setActive] = useState<ActiveDirection | null>(null);
  const [readback, setReadback] = useState<CommissioningDirectControlResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [jointState, setJointState] = useState<CommissioningDirectJointStateResponse | null>(null);
  const [targets, setTargets] = useState<Record<string, number>>({});
  const [targetDrafts, setTargetDrafts] = useState<Record<string, string>>({});
  const [durationS, setDurationS] = useState(2);
  const [groupBusy, setGroupBusy] = useState(false);
  const [fk, setFk] = useState<ForwardKinematicsResponse | null>(null);
  const [ikResult, setIkResult] = useState<InverseKinematicsResponse | null>(null);
  const [frame, setFrame] = useState<CartesianFrame>('BASE');
  const [poseTarget, setPoseTarget] = useState<PoseTarget>({
    positionMm: { x: 0, y: 0, z: 0 },
    rotationDeg: { x: 0, y: 0, z: 0 },
  });
  const heartbeat = useRef<number | null>(null);
  const pressed = useRef(false);
  const generation = useRef(0);
  const mounted = useRef(true);

  const definitions = useMemo(() => {
    const profile = runtime.profile?.profile;
    if (!profile) return [];
    const byId = new Map<string, ProfileJointDefinition>(
      profile.joint_definitions.map((item) => [item.joint_id, item]),
    );
    return profile.enabled_joints.flatMap((jointId) => {
      const definition = byId.get(jointId);
      return definition ? [definition] : [];
    });
  }, [runtime.profile]);

  const option = summary.authorizationOptions.find(
    (candidate) => candidate.purpose === 'COMMISSIONING_MOTION_TEST',
  );
  const sessionAuthorized = summary.session?.purpose === 'COMMISSIONING_MOTION_TEST' &&
    summary.capabilityDetails.commissioning_motion_test.ready &&
    summary.capabilityDetails.commissioning_motion_test.authorized;
  const canStart = option?.authorizable === true && summary.session === null && !summary.stale;
  const controlLevel = CONTROL_LEVELS[controlLevelIndex] ?? CONTROL_LEVELS[DEFAULT_CONTROL_LEVEL_INDEX];
  const controlLevelLocked = pressed.current || active !== null || busyJoint !== null || groupBusy;
  const targetsValid = jointState !== null && definitions.every((definition) => {
    const draft = targetDrafts[definition.joint_id];
    const value = targets[definition.joint_id];
    return draft !== undefined && draft.trim() !== '' && Number.isFinite(value) &&
      value >= definition.minimum && value <= definition.maximum;
  });

  const replaceTargets = useCallback((next: Record<string, number>) => {
    setTargets(next);
    setTargetDrafts(Object.fromEntries(
      Object.entries(next).map(([jointId, value]) => [jointId, String(value)]),
    ));
  }, []);

  const clearHeartbeat = useCallback(() => {
    if (heartbeat.current !== null) window.clearInterval(heartbeat.current);
    heartbeat.current = null;
  }, []);

  const stopContinuous = useCallback((keepalive = false, force = false) => {
    if (!pressed.current && !force) return;
    pressed.current = false;
    generation.current += 1;
    clearHeartbeat();
    setActive(null);
    setBusyJoint(null);
    setError(null);
    void stopCommissioningDirectJog(keepalive)
      .then((next) => {
        if (mounted.current) setReadback(next);
      })
      .catch((caught) => {
        if (mounted.current && !keepalive) setError(errorMessage(caught));
      });
  }, [clearHeartbeat]);

  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
      clearHeartbeat();
      if (pressed.current) stopContinuous(true);
    };
  }, [clearHeartbeat, stopContinuous]);

  useEffect(() => {
    const stop = () => {
      if (pressed.current) stopContinuous();
    };
    const stopForUnload = () => {
      if (pressed.current) stopContinuous(true);
    };
    const stopWhenHidden = () => {
      if (document.visibilityState === 'hidden') stop();
    };
    window.addEventListener('blur', stop);
    window.addEventListener('pagehide', stopForUnload);
    window.addEventListener('beforeunload', stopForUnload);
    document.addEventListener('visibilitychange', stopWhenHidden);
    return () => {
      window.removeEventListener('blur', stop);
      window.removeEventListener('pagehide', stopForUnload);
      window.removeEventListener('beforeunload', stopForUnload);
      document.removeEventListener('visibilitychange', stopWhenHidden);
    };
  }, [stopContinuous]);

  useEffect(() => {
    if (!sessionAuthorized) {
      setStatus(null);
      return;
    }
    const controller = new AbortController();
    void getCommissioningMotionStatus(controller.signal)
      .then((next) => {
        if (!controller.signal.aborted && mounted.current) setStatus(next);
      })
      .catch(() => {
        if (!controller.signal.aborted) {
          void startCommissioningMotionSession()
            .then((next) => {
              if (mounted.current) setStatus(next);
            })
            .catch((caught) => {
              if (mounted.current) setError(errorMessage(caught));
            });
        }
      });
    return () => controller.abort();
  }, [sessionAuthorized]);

  const refreshJointState = useCallback(async () => {
    if (!sessionAuthorized) return null;
    const next = await getCommissioningDirectJointState();
    if (mounted.current) {
      setJointState(next);
      replaceTargets(next.positions);
      const nextFk = await getForwardKinematicsForState({
        positions: next.positions,
        units: next.units,
      });
      if (mounted.current) {
        setFk(nextFk);
        setPoseTarget({
          positionMm: { ...nextFk.tcp_pose.position_mm },
          rotationDeg: quaternionToRpyDegrees(
            nextFk.tcp_pose.orientation_quaternion_xyzw,
          ),
        });
      }
    }
    return next;
  }, [replaceTargets, sessionAuthorized]);

  useEffect(() => {
    if (!sessionAuthorized) {
      setJointState(null);
      setTargets({});
      setTargetDrafts({});
      return;
    }
    void refreshJointState().catch((caught) => {
      if (mounted.current) setError(errorMessage(caught));
    });
  }, [refreshJointState, sessionAuthorized]);

  const begin = async () => {
    if (!option || !canStart) return;
    setError(null);
    try {
      await authorize(
        'COMMISSIONING_MOTION_TEST',
        option.confirmation.required_confirmation_text,
        true,
        true,
      );
      setStatus(await startCommissioningMotionSession());
    } catch (caught) {
      setError(errorMessage(caught));
    }
  };

  const step = async (definition: ProfileJointDefinition, direction: -1 | 1) => {
    if (!sessionAuthorized || busyJoint || pressed.current) return;
    setBusyJoint(definition.joint_id);
    setError(null);
    try {
      const next = await directCommissioningStep(
        definition.joint_id,
        direction * controlLevel.step,
        controlLevel.stepSpeed,
      );
      setReadback(next);
      setStatus(await getCommissioningMotionStatus());
      await refreshJointState();
    } catch (caught) {
      setError(errorMessage(caught));
    } finally {
      if (mounted.current) setBusyJoint(null);
    }
  };

  const moveGroup = async (nextTargets: Record<string, number>) => {
    if (!sessionAuthorized || groupBusy || pressed.current) return;
    setGroupBusy(true);
    setError(null);
    try {
      const result = await moveCommissioningDirectJoints(nextTargets, durationS);
      setJointState({
        positions: result.positions,
        units: result.units,
        raw_positions: result.raw_positions,
        captured_at: new Date().toISOString(),
        moving: false,
        message: result.message,
      });
      replaceTargets(result.positions);
      setReadback(null);
      await refreshJointState();
    } catch (caught) {
      setError(errorMessage(caught));
    } finally {
      if (mounted.current) setGroupBusy(false);
    }
  };

  const solvePose = async (target: PoseTarget, execute: boolean) => {
    if (!jointState || groupBusy) return;
    setGroupBusy(true);
    setError(null);
    try {
      const solved = await solveInverseKinematics({
        target_pose: {
          frame: fk?.tcp_pose.frame ?? 'base',
          position_mm: { ...target.positionMm },
          orientation_quaternion_xyzw: rpyDegreesToQuaternion(target.rotationDeg),
        },
        position_unit: 'mm',
        orientation_unit: 'quaternion_xyzw',
        seed_joint_state: { positions: jointState.positions, units: jointState.units },
        position_only: false,
        maximum_iterations: 200,
      });
      setIkResult(solved);
      const solution = solved.joint_state_optional;
      if (execute) {
        if (!solved.success || !solution) {
          throw new Error(`逆解不可达：${solved.termination_reason}`);
        }
        const result = await moveCommissioningDirectJoints(solution.positions, durationS);
        replaceTargets(result.positions);
        await refreshJointState();
      }
    } catch (caught) {
      setError(errorMessage(caught));
    } finally {
      if (mounted.current) setGroupBusy(false);
    }
  };

  const cartesianJog = async (
    kind: 'translation' | 'rotation',
    axis: Axis,
    direction: -1 | 1,
  ) => {
    const currentQuaternion = rpyDegreesToQuaternion(poseTarget.rotationDeg);
    let next: PoseTarget = {
      positionMm: { ...poseTarget.positionMm },
      rotationDeg: { ...poseTarget.rotationDeg },
    };
    if (kind === 'translation') {
      const localDelta = { x: 0, y: 0, z: 0 };
      localDelta[axis] = direction * 5;
      const delta = frame === 'TOOL' ? rotateVector(currentQuaternion, localDelta) : localDelta;
      next = {
        ...next,
        positionMm: {
          x: next.positionMm.x + delta.x,
          y: next.positionMm.y + delta.y,
          z: next.positionMm.z + delta.z,
        },
      };
    } else {
      const delta = axisQuaternion(axis, direction * 3);
      const quaternion = frame === 'TOOL'
        ? multiplyQuaternion(currentQuaternion, delta)
        : multiplyQuaternion(delta, currentQuaternion);
      next = { ...next, rotationDeg: quaternionToRpyDegrees(quaternion) };
    }
    setPoseTarget(next);
    await solvePose(next, true);
  };

  const startContinuous = async (
    definition: ProfileJointDefinition,
    direction: -1 | 1,
  ) => {
    if (!sessionAuthorized || pressed.current || busyJoint) return;
    pressed.current = true;
    const requestGeneration = generation.current + 1;
    generation.current = requestGeneration;
    setBusyJoint(definition.joint_id);
    setError(null);
    try {
      const next = await startCommissioningDirectJog(
        definition.joint_id,
        direction,
        controlLevel.continuousSpeed,
      );
      if (!pressed.current || generation.current !== requestGeneration) {
        void stopCommissioningDirectJog();
        return;
      }
      setReadback(next);
      setActive({ jointId: definition.joint_id, direction });
      setBusyJoint(null);
      heartbeat.current = window.setInterval(() => {
        void heartbeatCommissioningDirectJog()
          .then((current) => {
            if (mounted.current) setReadback(current);
          })
          .catch((caught) => {
            if (mounted.current) setError(`连续控制保活失败：${errorMessage(caught)}`);
            stopContinuous();
          });
      }, HEARTBEAT_INTERVAL_MS);
    } catch (caught) {
      pressed.current = false;
      setBusyJoint(null);
      setError(errorMessage(caught));
    }
  };

  const pointerHandlers = (
    definition: ProfileJointDefinition,
    direction: -1 | 1,
  ) => ({
    onPointerDown: (event: PointerEvent<HTMLButtonElement>) => {
      event.preventDefault();
      event.currentTarget.setPointerCapture?.(event.pointerId);
      void startContinuous(definition, direction);
    },
    onPointerUp: (event: PointerEvent<HTMLButtonElement>) => {
      if (event.currentTarget.hasPointerCapture?.(event.pointerId)) {
        event.currentTarget.releasePointerCapture?.(event.pointerId);
      }
      stopContinuous();
    },
    onPointerCancel: () => stopContinuous(),
    onLostPointerCapture: () => stopContinuous(),
  });

  const stateReady = status !== null &&
    ['AUTHORIZED', 'COMPLETED', 'FAILED'].includes(status.state);

  return (
    <section className="control-panel direct-joint-control" aria-labelledby="direct-control-title">
      <div className="section-heading section-heading--compact">
        <div>
          <p className="section-kicker">实体机械臂</p>
          <h2 id="direct-control-title">单关节直接控制</h2>
          <p>一个五档控制滑块同时决定步进距离、步进执行速度和连续按住速度。</p>
        </div>
        <span className="status-badge">{sessionAuthorized ? '已启用' : '待启用'}</span>
      </div>

      {!sessionAuthorized ? (
        <button
          className="command-button command-button--danger-solid"
          disabled={!canStart || pendingAction !== null}
          onClick={() => void begin()}
          type="button"
        >
          <Hand aria-hidden="true" /> 急停已就位，开始直接控制
        </button>
      ) : (
        <>
          <div className="direct-joint-control__modes" aria-label="控制模式">
            <button
              aria-pressed={mode === 'STEP'}
              className={`command-button${mode === 'STEP' ? ' command-button--primary' : ''}`}
              disabled={controlLevelLocked}
              onClick={() => setMode('STEP')}
              type="button"
            >步进模式</button>
            <button
              aria-pressed={mode === 'CONTINUOUS'}
              className={`command-button${mode === 'CONTINUOUS' ? ' command-button--primary' : ''}`}
              disabled={controlLevelLocked}
              onClick={() => setMode('CONTINUOUS')}
              type="button"
            >连续模式</button>
          </div>
          <div className="direct-control-level">
            <div className="direct-control-level__heading">
              <div>
                <strong>控制档位</strong>
                <span>{mode === 'STEP'
                  ? `步进：每次 ${controlLevel.step} mm/deg，以 ${controlLevel.stepSpeed} mm/s 或 deg/s 执行`
                  : `连续：按住速度 ${controlLevel.continuousSpeed} mm/s 或 deg/s · ${LEGACY_CONTINUOUS_UPDATE_HZ} Hz`}</span>
              </div>
              <output htmlFor="direct-control-level-slider">{controlLevel.label}</output>
            </div>
            <input
              aria-label="控制档位"
              aria-valuetext={`${controlLevel.label}档`}
              disabled={controlLevelLocked}
              id="direct-control-level-slider"
              max={CONTROL_LEVELS.length - 1}
              min={0}
              onChange={(event) => setControlLevelIndex(Number(event.currentTarget.value))}
              onKeyDown={(event) => {
                const increments: Partial<Record<string, number>> = {
                  ArrowDown: -1,
                  ArrowLeft: -1,
                  ArrowRight: 1,
                  ArrowUp: 1,
                };
                const increment = increments[event.key];
                if (increment !== undefined) {
                  event.preventDefault();
                  setControlLevelIndex((current) => Math.max(
                    0,
                    Math.min(CONTROL_LEVELS.length - 1, current + increment),
                  ));
                } else if (event.key === 'Home' || event.key === 'End') {
                  event.preventDefault();
                  setControlLevelIndex(event.key === 'Home' ? 0 : CONTROL_LEVELS.length - 1);
                }
              }}
              step={1}
              type="range"
              value={controlLevelIndex}
            />
            <div aria-hidden="true" className="direct-control-level__labels">
              {CONTROL_LEVELS.map((level) => <span key={level.label}>{level.label}</span>)}
            </div>
          </div>
          <div className="direct-joint-control__grid">
            {definitions.map((definition) => (
              <div className="direct-joint-control__row" key={definition.joint_id}>
                <strong>{definition.joint_id.toUpperCase()}</strong>
                <span>{mode === 'STEP'
                  ? `${controlLevel.step} ${definition.domain_unit} · ${controlLevel.stepSpeed} ${definition.domain_unit}/s`
                  : `${controlLevel.continuousSpeed} ${definition.domain_unit}/s`}</span>
                {([-1, 1] as const).map((direction) => {
                  const isActive = active?.jointId === definition.joint_id &&
                    active.direction === direction;
                  return (
                    <button
                      {...(mode === 'CONTINUOUS' ? pointerHandlers(definition, direction) : {})}
                      aria-label={`${definition.joint_id.toUpperCase()} ${direction < 0 ? '负方向' : '正方向'}`}
                      aria-pressed={mode === 'CONTINUOUS' ? isActive : undefined}
                      className={`command-button${isActive ? ' command-button--danger-solid' : ''}`}
                      disabled={
                        !stateReady ||
                        (active !== null && !isActive) ||
                        (busyJoint !== null && !isActive)
                      }
                      key={direction}
                      onClick={mode === 'STEP' ? () => void step(definition, direction) : undefined}
                      type="button"
                    >
                      {mode === 'CONTINUOUS' ? <MoveHorizontal aria-hidden="true" /> : null}
                      {direction < 0 ? '−' : '+'}
                    </button>
                  );
                })}
              </div>
            ))}
          </div>
          <div className="direct-field-move">
            <div className="section-heading section-heading--compact">
              <div>
                <p className="section-kicker">现场功能测试</p>
                <h3>整组关节与 Home</h3>
                <p>目标值使用真实六轴读数；执行时按 20 Hz 平滑插值，Stop 可随时打断。</p>
              </div>
              <button
                className="command-button"
                disabled={groupBusy || active !== null}
                onClick={() => void refreshJointState().catch((caught) => setError(errorMessage(caught)))}
                type="button"
              >刷新实体姿态</button>
            </div>
            <div className="direct-field-move__targets">
              {definitions.map((definition) => (
                <label key={`target-${definition.joint_id}`}>
                  <span>{definition.joint_id.toUpperCase()} · {definition.domain_unit}</span>
                  <input
                    disabled={groupBusy || active !== null || jointState === null}
                    max={definition.maximum}
                    min={definition.minimum}
                    onChange={(event) => {
                      const draft = event.currentTarget.value;
                      const value = event.currentTarget.valueAsNumber;
                      setTargetDrafts((current) => ({
                        ...current,
                        [definition.joint_id]: draft,
                      }));
                      if (Number.isFinite(value)) {
                        setTargets((current) => ({
                          ...current,
                          [definition.joint_id]: value,
                        }));
                      }
                    }}
                    step="0.1"
                    type="number"
                    value={targetDrafts[definition.joint_id] ?? ''}
                  />
                </label>
              ))}
            </div>
            <div className="direct-field-move__actions">
              <label>
                运动时长
                <span className="number-with-unit">
                  <input
                    disabled={groupBusy || active !== null}
                    max={30}
                    min={0.1}
                    onChange={(event) => setDurationS(event.currentTarget.valueAsNumber)}
                    step={0.1}
                    type="number"
                    value={durationS}
                  />
                  <span>s</span>
                </span>
              </label>
              <button
                className="command-button command-button--primary"
                disabled={groupBusy || active !== null || !targetsValid}
                onClick={() => void moveGroup(targets)}
                type="button"
              >{groupBusy ? '运动中…' : '移动全部关节'}</button>
              <button
                className="command-button command-button--home"
                disabled={groupBusy || active !== null || jointState === null}
                onClick={() => void moveGroup(Object.fromEntries(
                  definitions.map((definition) => [definition.joint_id, definition.home]),
                ))}
                type="button"
              >Home</button>
            </div>
            {jointState ? (
              <p className="control-hint">
                当前实体：{definitions.map((definition) =>
                  `${definition.joint_id.toUpperCase()} ${(jointState.positions[definition.joint_id] ?? 0).toFixed(2)} ${definition.domain_unit}`
                ).join(' · ')}
              </p>
            ) : null}
          </div>
          <div className="direct-field-move">
            <div className="section-heading section-heading--compact">
              <div>
                <p className="section-kicker">TCP / 笛卡尔现场测试</p>
                <h3>位姿、BASE / TOOL 点动</h3>
                <p>每次点动先用真实六轴状态求 IK，再通过同一六轴平滑执行链路运动。</p>
              </div>
              <div className="frame-selector" aria-label="现场笛卡尔参考坐标系">
                {(['BASE', 'TOOL'] as const).map((candidate) => (
                  <button
                    aria-pressed={frame === candidate}
                    className={frame === candidate ? 'frame-selector__active' : ''}
                    disabled={groupBusy || fk === null}
                    key={candidate}
                    onClick={() => setFrame(candidate)}
                    type="button"
                  >{candidate}</button>
                ))}
              </div>
            </div>
            {fk ? (
              <p className="control-hint">
                TCP XYZ {fk.tcp_pose.position_mm.x.toFixed(2)}, {fk.tcp_pose.position_mm.y.toFixed(2)}, {fk.tcp_pose.position_mm.z.toFixed(2)} mm
              </p>
            ) : <p className="control-hint">读取实体姿态后显示 TCP。</p>}
            <div className="cartesian-jog-grid">
              {(['translation', 'rotation'] as const).map((kind) => (
                <fieldset className="cartesian-jog-group" disabled={groupBusy || fk === null} key={kind}>
                  <legend>{kind === 'translation' ? '位置点动 · 5 mm' : '姿态点动 · 3°'}</legend>
                  {(['x', 'y', 'z'] as const).map((axis) => (
                    <div key={`${kind}-${axis}`}>
                      <span>{kind === 'translation' ? axis.toUpperCase() : `R${axis}`}</span>
                      <button onClick={() => void cartesianJog(kind, axis, -1)} type="button">−</button>
                      <button onClick={() => void cartesianJog(kind, axis, 1)} type="button">+</button>
                    </div>
                  ))}
                </fieldset>
              ))}
            </div>
            <div className="pose-editor">
              <fieldset disabled={groupBusy || fk === null}>
                <legend>目标位置 · mm</legend>
                {(['x', 'y', 'z'] as const).map((axis) => (
                  <label key={`pose-position-${axis}`}>{axis.toUpperCase()}
                    <input
                      onChange={(event) => {
                        const value = event.currentTarget.valueAsNumber;
                        if (!Number.isFinite(value)) return;
                        setPoseTarget((current) => ({
                          ...current,
                          positionMm: { ...current.positionMm, [axis]: value },
                        }));
                      }}
                      step="0.1"
                      type="number"
                      value={poseTarget.positionMm[axis]}
                    />
                  </label>
                ))}
              </fieldset>
              <fieldset disabled={groupBusy || fk === null}>
                <legend>目标 RPY · deg</legend>
                {(['x', 'y', 'z'] as const).map((axis) => (
                  <label key={`pose-rotation-${axis}`}>{`R${axis}`}
                    <input
                      onChange={(event) => {
                        const value = event.currentTarget.valueAsNumber;
                        if (!Number.isFinite(value)) return;
                        setPoseTarget((current) => ({
                          ...current,
                          rotationDeg: { ...current.rotationDeg, [axis]: value },
                        }));
                      }}
                      step="0.1"
                      type="number"
                      value={poseTarget.rotationDeg[axis]}
                    />
                  </label>
                ))}
              </fieldset>
            </div>
            <div className="panel-actions">
              <button
                className="command-button"
                disabled={groupBusy || fk === null}
                onClick={() => void solvePose(poseTarget, false)}
                type="button"
              ><ScanSearch aria-hidden="true" /> 检查逆解</button>
              <button
                className="command-button command-button--primary"
                disabled={groupBusy || fk === null}
                onClick={() => void solvePose(poseTarget, true)}
                type="button"
              ><Crosshair aria-hidden="true" /> 移动到位姿</button>
            </div>
            {ikResult ? (
              <p className={ikResult.success ? 'control-hint' : 'real-inline-error'} role="status">
                {ikResult.success ? '逆解可达' : '逆解不可达'} · {ikResult.termination_reason} · 位置残差 {ikResult.position_error_mm.toFixed(3)} mm
              </p>
            ) : null}
          </div>
        </>
      )}

      <div className="direct-joint-control__footer">
        <span>
          {active
            ? `${active.jointId.toUpperCase()} 连续运动中，松手停止`
            : busyJoint
              ? `${busyJoint.toUpperCase()} 正在提交…`
              : readback
                ? readback.joint_id
                  ? `${readback.message} ${readback.joint_id.toUpperCase()} 目标 ${readback.target_value?.toFixed(2)} · Raw ${readback.raw_position ?? '读取中'}`
                  : readback.message
                : '等待操作'}
        </span>
        <button
          className="command-button command-button--stop"
          onClick={() => stopContinuous(false, true)}
          type="button"
        >
          <Square aria-hidden="true" /> 停止并保持（不断开）
        </button>
      </div>
      {error ? <p className="real-inline-error" role="alert">{error}</p> : null}
    </section>
  );
}
