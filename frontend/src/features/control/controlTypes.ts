import type { Vector3 } from '../../api/types';

export interface ControlParameters {
  jointStepDeg: number;
  railStepMm: number;
  continuousSpeedDegS: number;
  railSpeedMmS: number;
  cartesianStepMm: number;
  rotationStepDeg: number;
  durationS: number;
  speedScale: number;
}

export type ControlParameterChange = (key: keyof ControlParameters, value: number) => void;

export interface PoseEditorValue {
  positionMm: Vector3;
  rotationDeg: Vector3;
}

export interface MotionAvailability {
  allowed: boolean;
  reason: string;
}

export const CONTROL_SPEED_LEVELS = [
  { label: '极低', scale: 0.15, jointStep: 0.5, railStep: 1, rotationStep: 0.5 },
  { label: '低', scale: 0.3, jointStep: 1, railStep: 2.5, rotationStep: 1 },
  { label: '中', scale: 0.5, jointStep: 2, railStep: 5, rotationStep: 3 },
  { label: '高', scale: 0.75, jointStep: 3, railStep: 10, rotationStep: 4 },
  { label: '极高', scale: 1, jointStep: 5, railStep: 15, rotationStep: 5 },
] as const;

const DEFAULT_SPEED_LEVEL = CONTROL_SPEED_LEVELS[2];

export const DEFAULT_CONTROL_PARAMETERS: Readonly<ControlParameters> = Object.freeze({
  jointStepDeg: DEFAULT_SPEED_LEVEL.jointStep,
  railStepMm: DEFAULT_SPEED_LEVEL.railStep,
  continuousSpeedDegS: 45 * DEFAULT_SPEED_LEVEL.scale,
  railSpeedMmS: 50 * DEFAULT_SPEED_LEVEL.scale,
  cartesianStepMm: DEFAULT_SPEED_LEVEL.railStep,
  rotationStepDeg: DEFAULT_SPEED_LEVEL.rotationStep,
  durationS: 1,
  speedScale: DEFAULT_SPEED_LEVEL.scale,
});
