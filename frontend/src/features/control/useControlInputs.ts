import { useCallback, useEffect, useMemo, useRef, useState } from 'react';

import type {
  CartesianFrame,
  ForwardKinematicsResponse,
  ProfileJointDefinition,
  RobotStatus,
  Vector3,
} from '../../api/types';
import { clamp, quaternionToRpyDegrees } from './controlMath';
import {
  DEFAULT_CONTROL_PARAMETERS,
  type ControlParameters,
  type PoseEditorValue,
} from './controlTypes';

const PARAMETER_LIMITS: Record<keyof ControlParameters, readonly [number, number]> = {
  jointStepDeg: [0.1, 15],
  railStepMm: [0.1, 25],
  continuousSpeedDegS: [0.1, 45],
  railSpeedMmS: [0.1, 50],
  cartesianStepMm: [0.1, 25],
  rotationStepDeg: [0.1, 10],
  durationS: [0.1, 60],
  speedScale: [0.05, 1],
};

const EMPTY_POSE: PoseEditorValue = {
  positionMm: { x: 0, y: 0, z: 0 },
  rotationDeg: { x: 0, y: 0, z: 0 },
};

export function useControlInputs(options: {
  robot: RobotStatus | null;
  definitions: ProfileJointDefinition[];
  fk: ForwardKinematicsResponse | null;
}) {
  const [parameters, setParameters] = useState<ControlParameters>(() => ({
    ...DEFAULT_CONTROL_PARAMETERS,
  }));
  const [jointTargets, setJointTargets] = useState<Record<string, number>>({});
  const [frame, setFrame] = useState<CartesianFrame>('BASE');
  const [poseTarget, setPoseTarget] = useState<PoseEditorValue>(EMPTY_POSE);
  const initializedPoseFor = useRef<string | null>(null);
  const initializedJointsFor = useRef<string | null>(null);
  const definitionMap = useMemo(
    () => new Map(options.definitions.map((definition) => [definition.joint_id, definition])),
    [options.definitions],
  );
  const jointSignature = options.definitions.map((definition) => definition.joint_id).join(':');

  const resetJointTargets = useCallback(() => {
    const robot = options.robot;
    if (!robot) return;
    setJointTargets(
      Object.fromEntries(
        options.definitions.map((definition) => [
          definition.joint_id,
          robot.positions[definition.joint_id] ?? definition.home,
        ]),
      ),
    );
  }, [options.definitions, options.robot]);

  useEffect(() => {
    const initializationKey = options.robot
      ? `${options.robot.variant}:${options.robot.connected}:${jointSignature}`
      : null;
    if (!initializationKey || initializedJointsFor.current === initializationKey) return;
    initializedJointsFor.current = initializationKey;
    resetJointTargets();
  }, [jointSignature, options.robot, resetJointTargets]);

  useEffect(() => {
    const fk = options.fk;
    const initializationKey = fk
      ? `${fk.profile_fingerprint}:${fk.kinematics_fingerprint}`
      : null;
    if (!fk || initializedPoseFor.current === initializationKey) return;
    initializedPoseFor.current = initializationKey;
    setPoseTarget({
      positionMm: { ...fk.tcp_pose.position_mm },
      rotationDeg: quaternionToRpyDegrees(fk.tcp_pose.orientation_quaternion_xyzw),
    });
  }, [options.fk]);

  const updateParameter = useCallback(
    <Key extends keyof ControlParameters>(key: Key, value: ControlParameters[Key]) => {
      if (!Number.isFinite(value)) return;
      const [minimum, maximum] = PARAMETER_LIMITS[key];
      setParameters((current) => ({ ...current, [key]: clamp(value, minimum, maximum) }));
    },
    [],
  );

  const updateJointTarget = useCallback(
    (jointId: string, value: number) => {
      const definition = definitionMap.get(jointId);
      if (!definition || !Number.isFinite(value)) return;
      setJointTargets((current) => ({
        ...current,
        [jointId]: clamp(value, definition.minimum, definition.maximum),
      }));
    },
    [definitionMap],
  );

  const updatePoseVector = useCallback(
    (key: 'positionMm' | 'rotationDeg', axis: keyof Vector3, value: number) => {
      if (!Number.isFinite(value)) return;
      setPoseTarget((current) => ({
        ...current,
        [key]: { ...current[key], [axis]: value },
      }));
    },
    [],
  );

  return {
    parameters,
    updateParameter,
    jointTargets,
    updateJointTarget,
    resetJointTargets,
    frame,
    setFrame,
    poseTarget,
    updatePosition: (axis: keyof Vector3, value: number) =>
      updatePoseVector('positionMm', axis, value),
    updateRotation: (axis: keyof Vector3, value: number) =>
      updatePoseVector('rotationDeg', axis, value),
  };
}
