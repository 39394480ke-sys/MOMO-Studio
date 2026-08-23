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
import { useRuntimeStatus } from '../components/runtimeStatusContext';
import { CartesianControlPanel } from '../features/control/CartesianControlPanel';
import { CommandStatusPanel } from '../features/control/CommandStatusPanel';
import { ControlSafetyBar } from '../features/control/ControlSafetyBar';
import { JointControlPanel } from '../features/control/JointControlPanel';
import { MotionParametersPanel } from '../features/control/MotionParametersPanel';
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
  if (!value) return 'Waiting for backend';
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
  stale: boolean;
  robot: ReturnType<typeof useRuntimeStatus>['robot'];
  hasCompleteProfile: boolean;
  fk: ReturnType<typeof useForwardKinematics>['fk'];
  expectedStateSequence: number | null;
}): MotionAvailability {
  if (!options.backendOnline) return { allowed: false, reason: 'Backend unavailable' };
  if (options.stale) return { allowed: false, reason: 'Backend state is stale' };
  if (!options.robot) return { allowed: false, reason: 'Waiting for robot state' };
  if (!options.robot.connected) {
    return { allowed: false, reason: 'Connect the Dry Run robot to enable motion' };
  }
  if (!options.hasCompleteProfile) {
    return { allowed: false, reason: 'Active profile does not match this robot' };
  }
  if (!options.fk) {
    return { allowed: false, reason: 'Waiting for current forward kinematics' };
  }
  if (
    options.expectedStateSequence === null ||
    options.fk.state_sequence !== options.expectedStateSequence
  ) {
    return { allowed: false, reason: 'Synchronizing robot state and forward kinematics' };
  }
  if (options.fk.profile_fingerprint !== options.robot.profile_fingerprint) {
    return { allowed: false, reason: 'Profile fingerprint changed; refresh before moving' };
  }
  return { allowed: true, reason: 'Dry Run motion is ready' };
}

