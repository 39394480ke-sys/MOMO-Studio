import { afterEach, describe, expect, it, vi } from 'vitest';

import {
  acceptFieldJointMotion,
  addKinematicsVerificationMeasurement,
  commitKinematicsVerificationDraft,
  completeFieldPreMotionChecks,
  connectRealDevice,
  createOperatorSession,
  disconnectRealDevice,
  getFieldAcceptanceProgress,
  getFieldAcceptanceStatus,
  getKinematicsVerificationStatus,
  normalizeCalibrationWorkflowStatus,
  normalizeDeviceDiagnostics,
  normalizeDeviceReadiness,
  normalizeFieldAcceptanceProgress,
  normalizeFieldAcceptanceStatus,
  normalizeRawDirectionStatus,
  revokeOperatorSession,
  runDeviceDiagnostics,
  startCalibrationSession,
  startKinematicsVerificationDraft,
} from './client';

const profileFingerprint = 'a'.repeat(64);

function response(body: unknown): Response {
  return {
    ok: true,
    status: 200,
    json: vi.fn().mockResolvedValue(body),
  } as unknown as Response;
}

const confirmation = {
  robot_id: 'primary',
  robot_unit_id: 'MOMO-V1-UNIT-001',
  variant: 'V1',
  profile_fingerprint: profileFingerprint,
  calibration_fingerprint: null,
  kinematics_fingerprint: null,
  masked_serial_port: '/***USB0',
  masked_servo_ids: ['**1'],
  protocol: 'sts',
  session_purpose: 'COMMISSIONING_READ_ONLY',
  field_acceptance_evidence_id: null,
  physical_estop_required: true,
  workspace_clear_required: false,
  required_confirmation_text: 'I UNDERSTAND COMMISSIONING IS READ ONLY',
};

function capabilityMatrix() {
  const blocked = (reason: string) => ({
    ready: false,
    authorized: false,
    blocked_reasons: [reason],
    required_evidence: [],
  });
  return {
    commissioning_read_only: blocked('COMMISSIONING_OPERATOR_SESSION_REQUIRED'),
    commissioning_motion_test: blocked('COMMISSIONING_MOTION_SESSION_REQUIRED'),
    raw_direction_test: blocked('RAW_DIRECTION_SESSION_REQUIRED'),
    real_joint_motion: blocked('REAL_MOTION_SESSION_REQUIRED'),
    real_cartesian_motion: blocked('REAL_MOTION_SESSION_REQUIRED'),
    real_playback: blocked('REAL_MOTION_SESSION_REQUIRED'),
    real_vision_follow: blocked('REAL_MOTION_SESSION_REQUIRED'),
  };
}

function authorizationOptions(authorizable: {
  readOnly?: boolean;
  motionTest?: boolean;
  rawDirection?: boolean;
  realMotion?: boolean;
}) {
  return [
    {
      purpose: 'COMMISSIONING_READ_ONLY',
      authorizable: authorizable.readOnly ?? false,
      confirmation,
    },
    {
      purpose: 'COMMISSIONING_MOTION_TEST',
      authorizable: authorizable.motionTest ?? false,
      confirmation: { ...confirmation, session_purpose: 'COMMISSIONING_MOTION_TEST' },
    },
    {
      purpose: 'RAW_DIRECTION_TEST',
      authorizable: authorizable.rawDirection ?? false,
      confirmation: {
        ...confirmation,
        session_purpose: 'RAW_DIRECTION_TEST',
        workspace_clear_required: true,
        required_confirmation_text:
          'I CONFIRM CURRENT POSE MATCHES URDF ZERO AND RAW TEST CAN MOVE ONE JOINT',
      },
    },
    {
      purpose: 'REAL_MOTION',
      authorizable: authorizable.realMotion ?? false,
      confirmation: { ...confirmation, session_purpose: 'REAL_MOTION' },
    },
  ];
}

