import { afterEach, describe, expect, it, vi } from 'vitest';

import {
  createOperatorSession,
  getFieldAcceptanceStatus,
  normalizeCalibrationWorkflowStatus,
  normalizeDeviceReadiness,
  normalizeFieldAcceptanceStatus,
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
  required_confirmation_text: 'I UNDERSTAND COMMISSIONING IS READ ONLY',
};

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

describe('Commissioning API client boundary', () => {
  it('accepts independent read-only capabilities without claiming motion readiness', () => {
    const value = normalizeDeviceReadiness({
      state: 'AWAITING_OPERATOR_SESSION',
      ready: false,
      session_authorizable: true,
      commissioning_session_authorizable: true,
      motion_session_authorizable: false,
      blocking_reasons: ['OPERATOR_SESSION_MISSING'],
      capabilities: {
        commissioning_diagnostics_ready: true,
        calibration_capture_ready: true,
        real_joint_motion_ready: false,
        real_cartesian_motion_ready: false,
        real_playback_ready: false,
        real_vision_follow_ready: false,
      },
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

  it('keeps Real Motion bound to one immutable Field Acceptance evidence UUID', () => {
    const evidenceId = '33333333-3333-4333-8333-333333333333';
    const value = normalizeDeviceReadiness({
      state: 'AWAITING_OPERATOR_SESSION',
      ready: false,
      session_authorizable: true,
      commissioning_session_authorizable: false,
      motion_session_authorizable: true,
      blocking_reasons: ['OPERATOR_SESSION_MISSING'],
      capabilities: {
        commissioning_diagnostics_ready: false,
        calibration_capture_ready: false,
        real_joint_motion_ready: false,
        real_cartesian_motion_ready: false,
        real_playback_ready: false,
        real_vision_follow_ready: false,
      },
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
    expect(fetchMock).toHaveBeenCalledWith(
      '/api/v1/device/operator-session',
      expect.objectContaining({
        method: 'POST',
        body: JSON.stringify({
          purpose: 'COMMISSIONING_READ_ONLY',
          confirmation_text: 'I UNDERSTAND COMMISSIONING IS READ ONLY',
          physical_estop_confirmed: true,
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
});
