import { describe, expect, it } from 'vitest';

import { ApiError } from '../../api/client';
import { studioCompatibilityIssue } from './studioCompatibility';

function diagnosticError(details: Record<string, unknown>): ApiError {
  return new ApiError({
    status: 422,
    code: 'POSE_INCOMPATIBLE',
    message: 'Draft snapshot is incompatible with its declared robot contract',
    details,
  });
}

describe('Studio compatibility diagnostics', () => {
  it('parses bounded per-keyframe evidence without inventing a migration', () => {
    const issue = studioCompatibilityIssue(diagnosticError({
      error_code: 'STUDIO_DRAFT_CONTRACT_INCOMPATIBLE',
      draft_variant: 'V2',
      active_variant: 'V1',
      checks: ['missing_joint_ids', 'joint_units'],
      keyframes: [{
        keyframe_id: '11111111-1111-4111-8111-111111111111',
        keyframe_index: 2,
        keyframe_name: 'Legacy rail frame',
        source_pose_id: '22222222-2222-4222-8222-222222222222',
        checks: ['missing_joint_ids', 'joint_units'],
        expected_joint_ids: ['j10', 'j11'],
        actual_joint_ids: ['j11'],
        missing_joint_ids: ['j10'],
        extra_joint_ids: [],
        expected_units: { j10: 'mm', j11: 'deg' },
        actual_units: { j11: 'deg' },
        expected_profile_fingerprint: 'a'.repeat(64),
        actual_profile_fingerprint: 'b'.repeat(64),
        expected_kinematics_fingerprint: 'c'.repeat(64),
        actual_kinematics_fingerprint: 'd'.repeat(64),
        tcp_mismatch: false,
        state_sequence_issue: true,
        provenance_issue: true,
      }],
    }));

    expect(issue).toMatchObject({
      draftVariant: 'V2',
      activeVariant: 'V1',
      keyframes: [{
        keyframeIndex: 2,
        keyframeName: 'Legacy rail frame',
        missingJointIds: ['j10'],
        expectedUnits: { j10: 'mm', j11: 'deg' },
        stateSequenceIssue: true,
        provenanceIssue: true,
      }],
    });
  });

  it('rejects incomplete diagnostics instead of offering unsafe recovery actions', () => {
    expect(studioCompatibilityIssue(diagnosticError({
      error_code: 'STUDIO_DRAFT_CONTRACT_INCOMPATIBLE',
      draft_variant: 'V2',
      active_variant: 'V2',
      checks: ['joint_state'],
      keyframes: [{ keyframe_id: 'missing-required-evidence' }],
    }))).toBeNull();
  });
});
