import { useCallback, useMemo } from 'react';
import { RefreshCw, TriangleAlert } from 'lucide-react';

import type {
  JogSessionResponse,
  MotionRequestContext,
  ProfileJointDefinition,
  RobotVariant,
  TcpPose,
  Vector3,
} from '../api/types';
import { PageIntro } from '../components/PageIntro';
import {
  realCapabilityAvailability,
  useRealSession,
  type RealCapabilityAvailability,
} from '../components/realSessionContext';
import { useRuntimeStatus } from '../components/runtimeStatusContext';
import { CommandStatusPanel } from '../features/control/CommandStatusPanel';
import { ControlSafetyBar } from '../features/control/ControlSafetyBar';
import { CommissioningControlAdapter } from '../features/control/CommissioningControlAdapter';
import { ControlWorkspaceView } from '../features/control/ControlWorkspaceView';
import {
  createIdempotencyKey,
  rpyDegreesToQuaternion,
} from '../features/control/controlMath';
import type { MotionAvailability } from '../features/control/controlTypes';
import { useControlInputs } from '../features/control/useControlInputs';
import { useDeadmanJog } from '../features/control/useDeadmanJog';
import { useForwardKinematics } from '../features/control/useForwardKinematics';
import { useInverseKinematics } from '../features/control/useInverseKinematics';
import { useMotionCommands } from '../features/control/useMotionCommands';
import { useRobotSocket } from '../features/control/useRobotSocket';

type CartesianKind = 'translation' | 'rotation';
type Axis = keyof Vector3;
const TERMINAL_COMMAND_STATES = new Set([
  'STOPPED',
  'CANCELLED',
  'COMPLETED',
  'FAULTED',
  'REJECTED',
]);

function formatUpdatedAt(value: string | undefined): string {
  if (!value) return '等待后端';
  return new Intl.DateTimeFormat(undefined, {
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  }).format(new Date(value));
}

function definitionsFor(
  profile: ReturnType<typeof useRuntimeStatus>['profile'],
  variant: RobotVariant | undefined,
): ProfileJointDefinition[] {
  if (!profile || profile.profile.variant !== variant) return [];
  const byId = new Map(
    profile.profile.joint_definitions.map((definition) => [definition.joint_id, definition]),
  );
  return profile.profile.enabled_joints.flatMap((jointId) => {
    const definition = byId.get(jointId);
    return definition ? [definition] : [];
  });
}

function availabilityFor(options: {
  backendOnline: boolean;
  controlMode: ReturnType<typeof useRuntimeStatus>['controlMode'];
  hardwareAccessPolicy: ReturnType<typeof useRuntimeStatus>['hardwareAccessPolicy'];
  realMotionEnabled: boolean;
  stale: boolean;
  robot: ReturnType<typeof useRuntimeStatus>['robot'];
  hasCompleteProfile: boolean;
  fk: ReturnType<typeof useForwardKinematics>['fk'];
  expectedStateSequence: number | null;
  realCapability: RealCapabilityAvailability;
}): MotionAvailability {
  if (!options.backendOnline) return { allowed: false, reason: '后端不可用' };
  if (options.controlMode === 'REAL') {
    if (!options.realCapability.allowed) {
      return { allowed: false, reason: options.realCapability.reason };
    }
  } else if (
    options.hardwareAccessPolicy !== 'DISABLED' ||
    options.realMotionEnabled
  ) {
    return {
      allowed: false,
      reason: 'Dry Run hardware isolation is unavailable',
    };
  }
  if (options.stale) return { allowed: false, reason: '后端状态已过期' };
  if (!options.robot) return { allowed: false, reason: '等待机器人状态' };
  if (!options.robot.connected) {
    return {
      allowed: false,
      reason: options.controlMode === 'REAL'
        ? '后端报告真实机器人未连接'
        : '连接仿真机器人后即可启用运动',
    };
  }
  if (!options.hasCompleteProfile) {
    return { allowed: false, reason: '活动配置与此机器人不匹配' };
  }
  if (!options.fk) {
    return { allowed: false, reason: '等待当前正向运动学结果' };
  }
  if (
    options.expectedStateSequence === null ||
    options.fk.state_sequence !== options.expectedStateSequence
  ) {
    return { allowed: false, reason: '正在同步机器人状态与正向运动学' };
  }
  if (options.fk.profile_fingerprint !== options.robot.profile_fingerprint) {
    return { allowed: false, reason: '配置指纹已变化；请刷新后再运动' };
  }
  return {
    allowed: true,
    reason: options.controlMode === 'REAL' ? '后端能力已授权' : '仿真运动已就绪',
  };
}

