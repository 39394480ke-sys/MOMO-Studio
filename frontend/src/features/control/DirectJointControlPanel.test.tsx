import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import {
  directCommissioningStep,
  getCommissioningDirectJointState,
  getForwardKinematicsForState,
  getCommissioningMotionStatus,
  heartbeatCommissioningDirectJog,
  startCommissioningDirectJog,
  startCommissioningMotionSession,
  stopCommissioningDirectJog,
} from '../../api/client';
import type {
  CommissioningDirectControlResponse,
  CommissioningMotionStatus,
} from '../../api/types';
import { useRealSession, type RealSessionContextValue } from '../../components/realSessionContext';
import { useRuntimeStatus, type RuntimeStatus } from '../../components/runtimeStatusContext';
import { v2Profile } from '../../test/stage3Fixtures';
import { DirectJointControlPanel } from './DirectJointControlPanel';

vi.mock('../../api/client', () => ({
  directCommissioningStep: vi.fn(),
  getCommissioningDirectJointState: vi.fn(),
  getForwardKinematicsForState: vi.fn(),
  getCommissioningMotionStatus: vi.fn(),
  heartbeatCommissioningDirectJog: vi.fn(),
  startCommissioningDirectJog: vi.fn(),
  startCommissioningMotionSession: vi.fn(),
  stopCommissioningDirectJog: vi.fn(),
  moveCommissioningDirectJoints: vi.fn(),
  solveInverseKinematics: vi.fn(),
}));

vi.mock('../../components/realSessionContext', async (importOriginal) => {
  const original = await importOriginal<typeof import('../../components/realSessionContext')>();
  return { ...original, useRealSession: vi.fn() };
});

vi.mock('../../components/runtimeStatusContext', async (importOriginal) => {
  const original = await importOriginal<typeof import('../../components/runtimeStatusContext')>();
  return { ...original, useRuntimeStatus: vi.fn() };
});

const authorizedStatus: CommissioningMotionStatus = {
  state: 'AUTHORIZED',
  session_id: '22222222-2222-4222-8222-222222222222',
  active_joint_id: null,
  command_count: 0,
  session_expires_at: '2099-01-01T00:00:00Z',
  deadman_expires_at: null,
  last_evidence_id: null,
  failure_reason: null,
  physical_stop_verification: 'PENDING',
};

const directStatus: CommissioningDirectControlResponse = {
  running: false,
  mode: 'STEP',
  joint_id: 'j10',
  direction: 1,
  requested_speed: 1,
  logical_position: 1,
  raw_position: 64,
  target_value: 1,
  message: 'Step target was written',
};

const controlLevels = [
  { index: 0, label: '低', step: 0.5, speed: 1 },
  { index: 1, label: '中低', step: 1, speed: 5 },
  { index: 2, label: '中', step: 1.5, speed: 10 },
  { index: 3, label: '高', step: 2, speed: 25 },
  { index: 4, label: '极高', step: 3, speed: 50 },
];

function runtime(): RuntimeStatus {
  return {
    backend: 'connected',
    stale: false,
    controlMode: 'REAL',
    hardwareAccessPolicy: 'FULL',
    realMotionEnabled: false,
    meta: null,
    robot: null,
    profile: {
      profile: v2Profile,
      fingerprint: 'a'.repeat(64),
      kinematics_fingerprint: 'b'.repeat(64),
      real_eligible: false,
    } as RuntimeStatus['profile'],
    calibration: null,
    diagnostics: null,
    error: null,
    refresh: vi.fn(),
    connect: vi.fn(),
    disconnect: vi.fn(),
    stop: vi.fn(),
    switchVariant: vi.fn(),
    pendingAction: null,
  };
}

