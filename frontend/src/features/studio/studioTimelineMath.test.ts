import { describe, expect, it } from 'vitest';

import type { MotionKeyframe } from '../../api/types';
import {
  clampTransitionDuration,
  framesWithTimelineTimeEdit,
  MIN_TIMELINE_PIXELS_PER_SECOND,
  timelineEdgeScrollSpeed,
  timelineTimeEdit,
  timelineData,
  timelineTrailingDuration,
  timelineViewportLayout,
  timeFromTrackPointer,
} from './studioTimelineMath';

function keyframe(
  id: string,
  holdS: number,
  durationS: number | null,
): MotionKeyframe {
  return {
    id,
    label: id,
    hold_s: holdS,
    source_pose_id: null,
    incoming_transition: durationS === null ? null : {
      duration_s: durationS,
      motion_mode: 'JOINT',
      easing: 'SMOOTHSTEP',
    },
    pose_snapshot: {} as MotionKeyframe['pose_snapshot'],
  };
}

describe('studio timeline math', () => {
  it('places markers after the prior hold and incoming transition', () => {
    const data = timelineData([
      keyframe('K1', 0.2, null),
      keyframe('K2', 2, 1.5),
      keyframe('K3', 0.3, 0.5),
    ]);

    expect(data.markers.map((marker) => marker.time)).toEqual([0, 1.7, 4.2]);
    expect(data.duration).toBeCloseTo(4.5);
  });

  it('bounds and rounds drag-authored transition durations', () => {
    expect(clampTransitionDuration(-1)).toBe(0.05);
    expect(clampTransitionDuration(1.237)).toBe(1.24);
    expect(clampTransitionDuration(900)).toBe(600);
  });

  it('maps pointer position to a bounded playhead time', () => {
    expect(timeFromTrackPointer(56, 0, 100, 10)).toBe(0);
    expect(timeFromTrackPointer(556, 0, 100, 10)).toBe(5);
    expect(timeFromTrackPointer(1400, 0, 100, 10)).toBe(10);
  });

  it('fills short-motion viewports and preserves readable density for long motions', () => {
    const short = timelineViewportLayout(2, 1200);
    expect(short).toMatchObject({
      motionDurationS: 2,
      trackWidthPx: 1200,
      trailingDurationS: 0.5,
      viewDurationS: 2.5,
    });
    expect(short.pixelsPerSecond).toBeGreaterThan(MIN_TIMELINE_PIXELS_PER_SECOND);

    const compact = timelineViewportLayout(2, 520);
    expect(compact.trackWidthPx).toBe(520);

    const long = timelineViewportLayout(12, 900);
    expect(long.trackWidthPx).toBeGreaterThan(900);
    expect(long.pixelsPerSecond).toBe(MIN_TIMELINE_PIXELS_PER_SECOND);
    expect(long.trailingDurationS).toBeCloseTo(1.8);
  });

  it('bounds trailing time and keeps a locked drag scale while the track grows', () => {
    expect(timelineTrailingDuration(0)).toBe(0.5);
    expect(timelineTrailingDuration(10)).toBe(1.5);
    expect(timelineTrailingDuration(100)).toBe(2);

    const layout = timelineViewportLayout(4, 760, 200);
    expect(layout.pixelsPerSecond).toBe(200);
    expect(layout.viewDurationS).toBe(4.6);
    expect(layout.trackWidthPx).toBe(1032);
  });

  it('accelerates only inside the right-edge extension zone', () => {
    expect(timelineEdgeScrollSpeed(700, 760)).toBe(0);
    expect(timelineEdgeScrollSpeed(730, 760)).toBeGreaterThan(0);
    expect(timelineEdgeScrollSpeed(780, 760)).toBeGreaterThan(
      timelineEdgeScrollSpeed(730, 760),
    );
  });

  it('moves an interior keyframe without crossing and recalculates both adjacent transitions', () => {
    const frames = [
      keyframe('K1', 0, null),
      keyframe('K2', 0, 2.5),
      keyframe('K3', 0, 2.1),
    ];
    const edit = timelineTimeEdit(frames, 'K2', 3);

    expect(edit).toMatchObject({
      timeS: 3,
      incomingDurationS: 3,
      nextFrameId: 'K3',
      nextIncomingDurationS: 1.6,
    });
    expect(timelineData(framesWithTimelineTimeEdit(frames, edit)).markers.map(({ time }) => time))
      .toEqual([0, 3, 4.6]);
  });

  it('enforces minimum spacing and keeps the first keyframe fixed', () => {
    const frames = [keyframe('K1', 0, null), keyframe('K2', 0, 1), keyframe('K3', 0, 1)];
    expect(timelineTimeEdit(frames, 'K1', 0.5)).toBeNull();
    expect(timelineTimeEdit(frames, 'K2', 99)).toMatchObject({
      timeS: 1.95,
      incomingDurationS: 1.95,
      nextIncomingDurationS: 0.05,
    });
    expect(timelineTimeEdit(frames, 'K3', 4)).toMatchObject({
      timeS: 4,
      incomingDurationS: 3,
      nextFrameId: null,
    });
    expect(timelineTimeEdit(frames, 'K3', 999)).toMatchObject({
      timeS: 601,
      incomingDurationS: 600,
      nextFrameId: null,
    });
  });
});
