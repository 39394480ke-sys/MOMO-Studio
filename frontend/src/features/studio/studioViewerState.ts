import type { DomainUnit, MotionKeyframe, TrajectoryPreview } from '../../api/types';
import { timelineData } from './studioTimelineMath';

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

function easedProgress(progress: number, easing: MotionKeyframe['incoming_transition'] extends infer Transition
  ? Transition extends { easing: infer Easing } ? Easing : never
  : never): number {
  const bounded = Math.min(1, Math.max(0, progress));
  if (easing === 'LINEAR') return bounded;
  if (easing === 'EASE_IN_OUT') {
    return bounded < 0.5
      ? 2 * bounded * bounded
      : 1 - Math.pow(-2 * bounded + 2, 2) / 2;
  }
  return bounded * bounded * (3 - 2 * bounded);
}

/**
 * Immediate simulation-only fallback used while the backend preview is absent
 * or invalidated by an edit. It samples immutable embedded snapshots and never
 * submits a robot command.
 */
export function sampleDraftJointState(
  frames: MotionKeyframe[],
  playheadS: number,
  enabledJointIds: readonly string[],
): SampledJointState | null {
  if (frames.length === 0 || !Number.isFinite(playheadS)) return null;
  const data = timelineData(frames);
  const boundedTime = Math.min(data.duration, Math.max(0, playheadS));
  let currentIndex = 0;
  for (let index = 1; index < data.markers.length; index += 1) {
    if (data.markers[index].time > boundedTime) break;
    currentIndex = index;
  }

  const current = data.markers[currentIndex];
  const next = data.markers[currentIndex + 1] ?? null;
  if (!current) return null;
  const startState = current.frame.pose_snapshot.joint_state;
  const transitionStart = current.time + current.frame.hold_s;
  const transitionDuration = next ? next.time - transitionStart : 0;
  const progress = !next || transitionDuration <= 0 || boundedTime <= transitionStart
    ? 0
    : easedProgress(
        (boundedTime - transitionStart) / transitionDuration,
        next.frame.incoming_transition?.easing ?? 'SMOOTHSTEP',
      );
  const endState = next?.frame.pose_snapshot.joint_state ?? startState;
  const positions: Record<string, number> = {};
  const units: Record<string, DomainUnit | undefined> = {};

  for (const jointId of new Set(enabledJointIds)) {
    const from = startState.positions[jointId];
    const to = endState.positions[jointId];
    const fromUnit = startState.units[jointId];
    const toUnit = endState.units[jointId];
    if (
      from === undefined
      || to === undefined
      || !Number.isFinite(from)
      || !Number.isFinite(to)
      || fromUnit !== toUnit
    ) continue;
    positions[jointId] = from + (to - from) * progress;
    units[jointId] = fromUnit;
  }

  return Object.keys(positions).length > 0 ? { positions, units } : null;
}