function sessionContext(active: boolean): RealSessionContextValue {
  return {
    summary: {
      readiness: null,
      session: active ? {
        active: true,
        session_id: authorizedStatus.session_id!,
        expires_at: authorizedStatus.session_expires_at!,
        purpose: 'COMMISSIONING_MOTION_TEST',
        scopes: ['COMMISSIONING_SINGLE_JOINT_TEST'],
      } : null,
      capabilityDetails: {
        commissioning_read_only: { ready: false, authorized: false, blocked_reasons: [], required_evidence: [] },
        commissioning_motion_test: { ready: active, authorized: active, blocked_reasons: [], required_evidence: [] },
        raw_direction_test: { ready: false, authorized: false, blocked_reasons: [], required_evidence: [] },
        real_joint_motion: { ready: false, authorized: false, blocked_reasons: [], required_evidence: [] },
        real_cartesian_motion: { ready: false, authorized: false, blocked_reasons: [], required_evidence: [] },
        real_playback: { ready: false, authorized: false, blocked_reasons: [], required_evidence: [] },
        real_vision_follow: { ready: false, authorized: false, blocked_reasons: [], required_evidence: [] },
      },
      authorizationOptions: [{
        purpose: 'COMMISSIONING_MOTION_TEST',
        authorizable: !active,
        confirmation: {
          robot_id: 'primary',
          robot_unit_id: 'MOMO-V2-UNIT-001',
          variant: 'V2',
          profile_fingerprint: 'a'.repeat(64),
          calibration_fingerprint: 'b'.repeat(64),
          kinematics_fingerprint: null,
          field_acceptance_evidence_id: null,
          masked_serial_port: '/***13871',
          masked_servo_ids: ['**0'],
          protocol: 'STS3215',
          session_purpose: 'COMMISSIONING_MOTION_TEST',
          physical_estop_required: true,
          workspace_clear_required: true,
          required_confirmation_text: 'I UNDERSTAND THIS IS A SINGLE-JOINT MOTION TEST',
        },
      }],
      loading: false,
      stale: false,
      error: null,
      updatedAt: null,
    },
    pendingAction: null,
    authorize: vi.fn().mockResolvedValue({}),
    revoke: vi.fn(),
    refresh: vi.fn(),
  };
}

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(useRuntimeStatus).mockReturnValue(runtime());
  vi.mocked(getCommissioningMotionStatus).mockResolvedValue(authorizedStatus);
  vi.mocked(startCommissioningMotionSession).mockResolvedValue(authorizedStatus);
  vi.mocked(getCommissioningDirectJointState).mockResolvedValue({
    positions: { j10: 0, j11: 0, j12: 0, j13: 0, j14: 0, j15: 0 },
    units: { j10: 'mm', j11: 'deg', j12: 'deg', j13: 'deg', j14: 'deg', j15: 'deg' },
    raw_positions: { j10: 1000, j11: 1000, j12: 1000, j13: 1000, j14: 1000, j15: 1000 },
    captured_at: '2099-01-01T00:00:00Z',
    moving: false,
    message: 'Read six joints',
  });
  vi.mocked(getForwardKinematicsForState).mockResolvedValue({
    robot_id: 'primary',
    variant: 'V2',
    tcp_pose: {
      frame: 'base',
      position_mm: { x: 100, y: 200, z: 300 },
      orientation_quaternion_xyzw: { x: 0, y: 0, z: 0, w: 1 },
    },
    state_sequence: 1,
    profile_fingerprint: 'a'.repeat(64),
    kinematics_fingerprint: 'b'.repeat(64),
    hardware_accessed: false,
  });
  vi.mocked(directCommissioningStep).mockResolvedValue(directStatus);
  vi.mocked(startCommissioningDirectJog).mockResolvedValue({
    ...directStatus,
    running: true,
    mode: 'CONTINUOUS',
  });
  vi.mocked(heartbeatCommissioningDirectJog).mockResolvedValue({
    ...directStatus,
    running: true,
    mode: 'CONTINUOUS',
  });
  vi.mocked(stopCommissioningDirectJog).mockResolvedValue({
    ...directStatus,
    running: false,
    mode: 'CONTINUOUS',
    message: '已请求停止并保持当前位置; 舵机仍连接并保持扭矩。',
  });
});

