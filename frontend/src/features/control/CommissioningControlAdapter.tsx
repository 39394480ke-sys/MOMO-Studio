import { Cable, CircleStop, PlugZap } from 'lucide-react';
import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ButtonHTMLAttributes,
  type KeyboardEvent,
  type PointerEvent,
} from 'react';

import {
  directCommissioningStep,
  getCommissioningDirectJointState,
  getCommissioningMotionStatus,
  getForwardKinematicsForState,
  heartbeatCommissioningDirectJog,
  moveCommissioningDirectJoints,
  solveInverseKinematics,
  startCommissioningDirectJog,
  startCommissioningMotionSession,
  stopCommissioningDirectJog,
} from '../../api/client';
import type {
  CartesianFrame,
  CommissioningDirectJointStateResponse,
  CommissioningMotionStatus,
  ForwardKinematicsResponse,
  InverseKinematicsResponse,
  ProfileJointDefinition,
  RobotStatus,
  Vector3,
} from '../../api/types';
import { useRealSession } from '../../components/realSessionContext';
import { useRuntimeStatus } from '../../components/runtimeStatusContext';
import { quaternionToRpyDegrees, rpyDegreesToQuaternion } from './controlMath';
import {
  DEFAULT_CONTROL_PARAMETERS,
  type ControlParameters,
  type MotionAvailability,
  type PoseEditorValue,
} from './controlTypes';
import { ControlWorkspaceView } from './ControlWorkspaceView';

const HEARTBEAT_INTERVAL_MS = 150;

interface ActiveDirection {
  jointId: string;
  direction: -1 | 1;
}

type Axis = keyof Vector3;

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : '真机控制请求失败。';
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

function definitionsFor(
  profile: ReturnType<typeof useRuntimeStatus>['profile'],
): ProfileJointDefinition[] {
  if (!profile) return [];
  const byId = new Map(
    profile.profile.joint_definitions.map((definition) => [definition.joint_id, definition]),
  );
  return profile.profile.enabled_joints.flatMap((jointId) => {
    const definition = byId.get(jointId);
    return definition ? [definition] : [];
  });
}

function displayRobot(
  robot: RobotStatus | null,
  jointState: CommissioningDirectJointStateResponse | null,
): RobotStatus | null {
  if (!robot || !jointState) return robot;
  return {
    ...robot,
    positions: jointState.positions,
    units: jointState.units,
    raw_positions: jointState.raw_positions,
    updated_at: jointState.captured_at,
    hardware_accessed: true,
    stale: false,
  };
}

