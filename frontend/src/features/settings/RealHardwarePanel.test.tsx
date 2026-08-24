import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import {
  connectRealDevice,
  createOperatorSession,
  disconnectRealDevice,
  getDeviceReadiness,
  getFieldAcceptanceStatus,
  revokeOperatorSession,
  runDeviceDiagnostics,
  stopRealDevice,
} from '../../api/client';
import type {
  DeviceConfirmationEvidence,
  DeviceDiagnostics,
  DeviceReadiness,
} from '../../api/types';
import { RealHardwarePanel } from './RealHardwarePanel';

vi.mock('../../api/client', () => ({
  ApiError: class ApiError extends Error { status = 500; },
  connectRealDevice: vi.fn(),
  createOperatorSession: vi.fn(),
  disconnectRealDevice: vi.fn(),
  getDeviceReadiness: vi.fn(),
  getFieldAcceptanceStatus: vi.fn(),
  revokeOperatorSession: vi.fn(),
  runDeviceDiagnostics: vi.fn(),
  stopRealDevice: vi.fn(),
}));

const motionConfirmation: DeviceConfirmationEvidence = {
  robot_id: 'primary',
  variant: 'V2',
  profile_fingerprint: 'a'.repeat(64),
  calibration_fingerprint: 'b'.repeat(64),
  kinematics_fingerprint: 'c'.repeat(64),
  masked_serial_port: '/***USB0',
  masked_servo_ids: ['**1', '**2'],
  protocol: 'sts',
  session_purpose: 'REAL_MOTION',
  field_acceptance_evidence_id: '33333333-3333-4333-8333-333333333333',
  physical_estop_required: true,
  required_confirmation_text: 'I UNDERSTAND REAL HARDWARE CAN MOVE',
};

const commissioningConfirmation: DeviceConfirmationEvidence = {
  ...motionConfirmation,
  calibration_fingerprint: null,
  kinematics_fingerprint: null,
  session_purpose: 'COMMISSIONING_READ_ONLY',
  field_acceptance_evidence_id: null,
  required_confirmation_text: 'I UNDERSTAND COMMISSIONING IS READ ONLY',
};

function readiness(options: Partial<DeviceReadiness> = {}): DeviceReadiness {
  return {
    state: 'BLOCKED_BY_CONTROL_MODE',
    ready: false,
    session_authorizable: false,
    commissioning_session_authorizable: false,
    motion_session_authorizable: false,
    blocking_reasons: ['CONTROL_MODE_MUST_BE_REAL'],
    capabilities: {
      commissioning_diagnostics_ready: false,
      calibration_capture_ready: false,
      real_joint_motion_ready: false,
      real_cartesian_motion_ready: false,
      real_playback_ready: false,
      real_vision_follow_ready: false,
    },
    confirmation: motionConfirmation,
    session: null,
    calibration_configured: false,
    connected: false,
    ...options,
  };
}

function commissioningReadiness(options: Partial<DeviceReadiness> = {}): DeviceReadiness {
  return readiness({
    state: 'AWAITING_OPERATOR_SESSION',
    session_authorizable: true,
    commissioning_session_authorizable: true,
    blocking_reasons: ['OPERATOR_SESSION_MISSING'],
    capabilities: {
      commissioning_diagnostics_ready: true,
      calibration_capture_ready: true,
      real_joint_motion_ready: false,
      real_cartesian_motion_ready: false,
      real_playback_ready: false,
      real_vision_follow_ready: false,
    },
    confirmation: commissioningConfirmation,
    ...options,
  });
}

