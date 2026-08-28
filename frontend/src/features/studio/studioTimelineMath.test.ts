import { describe, expect, it } from 'vitest';

import type { MotionKeyframe } from '../../api/types';
import {
  clampTransitionDuration,
  timelineData,
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
    expect(timeFromTrackPointer(84, 0, 1168, 10)).toBe(0);
    expect(timeFromTrackPointer(584, 0, 1168, 10)).toBe(5);
    expect(timeFromTrackPointer(1400, 0, 1168, 10)).toBe(10);
  });
});
