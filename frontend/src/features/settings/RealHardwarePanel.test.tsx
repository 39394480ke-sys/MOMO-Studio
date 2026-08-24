import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import {
  connectRealDevice,
  createOperatorSession,
  disconnectRealDevice,
  getDeviceReadiness,
  revokeOperatorSession,
  runDeviceDiagnostics,
  stopRealDevice,
} from '../../api/client';
import type { DeviceDiagnostics, DeviceReadiness } from '../../api/types';
import { RealHardwarePanel } from './RealHardwarePanel';

vi.mock('../../api/client', () => ({
  ApiError: class ApiError extends Error {
    status = 500;
  },
  connectRealDevice: vi.fn(),
  createOperatorSession: vi.fn(),
  disconnectRealDevice: vi.fn(),
  getDeviceReadiness: vi.fn(),
  revokeOperatorSession: vi.fn(),
  runDeviceDiagnostics: vi.fn(),
  stopRealDevice: vi.fn(),
}));

const confirmation = {
  robot_id: 'primary',
  variant: 'V2' as const,
  profile_fingerprint: 'a'.repeat(64),
  calibration_fingerprint: 'b'.repeat(64),
  kinematics_fingerprint: 'c'.repeat(64),
  masked_serial_port: '/***USB0',
  masked_servo_ids: ['**1', '**2'],
  protocol: 'sts',
  physical_estop_required: true as const,
  required_confirmation_text: 'I UNDERSTAND REAL HARDWARE CAN MOVE',
};

function readiness(options: Partial<DeviceReadiness> = {}): DeviceReadiness {
  return {
    state: 'BLOCKED_BY_CONTROL_MODE',
    ready: false,
    session_authorizable: false,
    blocking_reasons: ['CONTROL_MODE_MUST_BE_REAL'],
    capabilities: {
      real_joint_motion_ready: false,
      real_cartesian_motion_ready: false,
      real_playback_ready: false,
      real_vision_follow_ready: false,
    },
    confirmation,
    session: null,
    connected: false,
    ...options,
  };
}

const diagnostics: DeviceDiagnostics = {
  connected: true,
  captured_at: '2026-08-24T01:02:03Z',
  dependency: {
    adapter_id: 'fake-servo-bus',
    state: 'AVAILABLE',
    package_name: null,
    license_status: 'TEST_ONLY',
    notice: 'Fake adapter',
  },
  hardware_policy: 'FULL',
  masked_serial_port: '/***USB0',
  masked_servo_ids: ['**1', '**2'],
  protocol: 'sts',
  profile: { configured: true, fingerprint: 'a'.repeat(64), verification_status: 'VERIFIED_FOR_REAL', template: false, ready_for_real: true },
  calibration: { configured: true, fingerprint: 'b'.repeat(64), verification_status: 'VERIFIED_FOR_REAL', template: false, ready_for_real: true },
  kinematics: { configured: true, fingerprint: 'c'.repeat(64), verification_status: 'VERIFIED_FOR_REAL', template: null, ready_for_real: true },
  field_acceptance: 'PASSED',
  readiness: 'READY',
  records: [{
    joint_id: 'j1',
    masked_servo_id: '**1',
    ping_responded: true,
    operating_mode: 'POSITION',
    present_raw: 2048,
    logical_value: 0,
    raw_bounds: [0, 4095],
    torque_enabled: false,
  }],
  last_error: null,
};

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
  vi.mocked(revokeOperatorSession).mockReset();
  vi.mocked(runDeviceDiagnostics).mockReset();
  vi.mocked(stopRealDevice).mockReset();
  Object.defineProperty(window, 'localStorage', {
    configurable: true,
    value: memoryStorageSpy(),
  });
  Object.defineProperty(window, 'sessionStorage', {
    configurable: true,
    value: memoryStorageSpy(),
  });
});

afterEach(() => {
  vi.useRealTimers();
});