const commissioningDiagnostics: DeviceDiagnostics = {
  connected: true,
  captured_at: '2026-08-24T01:02:03Z',
  dependency: {
    adapter_id: 'fake-servo-bus',
    state: 'AVAILABLE',
    package_name: null,
    license_status: 'TEST_ONLY',
    notice: 'Fake adapter',
  },
  hardware_policy: 'READ_ONLY',
  masked_serial_port: '/***USB0',
  masked_servo_ids: ['**1', '**2'],
  protocol: 'sts',
  profile: { configured: true, fingerprint: 'a'.repeat(64), verification_status: 'VERIFIED_FOR_REAL', template: false, ready_for_real: true },
  calibration: { configured: false, fingerprint: null, verification_status: null, template: null, ready_for_real: false },
  kinematics: { configured: true, fingerprint: 'c'.repeat(64), verification_status: 'PROVISIONAL_DRY_RUN', template: null, ready_for_real: false },
  field_acceptance: 'PENDING',
  readiness: 'COMMISSIONING_READ_ONLY',
  records: [{
    joint_id: 'j11',
    masked_servo_id: '**1',
    ping_responded: true,
    operating_mode: 'POSITION',
    present_raw: 2048,
    logical_value: null,
    raw_bounds: null,
    torque_enabled: false,
  }],
  last_error: null,
};

const pendingAcceptance = {
  state: 'MISSING' as const,
  effective_status: 'PENDING' as const,
  checklist_version: '1',
  stale_fields: [],
  evidence_id: null,
  accepted_at: null,
  accepted_by: null,
  required_confirmation_text: 'I CONFIRM THE FIELD ACCEPTANCE CHECKLIST IS COMPLETE',
};

function activeCommissioning(
  connected = false,
  calibrationConfigured = false,
): DeviceReadiness {
  return commissioningReadiness({
    state: 'COMMISSIONING_READ_ONLY',
    session_authorizable: false,
    commissioning_session_authorizable: false,
    blocking_reasons: [],
    session: {
      active: true,
      session_id: 'session-commissioning',
      expires_at: '2099-01-01T00:00:00Z',
      purpose: 'COMMISSIONING_READ_ONLY',
      scopes: ['DIAGNOSTICS_READ', 'CALIBRATION_CAPTURE'],
    },
    calibration_configured: calibrationConfigured,
    connected,
  });
}

function memoryStorageSpy(): Storage {
  return {
    clear: vi.fn(),
    getItem: vi.fn(() => null),
    key: vi.fn(() => null),
    length: 0,
    removeItem: vi.fn(),
    setItem: vi.fn(),
  };
}

beforeEach(() => {
  vi.mocked(connectRealDevice).mockReset();
  vi.mocked(createOperatorSession).mockReset();
  vi.mocked(disconnectRealDevice).mockReset();
  vi.mocked(getDeviceReadiness).mockReset();
  vi.mocked(getFieldAcceptanceStatus).mockReset();
  vi.mocked(getFieldAcceptanceStatus).mockResolvedValue(pendingAcceptance);
  vi.mocked(revokeOperatorSession).mockReset();
  vi.mocked(runDeviceDiagnostics).mockReset();
  vi.mocked(stopRealDevice).mockReset();
  Object.defineProperty(window, 'localStorage', { configurable: true, value: memoryStorageSpy() });
  Object.defineProperty(window, 'sessionStorage', { configurable: true, value: memoryStorageSpy() });
});

afterEach(() => {
  vi.useRealTimers();
});

async function authorizeCommissioning() {
  fireEvent.click(await screen.findByRole('button', { name: 'Authorize READ ONLY' }));
  const confirmButton = screen.getByRole('button', { name: 'Authorize READ ONLY session' });
  expect(confirmButton).toBeDisabled();
  fireEvent.change(screen.getByLabelText(/Type the exact confirmation text/), {
    target: { value: commissioningConfirmation.required_confirmation_text },
  });
  fireEvent.click(screen.getByLabelText(/tested physical E-stop/));
  fireEvent.click(confirmButton);
  await screen.findByText(/READ ONLY · Expires at/);
}