const positiveEvidenceId = '44444444-4444-4444-8444-444444444444';
const negativeEvidenceId = '55555555-5555-4555-8555-555555555555';

const fieldProgress = {
  state: 'JOINT_MOTION_TESTING',
  robot_unit_id: 'MOMO-V1-UNIT-001',
  checklist_version: 'field-v2',
  valid_capabilities: ['PRE_MOTION_CHECKS'],
  pre_motion_checks_complete: true,
  joint_motion_tests_complete: true,
  joint_motion_accepted: false,
  ready_to_accept_joint_motion: true,
  completed_joint_directions: 2,
  required_joint_directions: 2,
  joints: [{
    joint_id: 'j11',
    unit: 'deg',
    positive_evidence_id: positiveEvidenceId,
    negative_evidence_id: negativeEvidenceId,
    complete: true,
  }],
  selected_test_evidence_ids: [positiveEvidenceId, negativeEvidenceId],
  rejected_test_evidence_ids: [],
  stale_field_acceptance_evidence_ids: [],
  legacy_field_acceptance_evidence_ids: [],
  physical_stop_verification: 'PENDING',
  full_acceptance_complete: false,
};

const draftId = '66666666-6666-4666-8666-666666666666';
const operatorSessionId = '77777777-7777-4777-8777-777777777777';
const thresholds = {
  max_position_error_mm: 5,
  max_orientation_error_deg: 5,
};
const identityTcp = {
  frame: 'base',
  position_mm: { x: 10, y: 20, z: 30 },
  orientation_quaternion_xyzw: { x: 0, y: 0, z: 0, w: 1 },
};

function kinematicsPoint(index: number) {
  return {
    point_id: `${String(index).padStart(8, '0')}-8888-4888-8888-888888888888`,
    label: `gauge-${index}`,
    joint_state: { positions: { j11: index }, units: { j11: 'deg' } },
    joint_state_sequence: index,
    joint_state_captured_at: `2026-08-25T01:0${index}:00Z`,
    snapshot_session_id: operatorSessionId,
    predicted_tcp: identityTcp,
    measured_tcp: {
      ...identityTcp,
      position_mm: { ...identityTcp.position_mm, x: 10 + index },
    },
    position_error_mm: index,
    orientation_error_deg: 0,
    measured_at: `2026-08-25T01:0${index}:00Z`,
  };
}

function kinematicsDraft(points: ReturnType<typeof kinematicsPoint>[] = []) {
  return {
    draft_id: draftId,
    operator_session_id: operatorSessionId,
    operator_id: 'operator',
    robot_unit_id: 'MOMO-V1-UNIT-001',
    profile_fingerprint: profileFingerprint,
    calibration_fingerprint: 'b'.repeat(64),
    device_fingerprint: 'd'.repeat(64),
    kinematics_fingerprint: 'c'.repeat(64),
    software_commit: 'abcdef1',
    verification_checklist_version: 'kinematics-v1',
    thresholds,
    points,
  };
}

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

