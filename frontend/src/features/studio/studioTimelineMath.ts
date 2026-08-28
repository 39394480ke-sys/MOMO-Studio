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

export interface TimelineTimeEdit {
  frameId: string;
  incomingDurationS: number;
  nextFrameId: string | null;
  nextIncomingDurationS: number | null;
  timeS: number;
}

export const MIN_TIMELINE_SPACING_S = 0.05;

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

/**
 * Convert a keyframe's desired absolute time into the two adjacent transition
 * durations stored by the domain model. The edit is intentionally atomic so a
 * drag creates one undo step and never lets keyframes cross.
 */
export function timelineTimeEdit(
  frames: MotionKeyframe[],
  frameId: string,
  desiredTimeS: number,
  minimumSpacingS = MIN_TIMELINE_SPACING_S,
): TimelineTimeEdit | null {
  const data = timelineData(frames);
  const index = data.markers.findIndex((marker) => marker.frame.id === frameId);
  if (index <= 0 || !Number.isFinite(desiredTimeS)) return null;

  const previous = data.markers[index - 1];
  const current = data.markers[index];
  const next = data.markers[index + 1] ?? null;
  if (!previous || !current) return null;

  const spacing = Math.max(MIN_TIMELINE_SPACING_S, minimumSpacingS);
  const minimumTime = previous.time + previous.frame.hold_s + spacing;
  const maximumTime = next
    ? next.time - current.frame.hold_s - spacing
    : previous.time + previous.frame.hold_s + 600;
  const boundedTime = Math.min(maximumTime, Math.max(minimumTime, desiredTimeS));
  const timeS = Math.round(boundedTime * 100) / 100;
  const incomingDurationS = clampTransitionDuration(
    timeS - previous.time - previous.frame.hold_s,
  );
  const nextIncomingDurationS = next
    ? clampTransitionDuration(next.time - timeS - current.frame.hold_s)
    : null;

  return {
    frameId,
    incomingDurationS,
    nextFrameId: next?.frame.id ?? null,
    nextIncomingDurationS,
    timeS,
  };
}

export function framesWithTimelineTimeEdit(
  frames: MotionKeyframe[],
  edit: TimelineTimeEdit | null,
): MotionKeyframe[] {
  if (!edit) return frames;
  return frames.map((frame) => {
    if (frame.id === edit.frameId && frame.incoming_transition) {
      return {
        ...frame,
        incoming_transition: {
          ...frame.incoming_transition,
          duration_s: edit.incomingDurationS,
        },
      };
    }
    if (
      edit.nextFrameId !== null
      && frame.id === edit.nextFrameId
      && frame.incoming_transition
      && edit.nextIncomingDurationS !== null
    ) {
      return {
        ...frame,
        incoming_transition: {
          ...frame.incoming_transition,
          duration_s: edit.nextIncomingDurationS,
        },
      };
    }
    return frame;
  });
}

export function formatTimelineTime(timeS: number): string {
  const bounded = Math.max(0, Number.isFinite(timeS) ? timeS : 0);
  const minutes = Math.floor(bounded / 60);
  const seconds = bounded - minutes * 60;
  return `${String(minutes).padStart(2, '0')}:${seconds.toFixed(1).padStart(4, '0')}`;
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
