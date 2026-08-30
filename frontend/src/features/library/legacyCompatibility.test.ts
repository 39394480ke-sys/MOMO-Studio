import { describe, expect, it } from 'vitest';

import type { MotionEntity, MotionSummary, PoseSnapshot, PoseSummary } from '../../api/types';
import {
  motionLegacyCompatibility,
  poseLegacyCompatibility,
  type LibraryCompatibilityContract,
} from './legacyCompatibility';

const contract: LibraryCompatibilityContract = {
  variant: 'V2',
  enabledJointIds: ['j10', 'j11', 'j12', 'j13', 'j14', 'j15'],
  jointUnits: {
    j10: 'mm',
    j11: 'deg',
    j12: 'deg',
    j13: 'deg',
    j14: 'deg',
    j15: 'deg',
  },
  profileFingerprint: 'a'.repeat(64),
  kinematicsFingerprint: 'b'.repeat(64),
};

function snapshot(): PoseSnapshot {
  return {
    robot_variant: 'V2',
    joint_state: {
      positions: { j10: 0, j11: 0, j12: 0, j13: 0, j14: 0, j15: 0 },
      units: { ...contract.jointUnits },
    },
    tcp_pose: {
      frame: 'base',
      position_mm: { x: 0, y: 0, z: 0 },
      orientation_quaternion_xyzw: { x: 0, y: 0, z: 0, w: 1 },
    },
    profile_fingerprint: contract.profileFingerprint,
    kinematics_fingerprint: contract.kinematicsFingerprint,
    state_sequence: null,
    hardware_snapshot: null,
    calibration_fingerprint: null,
    captured_at: '2026-08-30T00:00:00Z',
  };
}

function poseSummary(): PoseSummary {
  const value = snapshot();
  return {
    id: '11111111-1111-4111-8111-111111111111',
    name: 'Legacy pose',
    description: '',
    tags: ['legacy-import'],
    robot_variant: value.robot_variant,
    joint_state: value.joint_state,
    tcp_pose: value.tcp_pose,
    profile_fingerprint: value.profile_fingerprint,
    kinematics_fingerprint: value.kinematics_fingerprint,
    state_sequence: value.state_sequence,
    created_at: value.captured_at,
    updated_at: value.captured_at,
    revision: 1,
  };
}

function motion(entitySnapshot: PoseSnapshot): [MotionSummary, MotionEntity] {
  const summary: MotionSummary = {
    id: '22222222-2222-4222-8222-222222222222',
    name: 'Legacy motion',
    description: '',
    robot_variant: 'V2',
    keyframe_count: 2,
    total_duration_s: 1,
    motion_types: ['JOINT'],
    tags: ['legacy-import'],
    created_at: '2026-08-30T00:00:00Z',
    updated_at: '2026-08-30T00:00:00Z',
    revision: 1,
  };
  const entity: MotionEntity = {
    ...summary,
    schema_version: '2.0.0',
    keyframes: [0, 1].map((index) => ({
      id: `${index + 3}3333333-3333-4333-8333-333333333333`,
      label: `Legacy ${index + 1}`,
      pose_snapshot: entitySnapshot,
      source_pose_id: null,
      hold_s: 0,
      incoming_transition: index === 0 ? null : {
        duration_s: 1,
        motion_mode: 'JOINT',
        easing: 'SMOOTHSTEP',
      },
    })),
    playback_defaults: { loop: false, speed_multiplier: 1 },
    source_metadata: {
      importer: 'momo.tools.import_legacy_actions',
      source_file_name: 'legacy.json',
      source_sha256: 'c'.repeat(64),
      legacy_id: null,
      legacy_source: null,
      warnings: [],
    },
  };
  return [summary, entity];
}

describe('Library Legacy compatibility status', () => {
  it('reports a Legacy Pose as matching only when the visible contract matches', () => {
    const compatible = poseLegacyCompatibility(poseSummary(), contract);
    expect(compatible?.state).toBe('compatible');
    expect(compatible?.detail).toContain('后端安全预检');

    const incompatiblePose = poseSummary();
    incompatiblePose.joint_state.units.j10 = 'deg';
    incompatiblePose.profile_fingerprint = 'd'.repeat(64);
    const incompatible = poseLegacyCompatibility(incompatiblePose, contract);
    expect(incompatible?.state).toBe('incompatible');
    expect(incompatible?.summary).toContain('j10 单位应为 mm，实际为 deg');
    expect(incompatible?.summary).toContain('Profile 指纹不匹配');
    expect(incompatible?.detail).toContain('不会自动换算');
  });

  it('keeps Motion list status unverified until snapshots load, then names bad frames', () => {
    const [summary, entity] = motion(snapshot());
    expect(motionLegacyCompatibility(summary, null, contract)?.state).toBe('unverified');

    const badSnapshot = snapshot();
    badSnapshot.robot_variant = 'V1';
    badSnapshot.joint_state = {
      positions: { j11: 0, j12: 0, j13: 0, j14: 0, j15: 0, j16: 0 },
      units: { j11: 'deg', j12: 'deg', j13: 'deg', j14: 'deg', j15: 'deg', j16: 'deg' },
    };
    entity.keyframes[1].pose_snapshot = badSnapshot;
    const incompatible = motionLegacyCompatibility(summary, entity, contract);
    expect(incompatible?.state).toBe('incompatible');
    expect(incompatible?.summary).toContain('关键帧 2（Legacy 2）');
    expect(incompatible?.summary).toContain('缺少关节 j10');
    expect(incompatible?.summary).toContain('多余关节 j16');
  });
});