describe('Commissioning API client boundary', () => {
  it('accepts signed STS3215 Raw positions and direction candidates', () => {
    const sessionId = '11111111-1111-4111-8111-111111111111';
    const value = normalizeRawDirectionStatus({
      state: 'ZERO_CAPTURED',
      session_id: sessionId,
      active_joint_id: null,
      command_count: 0,
      session_expires_at: '2026-08-27T01:05:00Z',
      deadman_expires_at: null,
      zero_snapshot: {
        session_id: sessionId,
        robot_unit_id: 'MOMO-V2-UNIT-001',
        captured_at: '2026-08-27T01:00:00Z',
        raw_by_joint: { j10: -12 },
      },
      last_observation: null,
      observations: [],
      calibration_draft: {
        robot_unit_id: 'MOMO-V2-UNIT-001',
        profile_fingerprint: profileFingerprint,
        source: 'legacy-characterization',
        source_revision: 'ff8bbda',
        complete_for_review: false,
        confirmed_for_review: false,
        confirmed_at: null,
        joints: [{
          joint_id: 'j10',
          servo_id: 10,
          home_present_raw: -12,
          profile_direction_candidate: -1,
          matches_urdf: null,
          resolved_calibration_direction: null,
          phase_candidate: 28,
          raw_bounds_candidate: [-30719, 30719],
        }],
      },
      failure_reason: null,
    });

    expect(value.zero_snapshot?.raw_by_joint.j10).toBe(-12);
    expect(value.calibration_draft?.joints[0].profile_direction_candidate).toBe(-1);
    expect(value.calibration_draft?.joints[0].raw_bounds_candidate).toEqual([-30719, 30719]);
  });

  it('accepts independent read-only capabilities without claiming motion readiness', () => {
    const value = normalizeDeviceReadiness({
      state: 'AWAITING_OPERATOR_SESSION',
      ready: false,
      session_authorizable: true,
      commissioning_session_authorizable: true,
      commissioning_motion_session_authorizable: false,
      raw_direction_session_authorizable: false,
      motion_session_authorizable: false,
      blocking_reasons: ['OPERATOR_SESSION_MISSING'],
      capabilities: {
        commissioning_diagnostics_ready: true,
        calibration_capture_ready: true,
        commissioning_motion_test_ready: false,
        raw_direction_test_ready: false,
        real_joint_motion_ready: false,
        real_cartesian_motion_ready: false,
        real_playback_ready: false,
        real_vision_follow_ready: false,
      },
      capability_details: capabilityMatrix(),
      authorization_options: authorizationOptions({ readOnly: true }),
      confirmation,
      session: null,
      calibration_configured: false,
      connected: false,
    });

    expect(value.commissioning_session_authorizable).toBe(true);
    expect(value.capabilities.commissioning_diagnostics_ready).toBe(true);
    expect(value.capabilities.real_joint_motion_ready).toBe(false);
    expect(value.ready).toBe(false);
    expect(value.confirmation.field_acceptance_evidence_id).toBeNull();
    expect(() => normalizeDeviceReadiness({
      ...value,
      capability_details: undefined,
    })).toThrow('capability details');
    expect(() => normalizeDeviceReadiness({
      ...value,
      state: 'COMMISSIONING_READ_ONLY',
      session_authorizable: false,
      commissioning_session_authorizable: false,
      blocking_reasons: [],
      session: {
        active: true,
        session_id: '11111111-1111-4111-8111-111111111111',
        expires_at: '2099-01-01T00:00:00Z',
        purpose: 'COMMISSIONING_READ_ONLY',
        scopes: ['DIAGNOSTICS_READ'],
      },
    })).toThrow('scopes incoherent');
  });

  it('normalizes the staged capability matrix and purpose-specific confirmations', () => {
    const commissioningMotionConfirmation = {
      ...confirmation,
      session_purpose: 'COMMISSIONING_MOTION_TEST',
      workspace_clear_required: true,
      required_confirmation_text: 'I UNDERSTAND THIS IS A SINGLE-JOINT MOTION TEST',
    };
    const blocked = (reason: string, requiredEvidence: string[] = []) => ({
      ready: false,
      authorized: false,
      blocked_reasons: [reason],
      required_evidence: requiredEvidence,
    });
    const value = normalizeDeviceReadiness({
      state: 'AWAITING_COMMISSIONING_MOTION_SESSION',
      ready: false,
      session_authorizable: true,
      commissioning_session_authorizable: false,
      commissioning_motion_session_authorizable: true,
      raw_direction_session_authorizable: false,
      motion_session_authorizable: false,
      blocking_reasons: ['COMMISSIONING_MOTION_SESSION_REQUIRED'],
      capabilities: {
        commissioning_diagnostics_ready: false,
        calibration_capture_ready: false,
        commissioning_motion_test_ready: false,
        raw_direction_test_ready: false,
        real_joint_motion_ready: false,
        real_cartesian_motion_ready: false,
        real_playback_ready: false,
        real_vision_follow_ready: false,
      },
      capability_details: {
        commissioning_read_only: blocked('READ_ONLY_SESSION_REQUIRED'),
        commissioning_motion_test: blocked('COMMISSIONING_MOTION_SESSION_REQUIRED'),
        raw_direction_test: blocked('RAW_DIRECTION_SESSION_REQUIRED'),
        real_joint_motion: blocked('JOINT_EVIDENCE_REQUIRED', ['JOINT_MOTION_ACCEPTANCE']),
        real_cartesian_motion: blocked('KINEMATICS_EVIDENCE_REQUIRED', [
          'JOINT_MOTION_ACCEPTANCE',
          'KINEMATICS_VERIFICATION',
          'CARTESIAN_ACCEPTANCE',
        ]),
        real_playback: blocked('PLAYBACK_EVIDENCE_REQUIRED', ['PLAYBACK_ACCEPTANCE']),
        real_vision_follow: blocked('VISION_EVIDENCE_REQUIRED', ['VISION_FOLLOW_ACCEPTANCE']),
      },
      authorization_options: [
        { purpose: 'COMMISSIONING_READ_ONLY', authorizable: false, confirmation },
        {
          purpose: 'COMMISSIONING_MOTION_TEST',
          authorizable: true,
          confirmation: commissioningMotionConfirmation,
        },
        {
          purpose: 'RAW_DIRECTION_TEST',
          authorizable: false,
          confirmation: {
            ...confirmation,
            session_purpose: 'RAW_DIRECTION_TEST',
            workspace_clear_required: true,
          },
        },
        {
          purpose: 'REAL_MOTION',
          authorizable: false,
          confirmation: { ...confirmation, session_purpose: 'REAL_MOTION' },
        },
      ],
      confirmation: commissioningMotionConfirmation,
      session: null,
      calibration_configured: true,
      connected: true,
    });

    expect(value.commissioning_motion_session_authorizable).toBe(true);
    expect(value.capability_details?.commissioning_motion_test).toMatchObject({
      ready: false,
      authorized: false,
      blocked_reasons: ['COMMISSIONING_MOTION_SESSION_REQUIRED'],
    });
    expect(value.authorization_options?.map((option) => option.purpose)).toEqual([
      'COMMISSIONING_READ_ONLY',
      'COMMISSIONING_MOTION_TEST',
      'RAW_DIRECTION_TEST',
      'REAL_MOTION',
    ]);
    expect(value.confirmation).toMatchObject({
      robot_unit_id: 'MOMO-V1-UNIT-001',
      workspace_clear_required: true,
    });
  });

  it('keeps Real Motion bound to one immutable Field Acceptance evidence UUID', () => {
    const evidenceId = '33333333-3333-4333-8333-333333333333';
    const value = normalizeDeviceReadiness({
      state: 'AWAITING_OPERATOR_SESSION',
      ready: false,
      session_authorizable: true,
      commissioning_session_authorizable: false,
      commissioning_motion_session_authorizable: false,
      raw_direction_session_authorizable: false,
      motion_session_authorizable: true,
      blocking_reasons: ['OPERATOR_SESSION_MISSING'],
      capabilities: {
        commissioning_diagnostics_ready: false,
        calibration_capture_ready: false,
        commissioning_motion_test_ready: false,
        raw_direction_test_ready: false,
        real_joint_motion_ready: false,
        real_cartesian_motion_ready: false,
        real_playback_ready: false,
        real_vision_follow_ready: false,
      },
      capability_details: capabilityMatrix(),
      authorization_options: authorizationOptions({ realMotion: true }),
      confirmation: {
        ...confirmation,
        session_purpose: 'REAL_MOTION',
        field_acceptance_evidence_id: evidenceId,
      },
      session: null,
      calibration_configured: true,
      connected: false,
    });

    expect(value.confirmation.field_acceptance_evidence_id).toBe(evidenceId);
  });

  it('posts and parses an immutable purpose-bound commissioning session', async () => {
    const fetchMock = vi.fn().mockResolvedValue(response({
      session_token: 'commissioning-token-material',
      session_id: '11111111-1111-4111-8111-111111111111',
      issued_at: '2026-08-24T01:00:00Z',
      expires_at: '2026-08-24T01:05:00Z',
      purpose: 'COMMISSIONING_READ_ONLY',
      scopes: ['CALIBRATION_CAPTURE', 'DIAGNOSTICS_READ'],
      evidence: confirmation,
    }));
    vi.stubGlobal('fetch', fetchMock);

    const session = await createOperatorSession(
      'COMMISSIONING_READ_ONLY',
      'I UNDERSTAND COMMISSIONING IS READ ONLY',
      true,
    );

    expect(session.purpose).toBe('COMMISSIONING_READ_ONLY');
    expect(session.scopes).toEqual(['CALIBRATION_CAPTURE', 'DIAGNOSTICS_READ']);
    expect(session).not.toHaveProperty('session_token');
    expect(fetchMock).toHaveBeenCalledWith(
      '/api/v1/device/operator-session',
      expect.objectContaining({
        method: 'POST',
        credentials: 'include',
        body: JSON.stringify({
          purpose: 'COMMISSIONING_READ_ONLY',
          confirmation_text: 'I UNDERSTAND COMMISSIONING IS READ ONLY',
          physical_estop_confirmed: true,
          workspace_clear_confirmed: false,
        }),
      }),
    );

    fetchMock.mockResolvedValueOnce(response({
      session_token: 'commissioning-token-material',
      session_id: '11111111-1111-4111-8111-111111111111',
      issued_at: '2026-08-24T01:00:00Z',
      expires_at: '2026-08-24T01:05:00Z',
      purpose: 'COMMISSIONING_READ_ONLY',
      scopes: ['DIAGNOSTICS_READ'],
      evidence: confirmation,
    }));
    await expect(createOperatorSession(
      'COMMISSIONING_READ_ONLY',
      'I UNDERSTAND COMMISSIONING IS READ ONLY',
      true,
    )).rejects.toThrow('scopes incoherent');

    fetchMock.mockResolvedValueOnce(response({
      session_token: 'commissioning-token-material',
      session_id: '11111111-1111-4111-8111-111111111111',
      issued_at: '2026-08-24T01:00:00Z',
      expires_at: '2026-08-24T01:05:00Z',
      purpose: 'COMMISSIONING_READ_ONLY',
      scopes: ['CALIBRATION_CAPTURE', 'DIAGNOSTICS_READ'],
      evidence: { ...confirmation, session_purpose: 'REAL_MOTION' },
    }));
    await expect(createOperatorSession(
      'COMMISSIONING_READ_ONLY',
      'I UNDERSTAND COMMISSIONING IS READ ONLY',
      true,
    )).rejects.toThrow('evidence for another purpose');
  });

  it('issues a non-upgradeable commissioning-motion summary with workspace clearance', async () => {
    const motionEvidence = {
      ...confirmation,
      session_purpose: 'COMMISSIONING_MOTION_TEST',
      workspace_clear_required: true,
      required_confirmation_text: 'I UNDERSTAND THIS IS A SINGLE-JOINT MOTION TEST',
    };
    const fetchMock = vi.fn().mockResolvedValue(response({
      session_token: 'legacy-secret-that-must-be-stripped',
      session_id: '22222222-2222-4222-8222-222222222222',
      issued_at: '2026-08-24T01:00:00Z',
      expires_at: '2026-08-24T01:05:00Z',
      purpose: 'COMMISSIONING_MOTION_TEST',
      scopes: ['COMMISSIONING_SINGLE_JOINT_TEST'],
      evidence: motionEvidence,
    }));
    vi.stubGlobal('fetch', fetchMock);

    const session = await createOperatorSession(
      'COMMISSIONING_MOTION_TEST',
      motionEvidence.required_confirmation_text,
      true,
      true,
    );

    expect(session).toEqual({
      session_id: '22222222-2222-4222-8222-222222222222',
      issued_at: '2026-08-24T01:00:00Z',
      expires_at: '2026-08-24T01:05:00Z',
      purpose: 'COMMISSIONING_MOTION_TEST',
      scopes: ['COMMISSIONING_SINGLE_JOINT_TEST'],
      evidence: expect.objectContaining({
        robot_unit_id: 'MOMO-V1-UNIT-001',
        workspace_clear_required: true,
      }),
    });
    expect(fetchMock).toHaveBeenCalledWith(
      '/api/v1/device/operator-session',
      expect.objectContaining({
        credentials: 'include',
        body: JSON.stringify({
          purpose: 'COMMISSIONING_MOTION_TEST',
          confirmation_text: motionEvidence.required_confirmation_text,
          physical_estop_confirmed: true,
          workspace_clear_confirmed: true,
        }),
      }),
    );
  });

  it('uses only the same-origin cookie for protected device and calibration calls', async () => {
    const fetchMock = vi.fn().mockResolvedValue(response({}));
    vi.stubGlobal('fetch', fetchMock);

    await revokeOperatorSession();
    await expect(connectRealDevice()).rejects.toThrow();
    await expect(disconnectRealDevice()).rejects.toThrow();
    await expect(runDeviceDiagnostics()).rejects.toThrow();
    await expect(startCalibrationSession()).rejects.toThrow();

    expect(fetchMock.mock.calls.map(([url]) => url)).toEqual([
      '/api/v1/device/operator-session',
      '/api/v1/device/connect',
      '/api/v1/device/disconnect',
      '/api/v1/device/diagnostics',
      '/api/v1/device/calibration/sessions',
    ]);
    for (const [, init] of fetchMock.mock.calls) {
      expect(init).toEqual(expect.objectContaining({ credentials: 'include' }));
      expect(new Headers(init?.headers).has('X-MOMO-Operator-Session')).toBe(false);
    }
  });

  it('normalizes the backend empty device-error sentinel to null', () => {
    expect(normalizeDeviceDiagnostics({
      connected: true,
      captured_at: '2026-08-27T07:00:00Z',
      dependency: {
        adapter_id: 'feetech-servo-bus-shell',
        state: 'AVAILABLE',
        package_name: 'ftservo-python-sdk==2.0.0',
        license_status: 'MIT',
        notice: 'Reviewed read-only adapter',
      },
      hardware_policy: 'READ_ONLY',
      masked_serial_port: '***3871',
      masked_servo_ids: ['servo-1'],
      protocol: 'STS3215',
      profile: {
        configured: true,
        fingerprint: profileFingerprint,
        verification_status: 'VERIFIED_FOR_DRY_RUN',
        template: true,
        ready_for_real: false,
      },
      calibration: {
        configured: false,
        fingerprint: null,
        verification_status: 'BLOCKED',
        template: null,
        ready_for_real: false,
      },
      kinematics: {
        configured: false,
        fingerprint: null,
        verification_status: null,
        template: null,
        ready_for_real: false,
      },
      field_acceptance: 'PENDING',
      readiness: 'COMMISSIONING_READ_ONLY',
      records: [{
        joint_id: 'j10',
        masked_servo_id: 'servo-1',
        ping_responded: true,
        operating_mode: 'MULTI_TURN',
        present_raw: 2048,
        logical_value: null,
        raw_bounds: null,
        torque_enabled: false,
      }],
      last_error: '',
    }).last_error).toBeNull();
  });

  it('normalizes a fresh Calibration Draft with no fabricated base revision', () => {
    const value = normalizeCalibrationWorkflowStatus({
      session_id: '22222222-2222-4222-8222-222222222222',
      authorization_session_id: '11111111-1111-4111-8111-111111111111',
      robot_id: 'primary',
      variant: 'V1',
      profile_fingerprint: profileFingerprint,
      base_revision: null,
      base_calibration_fingerprint: null,
      source: 'EXISTING_REAL',
      draft: {
        robot_variant: 'V1',
        profile_fingerprint: profileFingerprint,
        enabled_joints: ['j11'],
        created_at: '2026-08-24T01:01:00Z',
        base_revision: null,
        base_calibration_fingerprint: null,
        joints: [{
          joint_id: 'j11',
          servo_id: 11,
          present_raw: null,
          logical_value: null,
          direction: null,
          phase: null,
          raw_bounds: null,
          operating_mode: null,
        }],
      },
      state: 'ACTIVE',
      required_joint_ids: ['j11'],
      confirmed_joint_ids: [],
      selected_joint_id: null,
      observed_raw: null,
      preview: null,
      save_preview: null,
      saved_revision: null,
      saved_calibration_fingerprint: null,
      updated_at: '2026-08-24T01:01:00Z',
    });

    expect(value.base_revision).toBeNull();
    expect(value.draft.joints[0]).toMatchObject({
      joint_id: 'j11',
      present_raw: null,
      logical_value: null,
      direction: null,
    });
  });

  it('bounds and displays stale Field Acceptance evidence without mutating it', async () => {
    const stale = {
      state: 'STALE',
      effective_status: 'PENDING',
      checklist_version: '1',
      stale_fields: ['calibration_fingerprint'],
      evidence_id: '33333333-3333-4333-8333-333333333333',
      accepted_at: '2026-08-24T00:00:00Z',
      accepted_by: 'operator',
      required_confirmation_text: 'I CONFIRM THE FIELD ACCEPTANCE CHECKLIST IS COMPLETE',
    };
    expect(normalizeFieldAcceptanceStatus(stale)).toMatchObject(stale);
    expect(() => normalizeFieldAcceptanceStatus({
      ...stale,
      stale_fields: Array.from({ length: 17 }, (_, index) => `field-${index}`),
    })).toThrow('Field Acceptance stale fields');
    expect(() => normalizeFieldAcceptanceStatus({
      ...stale,
      evidence_id: 'not-an-evidence-uuid',
    })).toThrow('Field Acceptance evidence ID');

    const fetchMock = vi.fn().mockResolvedValue(response(stale));
    vi.stubGlobal('fetch', fetchMock);
    await expect(getFieldAcceptanceStatus()).resolves.toMatchObject(stale);
    expect(fetchMock).toHaveBeenCalledWith(
      '/api/v1/device/field-acceptance',
      expect.objectContaining({ credentials: 'include' }),
    );
  });

  it('reads and advances only staged, persisted Field Acceptance progress', async () => {
    expect(normalizeFieldAcceptanceProgress(fieldProgress)).toMatchObject(fieldProgress);
    expect(() => normalizeFieldAcceptanceProgress({
      ...fieldProgress,
      completed_joint_directions: 1,
    })).toThrow('incoherent Field Acceptance progress');
    expect(() => normalizeFieldAcceptanceProgress({
      ...fieldProgress,
      joints: [{ ...fieldProgress.joints[0], complete: false }],
    })).toThrow('incoherent Field Acceptance joint progress');

    const accepted = {
      ...fieldProgress,
      state: 'KINEMATICS_VERIFICATION_PENDING',
      valid_capabilities: ['PRE_MOTION_CHECKS', 'JOINT_MOTION'],
      joint_motion_accepted: true,
      ready_to_accept_joint_motion: false,
    };
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(response(fieldProgress))
      .mockResolvedValueOnce(response(fieldProgress))
      .mockResolvedValueOnce(response(accepted));
    vi.stubGlobal('fetch', fetchMock);

    await expect(getFieldAcceptanceProgress()).resolves.toMatchObject(fieldProgress);
    await expect(completeFieldPreMotionChecks(' field-v2 ')).resolves.toMatchObject(fieldProgress);
    await expect(acceptFieldJointMotion('field-v2')).resolves.toMatchObject(accepted);

    expect(fetchMock.mock.calls.map(([url]) => url)).toEqual([
      '/api/v1/device/field-acceptance/progress',
      '/api/v1/device/field-acceptance/pre-motion-checks',
      '/api/v1/device/field-acceptance/joint-motion',
    ]);
    expect(fetchMock.mock.calls[1]?.[1]).toEqual(expect.objectContaining({
      method: 'POST',
      credentials: 'include',
      body: JSON.stringify({ checklist_version: 'field-v2' }),
    }));
    expect(fetchMock.mock.calls[2]?.[1]).toEqual(expect.objectContaining({
      method: 'POST',
      credentials: 'include',
      body: JSON.stringify({ checklist_version: 'field-v2' }),
    }));
    expect(fetchMock.mock.calls.some(([, init]) => (
      new Headers(init?.headers).has('X-MOMO-Operator-Session')
    ))).toBe(false);
  });

  it('uses a session-bound measured-TCP draft with no model-label shortcut', async () => {
    const point1 = kinematicsPoint(1);
    const points = [point1, kinematicsPoint(2), kinematicsPoint(3)];
    const evidence = {
      schema_version: 1,
      revision: 1,
      id: '99999999-9999-4999-8999-999999999999',
      robot_unit_id: 'MOMO-V1-UNIT-001',
      variant: 'V1',
      profile_fingerprint: profileFingerprint,
      calibration_fingerprint: 'b'.repeat(64),
      device_fingerprint: 'd'.repeat(64),
      kinematics_fingerprint: 'c'.repeat(64),
      kinematics_model_schema_version: '1.0.0',
      verification_checklist_version: 'kinematics-v1',
      test_points: points,
      thresholds,
      accepted_at: '2026-08-25T02:00:00Z',
      accepted_by: 'operator',
      software_commit: 'abcdef1',
    };
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(response({
        state: 'MISSING',
        stale_fields: [],
        evidence_id: null,
        point_count: 0,
      }))
      .mockResolvedValueOnce(response(kinematicsDraft()))
      .mockResolvedValueOnce(response(kinematicsDraft([point1])))
      .mockResolvedValueOnce(response(evidence));
    vi.stubGlobal('fetch', fetchMock);

    await expect(getKinematicsVerificationStatus()).resolves.toMatchObject({ state: 'MISSING' });
    await expect(startKinematicsVerificationDraft(thresholds)).resolves.toMatchObject({
      draft_id: draftId,
      points: [],
    });
    await expect(addKinematicsVerificationMeasurement(draftId, {
      label: ' gauge-1 ',
      measured_tcp: point1.measured_tcp,
    })).resolves.toMatchObject({ points: [{ label: 'gauge-1' }] });
    await expect(commitKinematicsVerificationDraft(draftId)).resolves.toMatchObject({
      id: evidence.id,
      test_points: points,
    });

    expect(fetchMock.mock.calls.map(([url]) => url)).toEqual([
      '/api/v1/kinematics-verification',
      '/api/v1/kinematics-verification/draft',
      `/api/v1/kinematics-verification/draft/${draftId}/measurement`,
      `/api/v1/kinematics-verification/draft/${draftId}/commit`,
    ]);
    expect(fetchMock.mock.calls[2]?.[1]).toEqual(expect.objectContaining({
      credentials: 'include',
      body: JSON.stringify({
        label: 'gauge-1',
        measured_tcp: point1.measured_tcp,
      }),
    }));
    expect(JSON.stringify(fetchMock.mock.calls)).not.toContain('session_token');
  });
});
