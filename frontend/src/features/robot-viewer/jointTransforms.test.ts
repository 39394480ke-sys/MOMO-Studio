import { describe, expect, it } from 'vitest';

import {
  buildUrdfJointValues,
  clampJointPosition,
  convertJointValueToUrdfUnit,
  interpolateJointPositions,
  type RobotViewerJointDefinition,
} from './jointTransforms';

const definitions: readonly RobotViewerJointDefinition[] = [
  { joint_id: 'j10', joint_type: 'PRISMATIC', domain_unit: 'mm', minimum: 0, maximum: 500 },
  { joint_id: 'j11', joint_type: 'REVOLUTE', domain_unit: 'deg', minimum: -180, maximum: 180 },
  { joint_id: 'j12', joint_type: 'REVOLUTE', domain_unit: 'deg', minimum: -90, maximum: 90 },
];

describe('robot viewer joint boundaries', () => {
  it('converts only at the named mm/deg -> m/rad boundary', () => {
    expect(convertJointValueToUrdfUnit(125, 'mm')).toBeCloseTo(0.125);
    expect(convertJointValueToUrdfUnit(90, 'deg')).toBeCloseTo(Math.PI / 2);
  });

  it('uses enabled joints, definition units and profile limits', () => {
    const result = buildUrdfJointValues({
      jointDefinitions: definitions,
      enabledJointIds: ['j10', 'j11', 'j12'],
      jointPositions: { j10: 900, j11: 270, j12: 45, j99: 12 },
      jointUnits: { j10: 'mm', j11: 'deg', j12: 'mm', j99: 'deg' },
    });

    expect(result).toEqual({
      j10: 0.5,
      j11: Math.PI,
    });
    expect(result).not.toHaveProperty('j12');
    expect(result).not.toHaveProperty('j99');
  });

  it('rejects non-finite values and invalid limit definitions', () => {
    expect(clampJointPosition(Number.NaN, definitions[0])).toBeNull();
    expect(clampJointPosition(2, {
      ...definitions[0],
      minimum: 10,
      maximum: 0,
    })).toBeNull();
  });

  it('interpolates enabled domain values and clamps progress and limits', () => {
    expect(interpolateJointPositions({
      from: { j10: 0, j11: -90, j12: 0, j99: 0 },
      to: { j10: 1000, j11: 90, j12: 45, j99: 100 },
      progress: 0.75,
      jointDefinitions: definitions,
      enabledJointIds: ['j10', 'j11'],
    })).toEqual({ j10: 500, j11: 45 });

    expect(interpolateJointPositions({
      from: { j11: -90 },
      to: { j11: 90 },
      progress: 2,
      jointDefinitions: definitions,
      enabledJointIds: ['j11'],
    })).toEqual({ j11: 90 });
  });
});
