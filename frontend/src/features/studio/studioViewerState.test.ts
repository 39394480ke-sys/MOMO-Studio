import { describe, expect, it } from 'vitest';

import type { MotionKeyframe, TrajectoryPreview } from '../../api/types';
import { sampleDraftJointState, sampleTrajectoryJointState } from './studioViewerState';

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

const draftFrames: MotionKeyframe[] = [
  {
    id: 'K1',
    label: 'K1',
    hold_s: 0,
    incoming_transition: null,
    source_pose_id: null,
    pose_snapshot: {
      robot_variant: 'V2',
      joint_state: { positions: { j10: 0, j11: -20 }, units: { j10: 'mm', j11: 'deg' } },
      tcp_pose: {
        frame: 'base',
        position_mm: { x: 0, y: 0, z: 0 },
        orientation_quaternion_xyzw: { x: 0, y: 0, z: 0, w: 1 },
      },
      profile_fingerprint: 'a'.repeat(64),
      kinematics_fingerprint: 'b'.repeat(64),
      state_sequence: 1,
      hardware_snapshot: null,
      calibration_fingerprint: null,
      captured_at: '2026-08-24T00:00:00Z',
    },
  },
  {
    id: 'K2',
    label: 'K2',
    hold_s: 0,
    incoming_transition: { duration_s: 2, motion_mode: 'JOINT', easing: 'LINEAR' },
    source_pose_id: null,
    pose_snapshot: {
      robot_variant: 'V2',
      joint_state: { positions: { j10: 100, j11: 20 }, units: { j10: 'mm', j11: 'deg' } },
      tcp_pose: {
        frame: 'base',
        position_mm: { x: 100, y: 0, z: 0 },
        orientation_quaternion_xyzw: { x: 0, y: 0, z: 0, w: 1 },
      },
      profile_fingerprint: 'a'.repeat(64),
      kinematics_fingerprint: 'b'.repeat(64),
      state_sequence: 2,
      hardware_snapshot: null,
      calibration_fingerprint: null,
      captured_at: '2026-08-24T00:00:01Z',
    },
  },
];

describe('sampleDraftJointState', () => {
  it('lets timeline scrubbing drive an immediate simulation pose before compilation', () => {
    expect(sampleDraftJointState(draftFrames, 1, ['j10', 'j11'])).toEqual({
      positions: { j10: 50, j11: 0 },
      units: { j10: 'mm', j11: 'deg' },
    });
  });

  it('clamps scrub time and ignores joints outside the active profile', () => {
    expect(sampleDraftJointState(draftFrames, 99, ['j10', 'disabled'])).toEqual({
      positions: { j10: 100 },
      units: { j10: 'mm' },
    });
    expect(sampleDraftJointState(draftFrames, -1, ['j10'])?.positions).toEqual({ j10: 0 });
  });
});
