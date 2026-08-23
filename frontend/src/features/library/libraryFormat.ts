import type { MotionEntity } from '../../api/types';

export function parseTags(value: string): string[] {
  return Array.from(
    new Set(
      value
        .split(',')
        .map((tag) => tag.trim())
        .filter(Boolean),
    ),
  );
}

export function validateEntityTags(tags: string[]): string | null {
  if (tags.length > 32) return 'Use no more than 32 tags.';
  if (tags.some((tag) => tag.length > 64)) return 'Each tag must be 64 characters or fewer.';
  return null;
}

export function formatEntityDate(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return 'Invalid timestamp';
  return new Intl.DateTimeFormat(undefined, {
    year: 'numeric',
    month: 'short',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  }).format(date);
}

export function totalMotionDuration(motion: MotionEntity): number {
  return motion.keyframes.reduce(
    (total, keyframe) =>
      total + keyframe.hold_s + (keyframe.incoming_transition?.duration_s ?? 0),
    0,
  );
}

export function motionTypeSummary(motion: MotionEntity): string {
  const modes = Array.from(
    new Set(
      motion.keyframes.flatMap((keyframe) =>
        keyframe.incoming_transition ? [keyframe.incoming_transition.motion_mode] : [],
      ),
    ),
  );
  return modes.length > 0 ? modes.join(' · ') : 'No transitions';
}

export function libraryIdempotencyKey(poseId: string): string {
  const randomPart = globalThis.crypto?.randomUUID?.() ?? `${Date.now()}-${Math.random()}`;
  return `library-goto-${poseId}-${randomPart}`;
}
