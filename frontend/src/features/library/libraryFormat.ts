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
  if (tags.length > 32) return '标签数量不能超过 32 个。';
  if (tags.some((tag) => tag.length > 64)) return '每个标签不能超过 64 个字符。';
  return null;
}

export function formatEntityDate(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return '无效时间';
  return new Intl.DateTimeFormat('zh-CN', {
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
  return modes.length > 0 ? modes.join(' · ') : '无过渡';
}

export function libraryIdempotencyKey(poseId: string): string {
  const randomPart = globalThis.crypto?.randomUUID?.() ?? `${Date.now()}-${Math.random()}`;
  return `library-goto-${poseId}-${randomPart}`;
}
