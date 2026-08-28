import type { DomainUnit, TrajectoryPreview } from '../../api/types';

export interface SampledJointState {
  positions: Readonly<Record<string, number>>;
  units: Readonly<Record<string, DomainUnit | undefined>>;
}

/**
 * Sample the backend-compiled, non-executable trajectory preview in UI/domain
 * units. This is visualization-only and never submits a motion command.
 */
export function sampleTrajectoryJointState(
  preview: TrajectoryPreview | null,
  playheadS: number,
  enabledJointIds: readonly string[],
): SampledJointState | null {
  if (!preview || !Number.isFinite(playheadS)) return null;
  const boundedTime = Math.min(preview.duration_s, Math.max(0, playheadS));
  const positions: Record<string, number> = {};
  const units: Record<string, DomainUnit | undefined> = {};

  for (const jointId of new Set(enabledJointIds)) {
    const series = preview.joint_series[jointId];
    if (!series || series.length === 0) continue;
    const afterIndex = series.findIndex((point) => point.time_s >= boundedTime);
    const after = afterIndex < 0 ? series.at(-1) : series[afterIndex];
    const before = afterIndex <= 0 ? series[0] : series[afterIndex - 1];
    if (!before || !after || before.unit !== after.unit) continue;

    const span = after.time_s - before.time_s;
    const progress = span <= 0 ? 0 : (boundedTime - before.time_s) / span;
    const value = before.value + (after.value - before.value) * Math.min(1, Math.max(0, progress));
    if (!Number.isFinite(value)) continue;
    positions[jointId] = value;
    units[jointId] = before.unit;
  }

  return Object.keys(positions).length > 0 ? { positions, units } : null;
}
