import { describe, expect, it } from 'vitest';

import type { MotionEntity, PoseSnapshot } from '../../api/types';
import {
  formatSimulationTime,
  motionSimulationDuration,
  sampleMotionAtTime,
} from './resourceSimulation';

function snapshot(value: number): PoseSnapshot {
  return {
    robot_variant: 'V2',
    joint_state: {
      positions: { j10: value, j11: value },
      units: { j10: 'mm', j11: 'deg' },
    },
    tcp_pose: {
      frame: 'base',
      position_mm: { x: value, y: 0, z: value * 2 },
      orientation_quaternion_xyzw: { x: 0, y: 0, z: 0, w: 1 },
    },
    profile_fingerprint: 'a'.repeat(64),
    kinematics_fingerprint: 'b'.repeat(64),
    state_sequence: null,
    hardware_snapshot: null,
    calibration_fingerprint: null,
    captured_at: '2026-08-28T00:00:00Z',
  };
}

const motion: MotionEntity = {
  schema_version: '2.0.0',
  id: '33333333-3333-4333-8333-333333333333',
  name: 'Simulation fixture',
  description: '',
  robot_variant: 'V2',
  keyframes: [
    {
      id: '44444444-4444-4444-8444-444444444444',
      label: 'Start',
      pose_snapshot: snapshot(0),
      source_pose_id: null,
      hold_s: 0.5,
      incoming_transition: null,
    },
    {
      id: '55555555-5555-4555-8555-555555555555',
      label: 'End',
      pose_snapshot: snapshot(10),
      source_pose_id: null,
      hold_s: 0.5,
      incoming_transition: {
        duration_s: 2,
        motion_mode: 'JOINT',
        easing: 'LINEAR',
      },
    },
  ],
  playback_defaults: { loop: false, speed_multiplier: 1 },
  source_metadata: null,
  tags: [],
  created_at: '2026-08-28T00:00:00Z',
  updated_at: '2026-08-28T00:00:00Z',
  revision: 1,
};

describe('resource simulation timeline', () => {
  it('uses embedded keyframes to compute the complete simulation duration', () => {
    expect(motionSimulationDuration(motion)).toBe(3);
  });

  it('holds, interpolates, and lands on the immutable keyframe data', () => {
    expect(sampleMotionAtTime(motion, 0.25).jointState.positions.j10).toBe(0);
    expect(sampleMotionAtTime(motion, 1.5).jointState.positions.j10).toBe(5);
    expect(sampleMotionAtTime(motion, 3).jointState.positions.j10).toBe(10);
    expect(sampleMotionAtTime(motion, 1.5).tcpPose.position_mm.z).toBe(10);
  });

  it('clamps scrubbing and formats stable transport timestamps', () => {
    expect(sampleMotionAtTime(motion, -100).jointState.positions.j10).toBe(0);
    expect(sampleMotionAtTime(motion, 100).jointState.positions.j10).toBe(10);
    expect(formatSimulationTime(61.25)).toBe('01:01.3');
  });
});