describe('RealHardwarePanel', () => {
  it('shows Hardware Disabled and performs no hardware request by default', async () => {
    vi.mocked(getDeviceReadiness).mockResolvedValue(readiness());
    render(<RealHardwarePanel />);

    expect(await screen.findByText('CONTROL_MODE_MUST_BE_REAL')).toBeVisible();
    expect(screen.getByText('Hardware access disabled')).toBeVisible();
    expect(screen.getByText('Commissioning / Read-only').nextElementSibling)
      .toHaveTextContent('UNAVAILABLE');
    expect(screen.getByRole('button', { name: 'Authorize Real Motion' })).toBeDisabled();
    expect(screen.getByRole('button', { name: /Real Motion software Stop/ })).toBeDisabled();
    expect(connectRealDevice).not.toHaveBeenCalled();
    expect(runDeviceDiagnostics).not.toHaveBeenCalled();
  });

  it('renders a fresh robot as Commissioning available, READ ONLY, and motion blocked', async () => {
    vi.mocked(getDeviceReadiness).mockResolvedValue(commissioningReadiness());
    render(<RealHardwarePanel />);

    expect(await screen.findByText('Commissioning available · READ ONLY')).toBeVisible();
    expect(screen.getByText('Commissioning mode')).toBeVisible();
    expect(screen.getAllByText('READ ONLY').length).toBeGreaterThan(0);
    expect(screen.getByText(/No motion commands are permitted/)).toBeVisible();
    expect(screen.getAllByText('Not configured').length).toBeGreaterThan(0);
    expect(screen.getByText('Commissioning diagnostics')).toBeVisible();
    expect(screen.getByText('Calibration capture')).toBeVisible();
    expect(screen.getByText('Joint motion').nextElementSibling).toHaveTextContent('BLOCKED');
    expect(screen.getByRole('button', { name: 'Connect Read-Only' })).toBeDisabled();
    expect(screen.getByRole('button', { name: 'Diagnostics' })).toBeDisabled();
    expect(screen.getByRole('button', { name: /Real Motion software Stop/ })).toBeDisabled();
    expect(screen.queryByRole('button', { name: /Jog|Home|Move|Playback|Vision Follow/i })).not.toBeInTheDocument();
  });

  it('issues a purpose-bound commissioning token, then exposes only diagnostics and calibration', async () => {
    vi.mocked(getDeviceReadiness)
      .mockResolvedValueOnce(commissioningReadiness())
      .mockResolvedValueOnce(activeCommissioning(false))
      .mockResolvedValue(activeCommissioning(true));
    vi.mocked(createOperatorSession).mockResolvedValue({
      session_token: 'commissioning-memory-only-token',
      session_id: 'session-commissioning',
      issued_at: '2026-08-24T01:00:00Z',
      expires_at: '2099-01-01T00:00:00Z',
      purpose: 'COMMISSIONING_READ_ONLY',
      scopes: ['DIAGNOSTICS_READ', 'CALIBRATION_CAPTURE'],
      evidence: commissioningConfirmation,
    });
    vi.mocked(connectRealDevice).mockResolvedValue(commissioningDiagnostics);
    vi.mocked(runDeviceDiagnostics).mockResolvedValue(commissioningDiagnostics);

    render(<RealHardwarePanel />);
    await authorizeCommissioning();

    expect(createOperatorSession).toHaveBeenCalledWith(
      'COMMISSIONING_READ_ONLY',
      commissioningConfirmation.required_confirmation_text,
      true,
    );
    expect(window.localStorage.setItem).not.toHaveBeenCalled();
    expect(window.sessionStorage.setItem).not.toHaveBeenCalled();
    expect(screen.getByRole('button', { name: 'Connect Read-Only' })).toBeEnabled();
    expect(screen.getByRole('button', { name: 'Diagnostics' })).toBeDisabled();
    expect(screen.getByRole('button', { name: 'Start initial calibration' })).toBeDisabled();

    fireEvent.click(screen.getByRole('button', { name: 'Connect Read-Only' }));
    expect(await screen.findByText('Device Diagnostics')).toBeVisible();
    await waitFor(() => expect(screen.getByRole('button', { name: 'Diagnostics' })).toBeEnabled());
    expect(screen.getByRole('button', { name: 'Start initial calibration' })).toBeEnabled();
    expect(screen.getByRole('cell', { name: '2048' })).toBeVisible();

    fireEvent.click(screen.getByRole('button', { name: 'Diagnostics' }));
    await waitFor(() => expect(runDeviceDiagnostics).toHaveBeenCalledWith(
      'commissioning-memory-only-token',
    ));
    expect(screen.getByRole('button', { name: /Real Motion software Stop/ })).toBeDisabled();
  });

  it('shows an existing Calibration without adding its fingerprint to commissioning evidence', async () => {
    vi.mocked(getDeviceReadiness)
      .mockResolvedValueOnce(commissioningReadiness({ calibration_configured: true }))
      .mockResolvedValue(activeCommissioning(false, true));
    vi.mocked(createOperatorSession).mockResolvedValue({
      session_token: 'commissioning-memory-only-token',
      session_id: 'session-commissioning',
      issued_at: '2026-08-24T01:00:00Z',
      expires_at: '2099-01-01T00:00:00Z',
      purpose: 'COMMISSIONING_READ_ONLY',
      scopes: ['DIAGNOSTICS_READ', 'CALIBRATION_CAPTURE'],
      evidence: commissioningConfirmation,
    });

    render(<RealHardwarePanel />);

    expect(await screen.findByText('Calibration configured · Field acceptance pending')).toBeVisible();
    expect(screen.getByText('Calibration fingerprint').nextElementSibling)
      .toHaveTextContent('Not configured');
    await authorizeCommissioning();
    expect(screen.getByRole('button', { name: 'Start protected recalibration' })).toBeDisabled();
  });

  it('shows Real Motion as a separate, purpose-specific authorization state', async () => {
    vi.mocked(getDeviceReadiness).mockResolvedValue(readiness({
      state: 'AWAITING_OPERATOR_SESSION',
      session_authorizable: true,
      motion_session_authorizable: true,
      blocking_reasons: ['OPERATOR_SESSION_MISSING'],
    }));
    render(<RealHardwarePanel />);

    expect(await screen.findByText('Real Motion blocked')).toBeVisible();
    expect(screen.getByRole('button', { name: 'Authorize Real Motion' })).toBeEnabled();
    expect(screen.getByRole('button', { name: 'Connect Read-Only' })).toBeDisabled();
    expect(screen.getByRole('button', { name: 'Diagnostics' })).toBeDisabled();
  });

  it('shows stale Field Acceptance evidence as pending and keeps Real Motion blocked', async () => {
    vi.mocked(getDeviceReadiness).mockResolvedValue(readiness({
      state: 'BLOCKED_BY_FIELD_ACCEPTANCE',
      blocking_reasons: ['FIELD_ACCEPTANCE_EVIDENCE_STALE'],
    }));
    vi.mocked(getFieldAcceptanceStatus).mockResolvedValue({
      state: 'STALE',
      effective_status: 'PENDING',
      checklist_version: '1',
      stale_fields: ['calibration_fingerprint'],
      evidence_id: '33333333-3333-4333-8333-333333333333',
      accepted_at: '2026-08-24T00:00:00Z',
      accepted_by: 'operator',
      required_confirmation_text: 'I CONFIRM THE FIELD ACCEPTANCE CHECKLIST IS COMPLETE',
    });
    render(<RealHardwarePanel />);

    expect(await screen.findByText('STALE · PENDING')).toBeVisible();
    expect(screen.getByText('Field Acceptance evidence is stale · Real Motion blocked')).toBeVisible();
    expect(screen.getByText('calibration_fingerprint')).toBeVisible();
    expect(screen.getByRole('button', { name: /Real Motion software Stop/ })).toBeDisabled();
  });

  it('expires the in-memory commissioning token and closes every read-only entry', async () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date('2026-08-24T01:00:00Z'));
    vi.mocked(getDeviceReadiness)
      .mockResolvedValueOnce(commissioningReadiness())
      .mockResolvedValue(activeCommissioning(false));
    vi.mocked(createOperatorSession).mockResolvedValue({
      session_token: 'expiring-commissioning-token',
      session_id: 'session-commissioning',
      issued_at: '2026-08-24T01:00:00Z',
      expires_at: '2026-08-24T01:00:30Z',
      purpose: 'COMMISSIONING_READ_ONLY',
      scopes: ['DIAGNOSTICS_READ', 'CALIBRATION_CAPTURE'],
      evidence: commissioningConfirmation,
    });

    render(<RealHardwarePanel />);
    await act(async () => { await Promise.resolve(); });
    fireEvent.click(screen.getByRole('button', { name: 'Authorize READ ONLY' }));
    fireEvent.change(screen.getByLabelText(/Type the exact confirmation text/), {
      target: { value: commissioningConfirmation.required_confirmation_text },
    });
    fireEvent.click(screen.getByLabelText(/tested physical E-stop/));
    fireEvent.click(screen.getByRole('button', { name: 'Authorize READ ONLY session' }));
    await act(async () => { await Promise.resolve(); await Promise.resolve(); });
    expect(screen.getByRole('button', { name: 'Connect Read-Only' })).toBeEnabled();

    await act(async () => { vi.advanceTimersByTime(30_001); });
    expect(screen.getByText(/Operator Session expired/)).toBeVisible();
    expect(screen.getByRole('button', { name: 'Connect Read-Only' })).toBeDisabled();
    expect(screen.getByRole('button', { name: 'Diagnostics' })).toBeDisabled();
  });

  it('reconciles authoritative scopes even when Field Acceptance refresh fails', async () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date('2026-08-24T01:00:00Z'));
    const narrowedSession = activeCommissioning(false);
    if (narrowedSession.session) narrowedSession.session.scopes = ['DIAGNOSTICS_READ'];
    vi.mocked(getDeviceReadiness)
      .mockResolvedValueOnce(commissioningReadiness())
      .mockResolvedValueOnce(activeCommissioning(false))
      .mockResolvedValue(narrowedSession);
    vi.mocked(getFieldAcceptanceStatus)
      .mockResolvedValueOnce(pendingAcceptance)
      .mockResolvedValueOnce(pendingAcceptance)
      .mockRejectedValue(new Error('Field Acceptance refresh unavailable'));
    vi.mocked(createOperatorSession).mockResolvedValue({
      session_token: 'commissioning-memory-only-token',
      session_id: 'session-commissioning',
      issued_at: '2026-08-24T01:00:00Z',
      expires_at: '2099-01-01T00:00:00Z',
      purpose: 'COMMISSIONING_READ_ONLY',
      scopes: ['DIAGNOSTICS_READ', 'CALIBRATION_CAPTURE'],
      evidence: commissioningConfirmation,
    });

    render(<RealHardwarePanel />);
    await act(async () => { await Promise.resolve(); });
    fireEvent.click(screen.getByRole('button', { name: 'Authorize READ ONLY' }));
    fireEvent.change(screen.getByLabelText(/Type the exact confirmation text/), {
      target: { value: commissioningConfirmation.required_confirmation_text },
    });
    fireEvent.click(screen.getByLabelText(/tested physical E-stop/));
    fireEvent.click(screen.getByRole('button', { name: 'Authorize READ ONLY session' }));
    await act(async () => { await Promise.resolve(); await Promise.resolve(); });
    expect(screen.getByRole('button', { name: 'Connect Read-Only' })).toBeEnabled();

    await act(async () => {
      vi.advanceTimersByTime(15_001);
      await Promise.resolve();
      await Promise.resolve();
    });

    expect(screen.getByText('No token held by this page')).toBeVisible();
    expect(screen.getByText('Field Acceptance refresh unavailable')).toBeVisible();
    expect(screen.getByRole('button', { name: 'Connect Read-Only' })).toBeDisabled();
    expect(screen.getByRole('button', { name: 'Diagnostics' })).toBeDisabled();
  });
});
