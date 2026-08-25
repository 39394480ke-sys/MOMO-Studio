import { act, render, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import {
  createOperatorSession,
  getDeviceReadiness,
  revokeOperatorSession,
} from '../api/client';
import type {
  DeviceCapabilityDetail,
  DeviceConfirmationEvidence,
  DeviceReadiness,
  OperatorSessionResponse,
} from '../api/types';
import { RealSessionProvider } from './RealSessionProvider';
import {
  useRealSession,
  type RealSessionContextValue,
} from './realSessionContext';
import {
  RuntimeStatusContext,
  SAFE_RUNTIME_STATUS,
  type RuntimeStatus,
} from './runtimeStatusContext';

vi.mock('../api/client', () => ({
  createOperatorSession: vi.fn(),
  getDeviceReadiness: vi.fn(),
  revokeOperatorSession: vi.fn(),
}));

const confirmation: DeviceConfirmationEvidence = {
  robot_id: 'primary',
  robot_unit_id: 'MOMO-V2-UNIT-001',
  variant: 'V2',
  profile_fingerprint: 'a'.repeat(64),
  calibration_fingerprint: 'b'.repeat(64),
  kinematics_fingerprint: 'c'.repeat(64),
  masked_serial_port: '/***USB0',
  masked_servo_ids: ['**1'],
  protocol: 'sts',
  session_purpose: 'COMMISSIONING_MOTION_TEST',
  field_acceptance_evidence_id: null,
  physical_estop_required: true,
  workspace_clear_required: true,
  required_confirmation_text: 'I UNDERSTAND THIS IS A SINGLE-JOINT MOTION TEST',
};

function detail(
  ready: boolean,
  authorized: boolean,
  blockedReasons: string[] = [],
): DeviceCapabilityDetail {
  return {
    ready,
    authorized,
    blocked_reasons: blockedReasons,
    required_evidence: [],
  };
}

function readiness(options: {
  active?: boolean;
  expiresAt?: string;
} = {}): DeviceReadiness {
  const active = options.active ?? false;
  return {
    state: active ? 'COMMISSIONING_MOTION_TEST' : 'AWAITING_COMMISSIONING_MOTION_SESSION',
    ready: false,
    session_authorizable: !active,
    commissioning_session_authorizable: false,
    commissioning_motion_session_authorizable: !active,
    motion_session_authorizable: false,
    blocking_reasons: active ? [] : ['COMMISSIONING_MOTION_SESSION_REQUIRED'],
    capabilities: {
      commissioning_diagnostics_ready: false,
      calibration_capture_ready: false,
      commissioning_motion_test_ready: active,
      real_joint_motion_ready: false,
      real_cartesian_motion_ready: false,
      real_playback_ready: false,
      real_vision_follow_ready: false,
    },
    capability_details: {
      commissioning_read_only: detail(false, false, ['READ_ONLY_SESSION_REQUIRED']),
      commissioning_motion_test: detail(
        active,
        active,
        active ? [] : ['COMMISSIONING_MOTION_SESSION_REQUIRED'],
      ),
      real_joint_motion: detail(false, false, ['JOINT_ACCEPTANCE_REQUIRED']),
      real_cartesian_motion: detail(false, false, ['KINEMATICS_VERIFICATION_REQUIRED']),
      real_playback: detail(false, false, ['PLAYBACK_ACCEPTANCE_REQUIRED']),
      real_vision_follow: detail(false, false, ['VISION_ACCEPTANCE_REQUIRED']),
    },
    authorization_options: [
      {
        purpose: 'COMMISSIONING_READ_ONLY',
        authorizable: false,
        confirmation: { ...confirmation, session_purpose: 'COMMISSIONING_READ_ONLY' },
      },
      {
        purpose: 'COMMISSIONING_MOTION_TEST',
        authorizable: !active,
        confirmation,
      },
      {
        purpose: 'REAL_MOTION',
        authorizable: false,
        confirmation: { ...confirmation, session_purpose: 'REAL_MOTION' },
      },
    ],
    confirmation,
    session: active ? {
      active: true,
      session_id: '22222222-2222-4222-8222-222222222222',
      expires_at: options.expiresAt ?? '2099-01-01T00:00:00Z',
      purpose: 'COMMISSIONING_MOTION_TEST',
      scopes: ['COMMISSIONING_SINGLE_JOINT_TEST'],
    } : null,
    calibration_configured: true,
    connected: true,
  };
}

function runtime(
  controlMode: RuntimeStatus['controlMode'],
  options: Partial<RuntimeStatus> = {},
): RuntimeStatus {
  return {
    ...SAFE_RUNTIME_STATUS,
    backend: 'connected',
    stale: false,
    controlMode,
    hardwareAccessPolicy: controlMode === 'REAL' ? 'FULL' : 'DISABLED',
    ...options,
  };
}

let currentContext: RealSessionContextValue | null = null;

function ContextProbe() {
  currentContext = useRealSession();
  return <div data-testid="real-session-probe" />;
}

function renderProvider(status: RuntimeStatus) {
  return render(
    <RuntimeStatusContext.Provider value={status}>
      <RealSessionProvider>
        <ContextProbe />
      </RealSessionProvider>
    </RuntimeStatusContext.Provider>,
  );
}

beforeEach(() => {
  currentContext = null;
  vi.mocked(createOperatorSession).mockReset();
  vi.mocked(getDeviceReadiness).mockReset();
  vi.mocked(revokeOperatorSession).mockReset();
  vi.mocked(revokeOperatorSession).mockResolvedValue();
});

afterEach(() => {
  vi.useRealTimers();
  vi.restoreAllMocks();
});

describe('RealSessionProvider', () => {
  it('does not poll or issue a session outside REAL control mode', async () => {
    renderProvider(runtime('DRY RUN'));
    await act(async () => Promise.resolve());

    expect(getDeviceReadiness).not.toHaveBeenCalled();
    expect(createOperatorSession).not.toHaveBeenCalled();
    expect(currentContext?.summary.session).toBeNull();
    expect(Object.values(currentContext?.summary.capabilityDetails ?? {})
      .every((value) => !value.ready && !value.authorized)).toBe(true);
  });

  it('publishes only the backend-derived capability summary in REAL mode', async () => {
    const backendReadiness = readiness({ active: true });
    vi.mocked(getDeviceReadiness).mockResolvedValue(backendReadiness);

    renderProvider(runtime('REAL'));

    await waitFor(() => expect(getDeviceReadiness).toHaveBeenCalledTimes(1));
    await waitFor(() => expect(currentContext?.summary.stale).toBe(false));
    expect(currentContext?.summary.session).toMatchObject({
      purpose: 'COMMISSIONING_MOTION_TEST',
      scopes: ['COMMISSIONING_SINGLE_JOINT_TEST'],
    });
    expect(currentContext?.summary.capabilityDetails.commissioning_motion_test.authorized)
      .toBe(true);
    expect(currentContext?.summary.capabilityDetails.real_joint_motion.authorized).toBe(false);
    expect(currentContext?.summary.capabilityDetails).toEqual(
      backendReadiness.capability_details,
    );
    expect(createOperatorSession).not.toHaveBeenCalled();
  });

  it('issues only after an explicit authorize call and never writes browser storage', async () => {
    const issued: OperatorSessionResponse = {
      session_id: '22222222-2222-4222-8222-222222222222',
      issued_at: '2026-08-24T01:00:00Z',
      expires_at: '2099-01-01T00:00:00Z',
      purpose: 'COMMISSIONING_MOTION_TEST',
      scopes: ['COMMISSIONING_SINGLE_JOINT_TEST'],
      evidence: confirmation,
    };
    vi.mocked(getDeviceReadiness)
      .mockResolvedValueOnce(readiness())
      .mockResolvedValue(readiness({ active: true }));
    vi.mocked(createOperatorSession).mockResolvedValue(issued);
    const storageWrite = vi.spyOn(Storage.prototype, 'setItem');
    renderProvider(runtime('REAL'));
    await waitFor(() => expect(currentContext?.summary.loading).toBe(false));

    let result: OperatorSessionResponse | null = null;
    await act(async () => {
      result = await currentContext?.authorize(
        'COMMISSIONING_MOTION_TEST',
        confirmation.required_confirmation_text,
        true,
        true,
      ) ?? null;
    });

    expect(createOperatorSession).toHaveBeenCalledWith(
      'COMMISSIONING_MOTION_TEST',
      confirmation.required_confirmation_text,
      true,
      true,
    );
    expect(result).toEqual(issued);
    expect(result).not.toHaveProperty('session_token');
    expect(currentContext?.summary.session?.session_id).toBe(issued.session_id);
    expect(storageWrite).not.toHaveBeenCalled();
  });

  it('revokes through the cookie session and refreshes to a closed backend summary', async () => {
    vi.mocked(getDeviceReadiness)
      .mockResolvedValueOnce(readiness({ active: true }))
      .mockResolvedValue(readiness());
    renderProvider(runtime('REAL'));
    await waitFor(() => expect(
      currentContext?.summary.capabilityDetails.commissioning_motion_test.authorized,
    ).toBe(true));

    await act(async () => {
      await currentContext?.revoke();
    });

    expect(revokeOperatorSession).toHaveBeenCalledTimes(1);
    expect(getDeviceReadiness).toHaveBeenCalledTimes(2);
    expect(currentContext?.summary.session).toBeNull();
    expect(Object.values(currentContext?.summary.capabilityDetails ?? {})
      .every((value) => !value.authorized)).toBe(true);
  });

  it('fails every capability closed when readiness refresh fails', async () => {
    vi.mocked(getDeviceReadiness).mockResolvedValueOnce(readiness({ active: true }));
    renderProvider(runtime('REAL'));
    await waitFor(() => expect(
      currentContext?.summary.capabilityDetails.commissioning_motion_test.authorized,
    ).toBe(true));
    vi.mocked(getDeviceReadiness).mockRejectedValueOnce(new Error('readiness offline'));

    await act(async () => {
      await currentContext?.refresh();
    });

    expect(currentContext?.summary).toMatchObject({
      stale: true,
      session: null,
      error: 'readiness offline',
    });
    expect(Object.values(currentContext?.summary.capabilityDetails ?? {})
      .every((value) => !value.ready && !value.authorized)).toBe(true);
  });

  it('rejects an already-expired backend session summary', async () => {
    vi.mocked(getDeviceReadiness).mockResolvedValue(readiness({
      active: true,
      expiresAt: '2020-01-01T00:00:00Z',
    }));
    renderProvider(runtime('REAL'));

    await waitFor(() => expect(currentContext?.summary.error).toMatch(/expired/i));
    expect(currentContext?.summary.stale).toBe(true);
    expect(currentContext?.summary.session).toBeNull();
    expect(currentContext?.summary.capabilityDetails.commissioning_motion_test.authorized)
      .toBe(false);
  });

  it('does not poll when REAL runtime status is stale', async () => {
    renderProvider(runtime('REAL', { stale: true }));
    await act(async () => Promise.resolve());

    expect(getDeviceReadiness).not.toHaveBeenCalled();
    expect(currentContext?.summary.stale).toBe(true);
    expect(currentContext?.summary.error).toMatch(/stale/i);
  });
});