describe('DirectJointControlPanel', () => {
  it('uses one explicit click to create and start the bounded control session', async () => {
    const context = sessionContext(false);
    vi.mocked(useRealSession).mockReturnValue(context);
    render(<DirectJointControlPanel />);

    fireEvent.click(screen.getByRole('button', { name: '急停已就位，开始直接控制' }));

    await waitFor(() => expect(context.authorize).toHaveBeenCalledWith(
      'COMMISSIONING_MOTION_TEST',
      'I UNDERSTAND THIS IS A SINGLE-JOINT MOTION TEST',
      true,
      true,
    ));
    expect(startCommissioningMotionSession).toHaveBeenCalledTimes(1);
  });

  it('uses the high control level by default for a direct J10 step', async () => {
    vi.mocked(useRealSession).mockReturnValue(sessionContext(true));
    render(<DirectJointControlPanel />);
    await waitFor(() => expect(getCommissioningMotionStatus).toHaveBeenCalled());

    fireEvent.click(screen.getByRole('button', { name: 'J10 正方向' }));
    await waitFor(() => expect(directCommissioningStep).toHaveBeenCalledWith('j10', 2, 25));

    fireEvent.click(screen.getByRole('button', { name: '停止并保持（不断开）' }));
    await waitFor(() => expect(stopCommissioningDirectJog).toHaveBeenCalledWith(false));
    expect(await screen.findByText(/已请求停止并保持当前位置/)).toBeInTheDocument();
  });

  it('starts continuous movement on pointerdown and stops on pointerup', async () => {
    vi.mocked(useRealSession).mockReturnValue(sessionContext(true));
    render(<DirectJointControlPanel />);
    await waitFor(() => expect(getCommissioningMotionStatus).toHaveBeenCalled());

    fireEvent.click(screen.getByRole('button', { name: '连续模式' }));
    expect(screen.getByText(/连续：按住速度 25/)).toBeInTheDocument();
    const button = screen.getByRole('button', { name: 'J11 正方向' });
    fireEvent.pointerDown(button, { pointerId: 7 });
    await waitFor(() => expect(startCommissioningDirectJog).toHaveBeenCalledWith('j11', 1, 25));
    fireEvent.pointerUp(button, { pointerId: 7 });
    await waitFor(() => expect(stopCommissioningDirectJog).toHaveBeenCalledWith(false));
  });

  it('shows an explicit idle result when Stop has nothing active to disconnect', async () => {
    vi.mocked(useRealSession).mockReturnValue(sessionContext(true));
    vi.mocked(stopCommissioningDirectJog).mockResolvedValue({
      running: false,
      mode: 'IDLE',
      joint_id: null,
      direction: null,
      requested_speed: null,
      logical_position: null,
      raw_position: null,
      target_value: null,
      message: '直接控制空闲; 当前没有运动, 连接状态未改变。',
    });
    render(<DirectJointControlPanel />);
    await waitFor(() => expect(getCommissioningMotionStatus).toHaveBeenCalled());

    fireEvent.click(screen.getByRole('button', { name: '停止并保持（不断开）' }));

    expect(await screen.findByText(/当前没有运动, 连接状态未改变/)).toBeInTheDocument();
  });

  it('does not present the commissioning evidence count as a direct-control limit', async () => {
    vi.mocked(useRealSession).mockReturnValue(sessionContext(true));
    vi.mocked(getCommissioningMotionStatus).mockResolvedValue({
      ...authorizedStatus,
      command_count: 24,
    });
    render(<DirectJointControlPanel />);

    await waitFor(() => expect(getCommissioningMotionStatus).toHaveBeenCalled());
    expect(screen.queryByText(/24\/120/)).not.toBeInTheDocument();
  });

  it('keeps the page rendered while a joint target is edited', async () => {
    vi.mocked(useRealSession).mockReturnValue(sessionContext(true));
    render(<DirectJointControlPanel />);

    const input = await screen.findByRole('spinbutton', { name: 'J10 · mm' });
    await waitFor(() => expect(input).toBeEnabled());
    fireEvent.change(input, { target: { value: '' } });

    expect(screen.getByRole('heading', { name: '整组关节与 Home' })).toBeVisible();
    expect(screen.getByRole('button', { name: '移动全部关节' })).toBeDisabled();

    fireEvent.change(input, { target: { value: '12.5' } });

    expect(input).toHaveValue(12.5);
    expect(screen.getByRole('button', { name: '移动全部关节' })).toBeEnabled();
  });

  it.each(controlLevels)(
    'maps the $label level to a $step-unit step at speed $speed',
    async ({ index, label, step, speed }) => {
      vi.mocked(useRealSession).mockReturnValue(sessionContext(true));
      render(<DirectJointControlPanel />);
      await waitFor(() => expect(getCommissioningMotionStatus).toHaveBeenCalled());

      const slider = screen.getByRole('slider', { name: '控制档位' });
      fireEvent.change(slider, { target: { value: String(index) } });
      expect(slider).toHaveAttribute('aria-valuetext', `${label}档`);

      fireEvent.click(screen.getByRole('button', { name: 'J10 正方向' }));
      await waitFor(() => expect(directCommissioningStep).toHaveBeenCalledWith(
        'j10', step, speed,
      ));
    },
  );

  it.each(controlLevels)(
    'maps the $label level to continuous speed $speed',
    async ({ index, label, speed }) => {
      vi.mocked(useRealSession).mockReturnValue(sessionContext(true));
      render(<DirectJointControlPanel />);
      await waitFor(() => expect(getCommissioningMotionStatus).toHaveBeenCalled());

      const slider = screen.getByRole('slider', { name: '控制档位' });
      fireEvent.change(slider, { target: { value: String(index) } });
      fireEvent.click(screen.getByRole('button', { name: '连续模式' }));
      expect(slider).toHaveAttribute('aria-valuetext', `${label}档`);

      const button = screen.getByRole('button', { name: 'J11 正方向' });
      fireEvent.pointerDown(button, { pointerId: index + 10 });
      await waitFor(() => expect(startCommissioningDirectJog).toHaveBeenCalledWith(
        'j11', 1, speed,
      ));
      fireEvent.pointerUp(button, { pointerId: index + 10 });
    },
  );

  it('keeps one level across modes and renders domain-specific units', async () => {
    vi.mocked(useRealSession).mockReturnValue(sessionContext(true));
    render(<DirectJointControlPanel />);
    await waitFor(() => expect(getCommissioningMotionStatus).toHaveBeenCalled());

    const slider = screen.getByRole('slider', { name: '控制档位' });
    fireEvent.change(slider, { target: { value: '2' } });
    expect(screen.getByText('1.5 mm · 10 mm/s')).toBeVisible();
    expect(screen.getAllByText('1.5 deg · 10 deg/s')).toHaveLength(5);

    fireEvent.click(screen.getByRole('button', { name: '连续模式' }));
    expect((slider as HTMLInputElement).value).toBe('2');
    expect(screen.getByText('10 mm/s')).toBeVisible();
    expect(screen.getAllByText('10 deg/s')).toHaveLength(5);
  });

  it('supports keyboard arrow adjustment for the discrete slider', async () => {
    const user = userEvent.setup();
    vi.mocked(useRealSession).mockReturnValue(sessionContext(true));
    render(<DirectJointControlPanel />);
    await waitFor(() => expect(getCommissioningMotionStatus).toHaveBeenCalled());

    const slider = screen.getByRole('slider', { name: '控制档位' });
    await user.click(slider);
    await user.keyboard('{ArrowLeft}');

    expect((slider as HTMLInputElement).value).toBe('2');
    expect(slider).toHaveAttribute('aria-valuetext', '中档');
  });

  it('locks the level during continuous motion and restores it after release', async () => {
    vi.mocked(useRealSession).mockReturnValue(sessionContext(true));
    render(<DirectJointControlPanel />);
    await waitFor(() => expect(getCommissioningMotionStatus).toHaveBeenCalled());

    const slider = screen.getByRole('slider', { name: '控制档位' });
    fireEvent.click(screen.getByRole('button', { name: '连续模式' }));
    const button = screen.getByRole('button', { name: 'J11 正方向' });
    fireEvent.pointerDown(button, { pointerId: 91 });
    await waitFor(() => expect(slider).toBeDisabled());

    fireEvent.pointerUp(button, { pointerId: 91 });
    await waitFor(() => expect(slider).toBeEnabled());
  });

  it('resets to high on remount without using browser storage', async () => {
    const storageRead = vi.spyOn(Storage.prototype, 'getItem');
    const storageWrite = vi.spyOn(Storage.prototype, 'setItem');
    vi.mocked(useRealSession).mockReturnValue(sessionContext(true));
    const first = render(<DirectJointControlPanel />);
    await waitFor(() => expect(getCommissioningMotionStatus).toHaveBeenCalled());

    fireEvent.change(screen.getByRole('slider', { name: '控制档位' }), {
      target: { value: '0' },
    });
    first.unmount();
    render(<DirectJointControlPanel />);

    const slider = screen.getByRole('slider', { name: '控制档位' });
    expect((slider as HTMLInputElement).value).toBe('3');
    expect(slider).toHaveAttribute('aria-valuetext', '高档');
    expect(storageRead).not.toHaveBeenCalled();
    expect(storageWrite).not.toHaveBeenCalled();
  });
});