export function ControlPage() {
  const runtime = useRuntimeStatus();
  const { summary: realSession } = useRealSession();
  const directCommissioningControl = runtime.controlMode === 'REAL' && (
    realSession.authorizationOptions.some(
      (option) => option.purpose === 'COMMISSIONING_MOTION_TEST' && option.authorizable,
    ) || realSession.session?.purpose === 'COMMISSIONING_MOTION_TEST'
  );
  const backendOnline = runtime.backend === 'connected';
  const dryRunWorkspace =
    runtime.controlMode === 'DRY RUN' &&
    runtime.hardwareAccessPolicy === 'DISABLED' &&
    runtime.realMotionEnabled === false;
  const socket = useRobotSocket(backendOnline && !runtime.stale && dryRunWorkspace);
  const liveSocket = socket.connectionState === 'open' ? socket.snapshot : null;
  const robot = liveSocket?.robot ?? runtime.robot;
  const effectiveStale = runtime.stale || robot?.stale !== false;
  const definitions = useMemo(
    () => definitionsFor(runtime.profile, robot?.variant),
    [robot?.variant, runtime.profile],
  );
  const stateSequence = liveSocket?.stateSequence ?? robot?.state_sequence ?? null;
  const realJointCapability = realCapabilityAvailability(realSession, 'real_joint_motion');
  const realCartesianCapability = realCapabilityAvailability(realSession, 'real_cartesian_motion');
  const realKinematicsAuthorized = runtime.controlMode === 'REAL' &&
    (realJointCapability.allowed || realCartesianCapability.allowed);
  const kinematics = useForwardKinematics({
    enabled: backendOnline && !effectiveStale && robot !== null &&
      (dryRunWorkspace || realKinematicsAuthorized),
    stateSequence: liveSocket?.tcpPose ? null : stateSequence,
    socketTcpPose: liveSocket?.tcpPose ?? null,
    socketStateSequence: liveSocket?.stateSequence ?? null,
  });
  const inputs = useControlInputs({ robot, definitions, fk: kinematics.fk });
  const ik = useInverseKinematics();
  const commands = useMotionCommands({
    socketCommand: liveSocket?.command ?? null,
    refreshRuntime: runtime.refresh,
  });
  const jointAvailability = useMemo(
    () => commands.stopUncertain
      ? { allowed: false, reason: '运动安全状态不确定；请停止运动' }
      : runtime.pendingAction !== null
        ? { allowed: false, reason: '机器人生命周期操作进行中 · 运动已禁用' }
      : availabilityFor({
          backendOnline,
          controlMode: runtime.controlMode,
          hardwareAccessPolicy: runtime.hardwareAccessPolicy,
          realMotionEnabled: runtime.realMotionEnabled,
          stale: effectiveStale,
          robot,
          hasCompleteProfile:
            definitions.length > 0 && definitions.length === runtime.profile?.profile.enabled_joints.length,
          fk: kinematics.fk,
          expectedStateSequence: stateSequence,
          realCapability: realJointCapability,
        }),
    [
      backendOnline,
      definitions.length,
      kinematics.fk,
      robot,
      runtime.profile,
      runtime.pendingAction,
      runtime.controlMode,
      runtime.hardwareAccessPolicy,
      runtime.realMotionEnabled,
      effectiveStale,
      stateSequence,
      commands.stopUncertain,
      realJointCapability,
    ],
  );
  const cartesianAvailability = useMemo(
    () => commands.stopUncertain
      ? { allowed: false, reason: '运动安全状态不确定；请停止运动' }
      : runtime.pendingAction !== null
        ? { allowed: false, reason: '机器人生命周期操作进行中 · 运动已禁用' }
        : availabilityFor({
            backendOnline,
            controlMode: runtime.controlMode,
            hardwareAccessPolicy: runtime.hardwareAccessPolicy,
            realMotionEnabled: runtime.realMotionEnabled,
            stale: effectiveStale,
            robot,
            hasCompleteProfile:
              definitions.length > 0 && definitions.length === runtime.profile?.profile.enabled_joints.length,
            fk: kinematics.fk,
            expectedStateSequence: stateSequence,
            realCapability: realCartesianCapability,
          }),
    [
      backendOnline,
      definitions.length,
      kinematics.fk,
      robot,
      runtime.profile,
      runtime.pendingAction,
      runtime.controlMode,
      runtime.hardwareAccessPolicy,
      runtime.realMotionEnabled,
      effectiveStale,
      stateSequence,
      commands.stopUncertain,
      realCartesianCapability,
    ],
  );
  const safetyAvailability = jointAvailability.allowed
    ? jointAvailability
    : cartesianAvailability.allowed
      ? cartesianAvailability
      : jointAvailability;
  const motionLocked =
    commands.stopUncertain ||
    runtime.pendingAction !== null ||
    (commands.command !== null && !TERMINAL_COMMAND_STATES.has(commands.command.state));
  const stopAllowed =
    (dryRunWorkspace || safetyAvailability.allowed || motionLocked) &&
    backendOnline &&
    !effectiveStale &&
    commands.pending !== 'stop';

  const requestContext = useCallback(
    (kind: string, requiredAvailability: MotionAvailability): MotionRequestContext | null => {
      if (!requiredAvailability.allowed || motionLocked || !robot || !kinematics.fk) return null;
      return {
        source: 'CONTROL',
        expected_state_sequence: liveSocket?.stateSequence ?? robot.state_sequence,
        expected_profile_fingerprint: robot.profile_fingerprint,
        expected_kinematics_fingerprint: kinematics.fk.kinematics_fingerprint,
        speed_scale: inputs.parameters.speedScale,
        idempotency_key: createIdempotencyKey(kind),
      };
    },
    [
      inputs.parameters.speedScale,
      kinematics.fk,
      motionLocked,
      robot,
      liveSocket?.stateSequence,
    ],
  );

  const buildJogRequest = useCallback(
    ({ jointId, direction }: { jointId: string; direction: -1 | 1 }) => {
      const context = requestContext('hold-jog', jointAvailability);
      const definition = definitions.find((candidate) => candidate.joint_id === jointId);
      if (!context || !definition) return null;
      return {
        ...context,
        joint_id: jointId,
        direction,
        speed_units_s:
          definition.domain_unit === 'mm'
            ? inputs.parameters.railSpeedMmS
            : inputs.parameters.continuousSpeedDegS,
        unit: definition.domain_unit,
      };
    },
    [
      definitions,
      inputs.parameters.continuousSpeedDegS,
      inputs.parameters.railSpeedMmS,
      requestContext,
      jointAvailability,
    ],
  );

  const registerJog = useCallback(
    (response: JogSessionResponse) => {
      commands.registerStatus({
        command_id: response.command_id,
        state: response.status,
        progress: 0,
        message: `Jog lease ${response.lease_expires_in_ms} ms`,
      });
    },
    [commands],
  );
  const deadman = useDeadmanJog({
    enabled: jointAvailability.allowed,
    canStart: commands.pending === null && !motionLocked,
    buildRequest: buildJogRequest,
    onSubmission: registerJog,
    onError: commands.reportError,
  });

  const moveAllJoints = useCallback(async () => {
    const context = requestContext('move-joints', jointAvailability);
    if (!context) return;
    await commands.moveJoints({
      ...context,
      joint_state: {
        positions: Object.fromEntries(
          definitions.map((definition) => [
            definition.joint_id,
            inputs.jointTargets[definition.joint_id] ?? definition.home,
          ]),
        ),
        units: Object.fromEntries(
          definitions.map((definition) => [definition.joint_id, definition.domain_unit]),
        ),
      },
      duration_s: inputs.parameters.durationS,
    });
  }, [commands, definitions, inputs.jointTargets, inputs.parameters.durationS, jointAvailability, requestContext]);

  const stepJoint = useCallback(
    async (jointId: string, direction: -1 | 1) => {
      const context = requestContext('jog-step', jointAvailability);
      const definition = definitions.find((candidate) => candidate.joint_id === jointId);
      if (!context || !definition) return;
      await commands.jogStep({
        ...context,
        joint_id: jointId,
        delta:
          direction *
          (definition.domain_unit === 'mm'
            ? inputs.parameters.railStepMm
            : inputs.parameters.jointStepDeg),
        unit: definition.domain_unit,
        duration_s: Math.min(inputs.parameters.durationS, 1),
      });
    },
    [commands, definitions, inputs.parameters, jointAvailability, requestContext],
  );

  const cartesianJog = useCallback(
    async (kind: CartesianKind, axis: Axis, direction: -1 | 1) => {
      const context = requestContext('cartesian-jog', cartesianAvailability);
      if (!context) return;
      const translation: Vector3 = { x: 0, y: 0, z: 0 };
      const rotation: Vector3 = { x: 0, y: 0, z: 0 };
      if (kind === 'translation') {
        translation[axis] = direction * inputs.parameters.cartesianStepMm;
      } else {
        rotation[axis] = direction * inputs.parameters.rotationStepDeg;
      }
      await commands.cartesianJog({
        ...context,
        delta_position_mm: translation,
        delta_rotation_deg: rotation,
        frame: inputs.frame,
        translation_unit: 'mm',
        rotation_unit: 'deg',
        duration_s: Math.min(inputs.parameters.durationS, 1),
      });
    },
    [cartesianAvailability, commands, inputs.frame, inputs.parameters, requestContext],
  );

  const targetPose = useCallback((): TcpPose => ({
    frame: kinematics.fk?.tcp_pose.frame ?? 'base',
    position_mm: { ...inputs.poseTarget.positionMm },
    orientation_quaternion_xyzw: rpyDegreesToQuaternion(inputs.poseTarget.rotationDeg),
  }), [inputs.poseTarget, kinematics.fk?.tcp_pose.frame]);

  const solveIk = useCallback(async () => {
    if (!robot || !cartesianAvailability.allowed) return;
    await ik.solve({
      target_pose: targetPose(),
      position_unit: 'mm',
      orientation_unit: 'quaternion_xyzw',
      seed_joint_state: { positions: robot.positions, units: robot.units },
      position_only: false,
      maximum_iterations: 200,
    });
  }, [cartesianAvailability.allowed, ik, robot, targetPose]);

  const moveToPose = useCallback(async () => {
    const context = requestContext('move-pose', cartesianAvailability);
    if (!context) return;
    await commands.movePose({
      ...context,
      target_pose: targetPose(),
      position_unit: 'mm',
      orientation_unit: 'quaternion_xyzw',
      duration_s: inputs.parameters.durationS,
    });
  }, [cartesianAvailability, commands, inputs.parameters.durationS, requestContext, targetPose]);

  const home = useCallback(async () => {
    const context = requestContext('home', jointAvailability);
    if (!context) return;
    await commands.home({
      ...context,
      confirm: 'HOME',
      duration_s: inputs.parameters.durationS,
    });
  }, [commands, inputs.parameters.durationS, jointAvailability, requestContext]);

  const stop = useCallback(async () => {
    deadman.stopActive();
    await commands.stop();
  }, [commands, deadman]);

  return (
    <div className="page control-workspace">
      <PageIntro
        title="机器人控制"
        description="统一控制工作区；运行模式只切换执行器，不切换前端页面。"
        detail="支持 V1/V2 关节、TCP 运动学、笛卡尔运动与按住点动安全租约。"
      />

      {(runtime.error || effectiveStale) ? (
        <div className="runtime-alert" role="alert">
          <TriangleAlert aria-hidden="true" />
          <div>
            <strong>
              {effectiveStale
                ? runtime.backend === 'unavailable'
                  ? '后端不可用 · 正在显示过期状态'
                  : '机器人状态已过期 · 运动已禁用'
                : '请求失败'}
            </strong>
            {runtime.error ? <span>{runtime.error}</span> : null}
          </div>
          <button aria-label="重试后端请求" onClick={() => void runtime.refresh()} type="button">
            <RefreshCw aria-hidden="true" />
          </button>
        </div>
      ) : null}

      {directCommissioningControl ? <CommissioningControlAdapter /> : (
        <ControlWorkspaceView
          definitions={definitions}
          emptyControlText="加载匹配的机器人配置后将显示关节控制。"
          enabledJointIds={runtime.profile?.profile.enabled_joints ?? null}
          fk={kinematics.fk}
          motionPanelProps={{
            activeJog: deadman.active,
            cartesianAvailability,
            frame: inputs.frame,
            holdHandlers: deadman.handlersFor,
            ikError: ik.error,
            ikPending: ik.pending,
            ikResult: ik.result,
            jointAvailability,
            jointTargets: inputs.jointTargets,
            motionLocked,
            onCartesianJog: cartesianJog,
            onFrameChange: inputs.setFrame,
            onHome: home,
            onJointTargetChange: inputs.updateJointTarget,
            onMoveJoints: moveAllJoints,
            onMovePose: moveToPose,
            onParameterChange: inputs.updateParameter,
            onPositionChange: inputs.updatePosition,
            onRotationChange: inputs.updateRotation,
            onSolveIk: solveIk,
            onStepJog: stepJoint,
            onStop: stop,
            parameters: inputs.parameters,
            pending: commands.pending,
            poseTarget: inputs.poseTarget,
            startingJog: deadman.starting,
            stopAllowed,
          }}
          parametersPanelProps={{
            availability: jointAvailability,
            motionLocked,
            onChange: inputs.updateParameter,
            onHome: home,
            parameters: inputs.parameters,
            pending: commands.pending,
            showHome: false,
          }}
          previewPill="Base frame"
          robot={robot}
          safetyBar={(
            <ControlSafetyBar
              availability={safetyAvailability}
              backendOnline={backendOnline}
              lifecyclePending={runtime.pendingAction}
              lifecycleAllowed={dryRunWorkspace}
              stopAllowed={stopAllowed}
              modeLabel={runtime.hardwareAccessPolicy === 'READ_ONLY'
                ? 'READ ONLY'
                : runtime.controlMode === 'DRY RUN'
                  ? 'DRY RUN'
                  : safetyAvailability.allowed
                    ? 'REAL CAPABILITY AUTHORIZED'
                    : 'REAL MOTION LOCKED'}
              motionPending={commands.pending}
              onConnect={runtime.connect}
              onDisconnect={runtime.disconnect}
              onStop={stop}
              robot={robot}
              socketState={socket.connectionState}
              stale={effectiveStale}
            />
          )}
          statusPanel={(
            <CommandStatusPanel
              command={commands.command}
              commandError={commands.error}
              fkError={kinematics.error}
              rejectedPreflight={commands.rejectedPreflight}
              robotError={null}
            />
          )}
          statusRows={[
            { label: '运行状态', value: <span className="product-status-pill">{robot?.connected ? '待机' : '未连接'}</span> },
            { label: '力矩', value: '不可用' },
            {
              label: '位置回读',
              value: <span className={socket.connectionState === 'open' ? 'product-status-pill product-status-pill--success' : 'product-status-pill'}>{socket.connectionState === 'open' ? 'WebSocket 正常' : 'REST 同步'}</span>,
            },
            { label: '状态序列', value: stateSequence ?? '—' },
            { label: '更新时间', value: formatUpdatedAt(robot?.updated_at) },
          ]}
          viewerAriaLabel={`${robot?.variant ?? runtime.profile?.profile.variant ?? 'MOMO'} 机械臂实时状态三维视图`}
          viewerBadgeLabel="3D · SIMULATION ONLY"
          viewerPlaceholder="正在等待机器人 Profile 与状态。"
          viewerPlaceholderDetail="SIMULATION ONLY · 视图不拥有运动控制权"
          viewerSafetyNote="仅用于可视化 · 不连接或控制实体机械臂"
        />
      )}
    </div>
  );
}
