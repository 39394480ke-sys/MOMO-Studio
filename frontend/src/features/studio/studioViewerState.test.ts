import { describe, expect, it } from 'vitest';

import type { TrajectoryPreview } from '../../api/types';
import { sampleTrajectoryJointState } from './studioViewerState';

const preview: TrajectoryPreview = {
  digest: 'preview-digest',
  motion_id: '00000000-0000-4000-8000-000000000001',
  duration_s: 2,
  sample_rate_hz: 1,
  sample_count: 3,
  segments: [],
  joint_series: {
    j10: [
      { time_s: 0, value: 0, unit: 'mm' },
      { time_s: 2, value: 100, unit: 'mm' },
    ],
    j11: [
      { time_s: 0, value: -20, unit: 'deg' },
      { time_s: 2, value: 20, unit: 'deg' },
    ],
    disabled: [{ time_s: 0, value: 999, unit: 'deg' }],
  },
  tcp_path: [],
  keyframe_markers: [],
};

describe('sampleTrajectoryJointState', () => {
  it('interpolates only enabled joints without changing domain units', () => {
    expect(sampleTrajectoryJointState(preview, 1, ['j10', 'j11'])).toEqual({
      positions: { j10: 50, j11: 0 },
      units: { j10: 'mm', j11: 'deg' },
    });
  });

  it('clamps the visualization playhead to the compiled preview bounds', () => {
    expect(sampleTrajectoryJointState(preview, 99, ['j10'])?.positions).toEqual({ j10: 100 });
    expect(sampleTrajectoryJointState(preview, -4, ['j10'])?.positions).toEqual({ j10: 0 });
  });

  it('fails closed when no preview data is available', () => {
    expect(sampleTrajectoryJointState(null, 1, ['j10'])).toBeNull();
    expect(sampleTrajectoryJointState(preview, 1, ['missing'])).toBeNull();
  });
});
