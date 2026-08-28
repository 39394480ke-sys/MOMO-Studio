export type RobotViewerDomainUnit = 'mm' | 'deg';

/**
 * The viewer deliberately accepts a small structural subset of a robot profile.
 * Product/API types can satisfy this shape without coupling the feature to an API module.
 */
export interface RobotViewerJointDefinition {
  readonly joint_id: string;
  readonly joint_type?: 'REVOLUTE' | 'PRISMATIC';
  readonly domain_unit: RobotViewerDomainUnit;
  readonly minimum: number;
  readonly maximum: number;
  readonly home?: number;
}

export type RobotViewerJointPositions = Readonly<Record<string, number>>;
export type RobotViewerJointUnits = Readonly<Record<string, RobotViewerDomainUnit | undefined>>;

function finite(value: number): boolean {
  return Number.isFinite(value);
}

/** Clamp a UI/domain value to the explicit profile limits. Invalid definitions are rejected. */
export function clampJointPosition(
  value: number,
  definition: RobotViewerJointDefinition,
): number | null {
  if (
    !finite(value) ||
    !finite(definition.minimum) ||
    !finite(definition.maximum) ||
    definition.minimum > definition.maximum
  ) {
    return null;
  }

  return Math.min(definition.maximum, Math.max(definition.minimum, value));
}

/** Named UI/domain -> URDF boundary: millimetres become metres; degrees become radians. */
export function convertJointValueToUrdfUnit(
  value: number,
  domainUnit: RobotViewerDomainUnit,
): number {
  return domainUnit === 'mm' ? value / 1000 : value * (Math.PI / 180);
}

export interface BuildUrdfJointValuesInput {
  readonly jointDefinitions: readonly RobotViewerJointDefinition[];
  readonly enabledJointIds: readonly string[];
  readonly jointPositions: RobotViewerJointPositions;
  readonly jointUnits: RobotViewerJointUnits;
}

/**
 * Select only enabled joints, validate any reported unit against the definition,
 * clamp in domain units, then convert at the URDF boundary.
 */
export function buildUrdfJointValues({
  jointDefinitions,
  enabledJointIds,
  jointPositions,
  jointUnits,
}: BuildUrdfJointValuesInput): Readonly<Record<string, number>> {
  const definitions = new Map(
    jointDefinitions.map((definition) => [definition.joint_id, definition]),
  );
  const result: Record<string, number> = {};

  for (const jointId of new Set(enabledJointIds)) {
    const definition = definitions.get(jointId);
    const position = jointPositions[jointId];
    const reportedUnit = jointUnits[jointId];
    if (
      definition === undefined ||
      position === undefined ||
      (reportedUnit !== undefined && reportedUnit !== definition.domain_unit)
    ) {
      continue;
    }

    const clamped = clampJointPosition(position, definition);
    if (clamped === null) continue;
    result[jointId] = convertJointValueToUrdfUnit(clamped, definition.domain_unit);
  }

  return Object.freeze(result);
}

export interface InterpolateJointPositionsInput {
  readonly from: RobotViewerJointPositions;
  readonly to: RobotViewerJointPositions;
  readonly progress: number;
  readonly jointDefinitions: readonly RobotViewerJointDefinition[];
  readonly enabledJointIds: readonly string[];
}

/**
 * Linearly interpolate enabled domain values. The result remains in profile units
 * and is clamped before a caller passes it through `buildUrdfJointValues`.
 */
export function interpolateJointPositions({
  from,
  to,
  progress,
  jointDefinitions,
  enabledJointIds,
}: InterpolateJointPositionsInput): Readonly<Record<string, number>> {
  const definitions = new Map(
    jointDefinitions.map((definition) => [definition.joint_id, definition]),
  );
  const boundedProgress = Number.isFinite(progress)
    ? Math.min(1, Math.max(0, progress))
    : 0;
  const result: Record<string, number> = {};

  for (const jointId of new Set(enabledJointIds)) {
    const definition = definitions.get(jointId);
    const start = from[jointId];
    const end = to[jointId];
    if (definition === undefined || start === undefined || end === undefined) continue;
    if (!finite(start) || !finite(end)) continue;

    const value = start + (end - start) * boundedProgress;
    const clamped = clampJointPosition(value, definition);
    if (clamped !== null) result[jointId] = clamped;
  }

  return Object.freeze(result);
}
