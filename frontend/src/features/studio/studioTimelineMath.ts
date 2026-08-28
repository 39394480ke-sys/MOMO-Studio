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
export const TIMELINE_TRACK_PADDING_PX = 56;
export const MIN_TIMELINE_TRACK_WIDTH_PX = 760;
export const MIN_TIMELINE_PIXELS_PER_SECOND = 112;
export const TIMELINE_EDGE_SCROLL_ZONE_PX = 40;

export interface TimelineViewportLayout {
  motionDurationS: number;
  pixelsPerSecond: number;
  trackWidthPx: number;
  trailingDurationS: number;
  viewDurationS: number;
}

export function timelineTrailingDuration(motionDurationS: number): number {
  const boundedDuration = Math.max(0, Number.isFinite(motionDurationS) ? motionDurationS : 0);
  return Math.min(2, Math.max(0.5, boundedDuration * 0.15));
}

/**
 * Short motions expand to the available viewport. Long motions retain a
 * readable time density and overflow only inside the timeline scroller.
 * A locked scale keeps last-frame dragging visually stable while the track
 * grows beneath the pointer.
 */
export function timelineViewportLayout(
  motionDurationS: number,
  viewportWidthPx: number,
  lockedPixelsPerSecond?: number,
): TimelineViewportLayout {
  const motionDuration = Math.max(0.05, Number.isFinite(motionDurationS) ? motionDurationS : 0.05);
  const viewportWidth = Math.max(
    1,
    Number.isFinite(viewportWidthPx) ? viewportWidthPx : 0,
  );
  const trailingDuration = timelineTrailingDuration(motionDuration);
  const minimumViewDuration = Math.max(1, motionDuration + trailingDuration);
  const usableViewportWidth = Math.max(1, viewportWidth - TIMELINE_TRACK_PADDING_PX * 2);

  if (lockedPixelsPerSecond !== undefined && lockedPixelsPerSecond > 0) {
    const pixelsPerSecond = lockedPixelsPerSecond;
    const viewDuration = Math.max(minimumViewDuration, usableViewportWidth / pixelsPerSecond);
    const trackWidth = Math.max(
      viewportWidth,
      TIMELINE_TRACK_PADDING_PX * 2 + viewDuration * pixelsPerSecond,
    );
    return {
      motionDurationS: motionDuration,
      pixelsPerSecond,
      trackWidthPx: trackWidth,
      trailingDurationS: viewDuration - motionDuration,
      viewDurationS: viewDuration,
    };
  }

  const readableTrackWidth = TIMELINE_TRACK_PADDING_PX * 2
    + minimumViewDuration * MIN_TIMELINE_PIXELS_PER_SECOND;
  const trackWidth = Math.max(viewportWidth, readableTrackWidth);
  const pixelsPerSecond = Math.max(
    MIN_TIMELINE_PIXELS_PER_SECOND,
    (trackWidth - TIMELINE_TRACK_PADDING_PX * 2) / minimumViewDuration,
  );
  const viewDuration = (trackWidth - TIMELINE_TRACK_PADDING_PX * 2) / pixelsPerSecond;
  return {
    motionDurationS: motionDuration,
    pixelsPerSecond,
    trackWidthPx: trackWidth,
    trailingDurationS: viewDuration - motionDuration,
    viewDurationS: viewDuration,
  };
}

export function timelineEdgeScrollSpeed(
  clientX: number,
  viewportRightPx: number,
  edgeZonePx = TIMELINE_EDGE_SCROLL_ZONE_PX,
): number {
  if (!Number.isFinite(clientX) || !Number.isFinite(viewportRightPx) || edgeZonePx <= 0) return 0;
  const penetration = clientX - (viewportRightPx - edgeZonePx);
  if (penetration <= 0) return 0;
  const intensity = Math.min(1.5, penetration / edgeZonePx);
  return 2 + 14 * intensity;
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
  pixelsPerSecond: number,
  maximumTimeS: number,
): number {
  const rawTime = (clientX - trackLeft - TIMELINE_TRACK_PADDING_PX)
    / Math.max(1, pixelsPerSecond);
  const bounded = Math.min(Math.max(0, maximumTimeS), Math.max(0, rawTime));
  return Math.round(bounded * 100) / 100;
}