describe('RealHardwarePanel', () => {
  it('renders blocking evidence without claiming false readiness or probing a device', async () => {
    vi.mocked(getDeviceReadiness).mockResolvedValue(readiness());
    render(<RealHardwarePanel />);

    expect(await screen.findByText('Hardware access disabled')).toBeVisible();
    expect(screen.getByText('CONTROL_MODE_MUST_BE_REAL')).toBeVisible();
    expect(screen.queryByText('Backend Ready')).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Authorize' })).toBeDisabled();
    expect(screen.getByRole('button', { name: /Global software Stop/ })).toBeEnabled();
    expect(connectRealDevice).not.toHaveBeenCalled();
    expect(runDeviceDiagnostics).not.toHaveBeenCalled();
  });

  it('requires exact confirmation and E-stop evidence before keeping a token in memory', async () => {
    vi.mocked(getDeviceReadiness)
      .mockResolvedValueOnce(readiness({
        state: 'AWAITING_OPERATOR_SESSION',
        session_authorizable: true,
        blocking_reasons: ['OPERATOR_SESSION_MISSING'],
      }))
      .mockResolvedValue(readiness({
        state: 'READY',
        ready: true,
        session_authorizable: false,
        blocking_reasons: [],
        session: { active: true, session_id: 'session-1', expires_at: '2099-01-01T00:00:00Z' },
      }));
    vi.mocked(createOperatorSession).mockResolvedValue({
      session_token: 'memory-only-token',
      session_id: 'session-1',
      issued_at: '2026-08-24T01:00:00Z',
      expires_at: '2099-01-01T00:00:00Z',
      evidence: confirmation,
    });

    render(<RealHardwarePanel />);
    fireEvent.click(await screen.findByRole('button', { name: 'Authorize' }));

    const confirmButton = screen.getByRole('button', { name: 'Authorize for this session' });
    expect(confirmButton).toBeDisabled();
    fireEvent.change(screen.getByLabelText(/Type the exact confirmation text/), {
      target: { value: confirmation.required_confirmation_text },
    });
    expect(confirmButton).toBeDisabled();
    fireEvent.click(screen.getByLabelText(/tested physical E-stop/));
    expect(confirmButton).toBeEnabled();
    fireEvent.click(confirmButton);

    await waitFor(() => expect(createOperatorSession).toHaveBeenCalledWith(
      confirmation.required_confirmation_text,
      true,
    ));
    expect(await screen.findByText(/Expires at/)).toBeVisible();
    expect(window.localStorage.setItem).not.toHaveBeenCalled();
    expect(window.sessionStorage.setItem).not.toHaveBeenCalled();
  });

  it('runs diagnostics only after authorization and renders bounded Servo evidence', async () => {
    vi.mocked(getDeviceReadiness)
      .mockResolvedValueOnce(readiness({
        state: 'AWAITING_OPERATOR_SESSION',
        session_authorizable: true,
        blocking_reasons: ['OPERATOR_SESSION_MISSING'],
      }))
      .mockResolvedValue(readiness({
        state: 'READY',
        ready: true,
        blocking_reasons: [],
        session: { active: true, session_id: 'session-2', expires_at: '2099-01-01T00:00:00Z' },
      }));
    vi.mocked(createOperatorSession).mockResolvedValue({
      session_token: 'diagnostic-token',
      session_id: 'session-2',
      issued_at: '2026-08-24T01:00:00Z',
      expires_at: '2099-01-01T00:00:00Z',
      evidence: confirmation,
    });
    vi.mocked(runDeviceDiagnostics).mockResolvedValue(diagnostics);

    render(<RealHardwarePanel />);
    fireEvent.click(await screen.findByRole('button', { name: 'Authorize' }));
    fireEvent.change(screen.getByLabelText(/Type the exact confirmation text/), {
      target: { value: confirmation.required_confirmation_text },
    });
    fireEvent.click(screen.getByLabelText(/tested physical E-stop/));
    fireEvent.click(screen.getByRole('button', { name: 'Authorize for this session' }));
    await screen.findByText(/Expires at/);

    fireEvent.click(screen.getByRole('button', { name: /Read diagnostics/ }));
    expect(await screen.findByText('Device Diagnostics')).toBeVisible();
    expect(screen.getByRole('cell', { name: '2048' })).toBeVisible();
    expect(screen.getByRole('cell', { name: '**1' })).toBeVisible();
    expect(runDeviceDiagnostics).toHaveBeenCalledWith('diagnostic-token');
  });

  it('expires the in-memory token and disables diagnostics', async () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date('2026-08-24T01:00:00Z'));
    vi.mocked(getDeviceReadiness)
      .mockResolvedValueOnce(readiness({
        state: 'AWAITING_OPERATOR_SESSION',
        session_authorizable: true,
        blocking_reasons: ['OPERATOR_SESSION_MISSING'],
      }))
      .mockResolvedValue(readiness({ state: 'READY', ready: true, blocking_reasons: [] }));
    vi.mocked(createOperatorSession).mockResolvedValue({
      session_token: 'expiring-token',
      session_id: 'session-3',
      issued_at: '2026-08-24T01:00:00Z',
      expires_at: '2026-08-24T01:00:30Z',
      evidence: confirmation,
    });

    render(<RealHardwarePanel />);
    await act(async () => { await Promise.resolve(); });
    fireEvent.click(screen.getByRole('button', { name: 'Authorize' }));
    fireEvent.change(screen.getByLabelText(/Type the exact confirmation text/), {
      target: { value: confirmation.required_confirmation_text },
    });
    fireEvent.click(screen.getByLabelText(/tested physical E-stop/));
    fireEvent.click(screen.getByRole('button', { name: 'Authorize for this session' }));
    await act(async () => { await Promise.resolve(); await Promise.resolve(); });
    expect(screen.getByRole('button', { name: /Read diagnostics/ })).toBeEnabled();

    await act(async () => { vi.advanceTimersByTime(30_001); });
    expect(screen.getByText(/Operator Session expired/)).toBeVisible();
    expect(screen.getByRole('button', { name: /Read diagnostics/ })).toBeDisabled();
    expect(runDeviceDiagnostics).not.toHaveBeenCalled();
  });
});
