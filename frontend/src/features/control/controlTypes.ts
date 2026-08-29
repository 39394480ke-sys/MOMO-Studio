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

export const DEFAULT_CONTROL_PARAMETERS: Readonly<ControlParameters> = Object.freeze({
  jointStepDeg: 2,
  railStepMm: 5,
  continuousSpeedDegS: 12,
  railSpeedMmS: 20,
  cartesianStepMm: 5,
  rotationStepDeg: 3,
  durationS: 1,
  speedScale: 0.5,
});