export function CommissioningControlAdapter() {
  const runtime = useRuntimeStatus();
  const { authorize, pendingAction, refresh: refreshSession, revoke, summary } = useRealSession();
  const [status, setStatus] = useState<CommissioningMotionStatus | null>(null);
  const [jointState, setJointState] = useState<CommissioningDirectJointStateResponse | null>(null);
  const [targets, setTargets] = useState<Record<string, number>>({});
  const [parameters, setParameters] = useState<ControlParameters>(() => ({
    ...DEFAULT_CONTROL_PARAMETERS,
  }));
  const [frame, setFrame] = useState<CartesianFrame>('BASE');
  const [poseTarget, setPoseTarget] = useState<PoseEditorValue>({
    positionMm: { x: 0, y: 0, z: 0 },
    rotationDeg: { x: 0, y: 0, z: 0 },
  });
  const [fk, setFk] = useState<ForwardKinematicsResponse | null>(null);
  const [ikResult, setIkResult] = useState<InverseKinematicsResponse | null>(null);
  const [ikError, setIkError] = useState<string | null>(null);
  const [busyJoint, setBusyJoint] = useState<string | null>(null);
  const [starting, setStarting] = useState<ActiveDirection | null>(null);
  const [active, setActive] = useState<ActiveDirection | null>(null);
  const [groupBusy, setGroupBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const heartbeat = useRef<number | null>(null);
  const pressed = useRef(false);
  const generation = useRef(0);
  const mounted = useRef(true);

  const definitions = useMemo(() => definitionsFor(runtime.profile), [runtime.profile]);
  const option = summary.authorizationOptions.find(
    (candidate) => candidate.purpose === 'COMMISSIONING_MOTION_TEST',
  );
  const sessionAuthorized = summary.session?.purpose === 'COMMISSIONING_MOTION_TEST' &&
    summary.capabilityDetails.commissioning_motion_test.ready &&
    summary.capabilityDetails.commissioning_motion_test.authorized;
  const canAuthorize = option?.authorizable === true && summary.session === null && !summary.stale;
  const robot = useMemo(
    () => displayRobot(runtime.robot, jointState),
    [jointState, runtime.robot],
  );
  const stateReady = status !== null &&
    ['AUTHORIZED', 'COMPLETED', 'FAILED'].includes(status.state);
  const motionLocked = groupBusy || busyJoint !== null || active !== null;
  const availability: MotionAvailability = !sessionAuthorized
    ? { allowed: false, reason: canAuthorize ? '启用真机控制后即可操作' : '真机控制授权不可用' }
    : !stateReady || jointState === null
      ? { allowed: false, reason: '正在读取真实机械臂状态' }
      : { allowed: true, reason: '真实控制适配器已就绪' };
  const cartesianAvailability: MotionAvailability = fk === null
    ? { allowed: false, reason: availability.allowed ? '正在计算 TCP 状态' : availability.reason }
    : availability;

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
    setStarting(null);
    setBusyJoint(null);
    void stopCommissioningDirectJog(keepalive).catch((caught) => {
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

  const replaceState = useCallback(async (next: CommissioningDirectJointStateResponse) => {
    if (!mounted.current) return;
    setJointState(next);
    setTargets(next.positions);
    const nextFk = await getForwardKinematicsForState({
      positions: next.positions,
      units: next.units,
    });
    if (!mounted.current) return;
    setFk(nextFk);
    setPoseTarget({
      positionMm: { ...nextFk.tcp_pose.position_mm },
      rotationDeg: quaternionToRpyDegrees(nextFk.tcp_pose.orientation_quaternion_xyzw),
    });
  }, []);

  const refreshJointState = useCallback(async () => {
    if (!sessionAuthorized) return;
    await replaceState(await getCommissioningDirectJointState());
  }, [replaceState, sessionAuthorized]);

  useEffect(() => {
    if (!sessionAuthorized) {
      setStatus(null);
      setJointState(null);
      setFk(null);
      return;
    }
    const controller = new AbortController();
    void getCommissioningMotionStatus(controller.signal)
      .catch(() => startCommissioningMotionSession())
      .then((next) => {
        if (!controller.signal.aborted && mounted.current) setStatus(next);
        return refreshJointState();
      })
      .catch((caught) => {
        if (!controller.signal.aborted && mounted.current) setError(errorMessage(caught));
      });
    return () => controller.abort();
  }, [refreshJointState, sessionAuthorized]);

  const authorizeControl = async () => {
    if (!option || !canAuthorize) return;
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

  const revokeControl = async () => {
    stopContinuous(false, true);
    try {
      await revoke();
      await refreshSession();
    } catch (caught) {
      setError(errorMessage(caught));
    }
  };

  const updateParameter = (key: keyof ControlParameters, value: number) => {
    if (!Number.isFinite(value)) return;
    setParameters((current) => ({ ...current, [key]: value }));
  };

  const updateJointTarget = (jointId: string, value: number) => {
    const definition = definitions.find((candidate) => candidate.joint_id === jointId);
    if (!definition || !Number.isFinite(value)) return;
    setTargets((current) => ({
      ...current,
      [jointId]: Math.max(definition.minimum, Math.min(definition.maximum, value)),
    }));
  };

  const step = async (jointId: string, direction: -1 | 1) => {
    const definition = definitions.find((candidate) => candidate.joint_id === jointId);
    if (!definition || !availability.allowed || motionLocked) return;
    const linear = definition.domain_unit === 'mm';
    setBusyJoint(jointId);
    setStarting({ jointId, direction });
    setError(null);
    try {
      await directCommissioningStep(
        jointId,
        direction * (linear ? parameters.railStepMm : parameters.jointStepDeg),
        linear ? parameters.railSpeedMmS : parameters.continuousSpeedDegS,
      );
      await refreshJointState();
    } catch (caught) {
      setError(errorMessage(caught));
    } finally {
      if (mounted.current) setBusyJoint(null);
    }
  };

  const startContinuous = async (jointId: string, direction: -1 | 1) => {
    const definition = definitions.find((candidate) => candidate.joint_id === jointId);
    if (!definition || !availability.allowed || pressed.current || motionLocked) return;
    pressed.current = true;
    const requestGeneration = generation.current + 1;
    generation.current = requestGeneration;
    setBusyJoint(jointId);
    setError(null);
    try {
      await startCommissioningDirectJog(
        jointId,
        direction,
        definition.domain_unit === 'mm'
          ? parameters.railSpeedMmS
          : parameters.continuousSpeedDegS,
      );
      if (!pressed.current || generation.current !== requestGeneration) {
        void stopCommissioningDirectJog();
        return;
      }
      setActive({ jointId, direction });
      setStarting(null);
      setBusyJoint(null);
      heartbeat.current = window.setInterval(() => {
        void heartbeatCommissioningDirectJog().catch((caught) => {
          if (mounted.current) setError(`连续控制保活失败：${errorMessage(caught)}`);
          stopContinuous();
        });
      }, HEARTBEAT_INTERVAL_MS);
    } catch (caught) {
      pressed.current = false;
      setStarting(null);
      setBusyJoint(null);
      setError(errorMessage(caught));
    }
  };

  const holdHandlers = (
    jointId: string,
    direction: -1 | 1,
  ): ButtonHTMLAttributes<HTMLButtonElement> => {
    const start = () => void startContinuous(jointId, direction);
    const stop = () => stopContinuous();
    return {
      onPointerDown: (event: PointerEvent<HTMLButtonElement>) => {
        event.preventDefault();
        start();
      },
      onPointerUp: stop,
      onPointerCancel: stop,
      onLostPointerCapture: stop,
      onKeyDown: (event: KeyboardEvent<HTMLButtonElement>) => {
        if (!event.repeat && (event.key === ' ' || event.key === 'Enter')) start();
      },
      onKeyUp: stop,
      onBlur: stop,
    };
  };

  const moveGroup = async (nextTargets: Record<string, number>) => {
    if (!availability.allowed || groupBusy || active !== null) return;
    setGroupBusy(true);
    setError(null);
    try {
      const result = await moveCommissioningDirectJoints(nextTargets, parameters.durationS);
      await replaceState({
        positions: result.positions,
        units: result.units,
        raw_positions: result.raw_positions,
        captured_at: new Date().toISOString(),
        moving: false,
        message: result.message,
      });
    } catch (caught) {
      setError(errorMessage(caught));
    } finally {
      if (mounted.current) setGroupBusy(false);
    }
  };

  const solvePose = async (target: PoseEditorValue, execute: boolean) => {
    if (!jointState || groupBusy) return;
    setGroupBusy(true);
    setIkError(null);
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
      if (execute) {
        if (!solved.success || !solved.joint_state_optional) {
          throw new Error(`逆解不可达：${solved.termination_reason}`);
        }
        const result = await moveCommissioningDirectJoints(
          solved.joint_state_optional.positions,
          parameters.durationS,
        );
        await replaceState({
          positions: result.positions,
          units: result.units,
          raw_positions: result.raw_positions,
          captured_at: new Date().toISOString(),
          moving: false,
          message: result.message,
        });
      }
    } catch (caught) {
      setIkError(errorMessage(caught));
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
    let next: PoseEditorValue = {
      positionMm: { ...poseTarget.positionMm },
      rotationDeg: { ...poseTarget.rotationDeg },
    };
    if (kind === 'translation') {
      const localDelta = { x: 0, y: 0, z: 0 };
      localDelta[axis] = direction * parameters.cartesianStepMm;
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
      const delta = axisQuaternion(axis, direction * parameters.rotationStepDeg);
      const quaternion = frame === 'TOOL'
        ? multiplyQuaternion(currentQuaternion, delta)
        : multiplyQuaternion(delta, currentQuaternion);
      next = { ...next, rotationDeg: quaternionToRpyDegrees(quaternion) };
    }
    setPoseTarget(next);
    await solvePose(next, true);
  };

  const updatePose = (key: 'positionMm' | 'rotationDeg', axis: Axis, value: number) => {
    if (!Number.isFinite(value)) return;
    setPoseTarget((current) => ({
      ...current,
      [key]: { ...current[key], [axis]: value },
    }));
  };

  const homeTargets = () => moveGroup(Object.fromEntries(
    definitions.map((definition) => [definition.joint_id, definition.home]),
  ));

  return (
    <ControlWorkspaceView
      definitions={definitions}
      emptyControlText="正在等待匹配的机器人配置。"
      enabledJointIds={runtime.profile?.profile.enabled_joints ?? null}
      fk={fk}
      motionPanelProps={{
        activeJog: active,
        cartesianAvailability,
        frame,
        holdHandlers,
        ikError,
        ikPending: groupBusy,
        ikResult,
        jointAvailability: availability,
        jointTargets: targets,
        motionLocked,
        onCartesianJog: cartesianJog,
        onFrameChange: setFrame,
        onHome: homeTargets,
        onJointTargetChange: updateJointTarget,
        onMoveJoints: () => moveGroup(targets),
        onMovePose: () => solvePose(poseTarget, true),
        onParameterChange: updateParameter,
        onPositionChange: (axis, value) => updatePose('positionMm', axis, value),
        onRotationChange: (axis, value) => updatePose('rotationDeg', axis, value),
        onSolveIk: () => solvePose(poseTarget, false),
        onStepJog: step,
        onStop: async () => stopContinuous(false, true),
        parameters,
        pending: groupBusy ? 'motion' : busyJoint,
        poseTarget,
        startingJog: starting,
        stopAllowed: sessionAuthorized,
      }}
      parametersPanelProps={{
        availability,
        motionLocked,
        onChange: updateParameter,
        onHome: homeTargets,
        parameters,
        pending: groupBusy ? 'motion' : busyJoint,
        showHome: false,
      }}
      previewPill="Real readback"
      robot={robot}
      safetyBar={(
        <section className="control-safety-bar control-safety-bar--commissioning" aria-label="运行安全控制">
          <div className="control-safety-bar__status">
            <span className="dry-run-badge">REAL · CONTROL ADAPTER</span>
            <span>{availability.allowed ? '运动已就绪' : availability.reason}</span>
            <span>状态来源：真实机械臂回读</span>
          </div>
          <div className="command-bar">
            <button
              className="command-button command-button--primary"
              disabled={!canAuthorize || pendingAction !== null}
              onClick={() => void authorizeControl()}
              type="button"
            ><PlugZap aria-hidden="true" />{pendingAction === 'authorize' ? '启用中' : '启用真机控制'}</button>
            <button
              className="command-button"
              disabled={!sessionAuthorized || pendingAction !== null}
              onClick={() => void revokeControl()}
              type="button"
            ><Cable aria-hidden="true" />{pendingAction === 'revoke' ? '结束中' : '结束控制'}</button>
            <button
              className="command-button command-button--stop control-global-stop"
              disabled={!sessionAuthorized}
              onClick={() => stopContinuous(false, true)}
              type="button"
            ><CircleStop aria-hidden="true" />停止运动</button>
          </div>
          <p className="software-stop-note">软件停止不能替代物理急停按钮。</p>
        </section>
      )}
      statusPanel={(
        <section className="command-status-panel" aria-label="真实控制适配器状态">
          <header className="product-panel-header"><h2>执行状态</h2></header>
          <p>{active ? `${active.jointId.toUpperCase()} 连续运动中，松手停止` : availability.reason}</p>
          {error ? <p className="real-inline-error" role="alert">{error}</p> : null}
        </section>
      )}
      statusRows={[
        { label: '控制状态', value: <span className="product-status-pill">{sessionAuthorized ? '已授权' : '待授权'}</span> },
        { label: '执行器', value: '真实控制适配器' },
        { label: '回读', value: jointState ? '已同步' : '等待同步' },
        { label: '会话状态', value: status?.state ?? 'IDLE' },
        { label: '更新时间', value: jointState ? new Date(jointState.captured_at).toLocaleTimeString() : '—' },
      ]}
      viewerAriaLabel={`${robot?.variant ?? runtime.profile?.profile.variant ?? 'MOMO'} 机械臂真实回读三维视图`}
      viewerBadgeLabel="3D · REAL READBACK"
      viewerPlaceholder="启用真机控制后读取机械臂状态。"
      viewerPlaceholderDetail="REAL READBACK · 页面不会自动连接硬件"
      viewerSafetyNote="仅显示真实回读 · 三维视图本身不发送控制指令"
    />
  );
}