export function ControlPage() {
  const runtime = useRuntimeStatus();
  const backendOnline = runtime.backend === 'connected';
  const socket = useRobotSocket(backendOnline && !runtime.stale);
  const liveSocket = socket.connectionState === 'open' ? socket.snapshot : null;
  const robot = liveSocket?.robot ?? runtime.robot;
  const effectiveStale = runtime.stale || robot?.stale !== false;
  const definitions = useMemo(
    () => definitionsFor(runtime.profile, robot?.variant),
    [robot?.variant, runtime.profile],
  );
  const stateSequence = liveSocket?.stateSequence ?? robot?.state_sequence ?? null;
  const kinematics = useForwardKinematics({
    enabled: backendOnline && !effectiveStale && robot !== null,
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
  const availability = useMemo(
    () => commands.stopUncertain
      ? { allowed: false, reason: 'Motion safety state is uncertain; use STOP MOTION' }
      : runtime.pendingAction !== null
        ? { allowed: false, reason: 'Robot lifecycle action pending · motion disabled' }
      : availabilityFor({
          backendOnline,
          stale: effectiveStale,
          robot,
          hasCompleteProfile:
            definitions.length > 0 && definitions.length === runtime.profile?.profile.enabled_joints.length,
          fk: kinematics.fk,
          expectedStateSequence: stateSequence,
        }),
    [
      backendOnline,
      definitions.length,
      kinematics.fk,
      robot,
      runtime.profile,
      runtime.pendingAction,
      effectiveStale,
      stateSequence,
      commands.stopUncertain,
    ],
  );
  const motionLocked =
    commands.stopUncertain ||
    runtime.pendingAction !== null ||
    (commands.command !== null && !TERMINAL_COMMAND_STATES.has(commands.command.state));

  const requestContext = useCallback(
    (kind: string): MotionRequestContext | null => {
      if (!availability.allowed || motionLocked || !robot || !kinematics.fk) return null;
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
      availability.allowed,
      inputs.parameters.speedScale,
      kinematics.fk,
      motionLocked,
      robot,
      liveSocket?.stateSequence,
    ],
  );

  const buildJogRequest = useCallback(
    ({ jointId, direction }: { jointId: string; direction: -1 | 1 }) => {
      const context = requestContext('hold-jog');
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
    enabled: availability.allowed,
    canStart: commands.pending === null && !motionLocked,
    buildRequest: buildJogRequest,
    onSubmission: registerJog,
    onError: commands.reportError,
  });

  const moveAllJoints = useCallback(async () => {
    const context = requestContext('move-joints');
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
  }, [commands, definitions, inputs.jointTargets, inputs.parameters.durationS, requestContext]);

  const stepJoint = useCallback(
    async (jointId: string, direction: -1 | 1) => {
      const context = requestContext('jog-step');
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
    [commands, definitions, inputs.parameters, requestContext],
  );

  const cartesianJog = useCallback(
    async (kind: CartesianKind, axis: Axis, direction: -1 | 1) => {
      const context = requestContext('cartesian-jog');
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
    [commands, inputs.frame, inputs.parameters, requestContext],
  );

  const targetPose = useCallback((): TcpPose => ({
    frame: kinematics.fk?.tcp_pose.frame ?? 'base',
    position_mm: { ...inputs.poseTarget.positionMm },
    orientation_quaternion_xyzw: rpyDegreesToQuaternion(inputs.poseTarget.rotationDeg),
  }), [inputs.poseTarget, kinematics.fk?.tcp_pose.frame]);

  const solveIk = useCallback(async () => {
    if (!robot || !availability.allowed) return;
    await ik.solve({
      target_pose: targetPose(),
      position_unit: 'mm',
      orientation_unit: 'quaternion_xyzw',
      seed_joint_state: { positions: robot.positions, units: robot.units },
      position_only: false,
      maximum_iterations: 200,
    });
  }, [availability.allowed, ik, robot, targetPose]);

  const moveToPose = useCallback(async () => {
    const context = requestContext('move-pose');
    if (!context) return;
    await commands.movePose({
      ...context,
      target_pose: targetPose(),
      position_unit: 'mm',
      orientation_unit: 'quaternion_xyzw',
      duration_s: inputs.parameters.durationS,
    });
  }, [commands, inputs.parameters.durationS, requestContext, targetPose]);

  const home = useCallback(async () => {
    const context = requestContext('home');
    if (!context) return;
    await commands.home({
      ...context,
      confirm: 'HOME',
      duration_s: inputs.parameters.durationS,
    });
  }, [commands, inputs.parameters.durationS, requestContext]);

  const stop = useCallback(async () => {
    deadman.stopActive();
    await commands.stop();
  }, [commands, deadman]);

  return (
    <div className="page control-workspace">
      <PageIntro
        title="Control"
        description="Stage 3: one safety-gated Dry Run workspace for direct robot motion."
        detail="Keyed V1/V2 joints, TCP kinematics, Cartesian motion, and deadman jog leases."
      />

      {(runtime.error || effectiveStale) ? (
        <div className="runtime-alert" role="alert">
          <TriangleAlert aria-hidden="true" />
          <div>
            <strong>
              {effectiveStale
                ? runtime.backend === 'unavailable'
                  ? 'Backend unavailable · showing stale state'
                  : 'Robot state stale · motion disabled'
                : 'Request failed'}
            </strong>
            {runtime.error ? <span>{runtime.error}</span> : null}
          </div>
          <button aria-label="Retry backend request" onClick={() => void runtime.refresh()} type="button">
            <RefreshCw aria-hidden="true" />
          </button>
        </div>
      ) : null}

      <ControlSafetyBar
        availability={availability}
        backendOnline={backendOnline}
        lifecyclePending={runtime.pendingAction}
        motionPending={commands.pending}
        onConnect={runtime.connect}
        onDisconnect={runtime.disconnect}
        onStop={stop}
        robot={robot}
        socketState={socket.connectionState}
        stale={effectiveStale}
      />

      <section className="control-overview" aria-labelledby="active-robot-title">
        <div className="section-heading section-heading--compact">
          <div>
            <p className="section-kicker">Active Robot</p>
            <h2 id="active-robot-title">{robot ? `${robot.robot_id} · ${robot.variant}` : 'Waiting for backend'}</h2>
          </div>
          <div className={`connection-state connection-state--${robot?.connection_state.toLowerCase() ?? 'pending'}`}>
            <span aria-hidden="true" />
            {robot?.connection_state ?? 'PENDING'}
          </div>
        </div>
        <dl className="runtime-facts">
          <div><dt>Mode</dt><dd>{robot?.control_mode ?? 'DRY_RUN'}</dd></div>
          <div><dt>Profile</dt><dd>{robot?.profile_verification_status ?? 'Pending'}</dd></div>
          <div><dt>Calibration</dt><dd>{runtime.calibration?.status ?? robot?.calibration_status ?? 'Pending'}</dd></div>
          <div><dt>Updated</dt><dd>{formatUpdatedAt(robot?.updated_at)}</dd></div>
        </dl>
      </section>

      <div className="control-workspace-grid">
        {robot && definitions.length > 0 ? (
          <JointControlPanel
            activeJog={deadman.active}
            availability={availability}
            definitions={definitions}
            holdHandlers={deadman.handlersFor}
            onMoveJoints={moveAllJoints}
            onResetTargets={inputs.resetJointTargets}
            onStepJog={stepJoint}
            onTargetChange={inputs.updateJointTarget}
            parameters={inputs.parameters}
            pending={commands.pending}
            motionLocked={motionLocked}
            robot={robot}
            startingJog={deadman.starting}
            targets={inputs.jointTargets}
          />
        ) : (
          <section className="control-panel control-panel--joints">
            <p className="empty-state">Joint controls will appear after a matching robot profile loads.</p>
          </section>
        )}

        <CartesianControlPanel
          availability={availability}
          fk={kinematics.fk}
          fkLoading={kinematics.loading}
          frame={inputs.frame}
          ikError={ik.error}
          ikPending={ik.pending}
          ikResult={ik.result}
          onCartesianJog={cartesianJog}
          onFrameChange={inputs.setFrame}
          onMovePose={moveToPose}
          onPositionChange={inputs.updatePosition}
          onRotationChange={inputs.updateRotation}
          onSolveIk={solveIk}
          parameters={inputs.parameters}
          pending={commands.pending}
          motionLocked={motionLocked}
          target={inputs.poseTarget}
        />

        <div className="control-workspace-sidebar">
          <MotionParametersPanel
            availability={availability}
            onChange={inputs.updateParameter}
            onHome={home}
            parameters={inputs.parameters}
            pending={commands.pending}
            motionLocked={motionLocked}
          />
          <CommandStatusPanel
            command={commands.command}
            commandError={commands.error}
            fkError={kinematics.error}
            rejectedPreflight={commands.rejectedPreflight}
            robotError={null}
          />
        </div>
      </div>
    </div>
  );
}
