import type { MotionKeyframe } from '../../api/types';

export interface TimelineMarker {
  frame: MotionKeyframe;
  index: number;
  time: number;
}

export interface TimelineSegment {
  duration: number;
  from: MotionKeyframe;
  to: MotionKeyframe;
  isDefault: boolean;
  mode: string;
}

export function timelineData(frames: MotionKeyframe[]): {
  duration: number;
  markers: TimelineMarker[];
  segments: TimelineSegment[];
} {
  let cursor = 0;
  const markers: TimelineMarker[] = [];
  const segments: TimelineSegment[] = [];
  frames.forEach((frame, index) => {
    if (index > 0) {
      const previous = frames[index - 1];
      const transition = frame.incoming_transition;
      if (previous && transition) {
        segments.push({
          duration: transition.duration_s,
          from: previous,
          to: frame,
          isDefault: false,
          mode: transition.motion_mode,
        });
        cursor += transition.duration_s;
      }
    }
    markers.push({ frame, index, time: cursor });
    cursor += frame.hold_s;
  });
  return { duration: cursor, markers, segments };
}

export function clampTransitionDuration(durationS: number): number {
  return Math.min(600, Math.max(0.05, Math.round(durationS * 100) / 100));
}

export function timeFromTrackPointer(
  clientX: number,
  trackLeft: number,
  trackWidth: number,
  durationS: number,
): number {
  const usableWidth = Math.max(1, trackWidth - 168);
  const ratio = Math.min(1, Math.max(0, (clientX - trackLeft - 84) / usableWidth));
  return Math.round(ratio * Math.max(0, durationS) * 100) / 100;
}
