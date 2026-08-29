import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import {
  directCommissioningStep,
  getCommissioningDirectJointState,
  getCommissioningMotionStatus,
  getForwardKinematicsForState,
  heartbeatCommissioningDirectJog,
  moveCommissioningDirectJoints,
  solveInverseKinematics,
  startCommissioningDirectJog,
  startCommissioningMotionSession,
  stopCommissioningDirectJog,
} from '../../api/client';
import type {
  CommissioningDirectControlResponse,
  CommissioningDirectJointMoveResponse,
  CommissioningDirectJointStateResponse,
  CommissioningMotionStatus,
  ForwardKinematicsResponse,
  InverseKinematicsResponse,
} from '../../api/types';
import { useRealSession, type RealSessionContextValue } from '../../components/realSessionContext';
import { useRuntimeStatus, type RuntimeStatus } from '../../components/runtimeStatusContext';
import { robotFor, v2Profile } from '../../test/stage3Fixtures';
import { CommissioningControlAdapter } from './CommissioningControlAdapter';

vi.mock('../../api/client', () => ({
  directCommissioningStep: vi.fn(),
  getCommissioningDirectJointState: vi.fn(),
  getForwardKinematicsForState: vi.fn(),
  getCommissioningMotionStatus: vi.fn(),
  heartbeatCommissioningDirectJog: vi.fn(),
  moveCommissioningDirectJoints: vi.fn(),
  solveInverseKinematics: vi.fn(),
  startCommissioningDirectJog: vi.fn(),
  startCommissioningMotionSession: vi.fn(),
  stopCommissioningDirectJog: vi.fn(),
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

const jointState: CommissioningDirectJointStateResponse = {
  positions: { j10: 0, j11: 0, j12: 0, j13: 0, j14: 0, j15: 0 },
  units: { j10: 'mm', j11: 'deg', j12: 'deg', j13: 'deg', j14: 'deg', j15: 'deg' },
  raw_positions: { j10: 1000, j11: 1000, j12: 1000, j13: 1000, j14: 1000, j15: 1000 },
  captured_at: '2099-01-01T00:00:00Z',
  moving: false,
  message: 'Read six joints',
};

const fkResponse: ForwardKinematicsResponse = {
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
};

const moveResponse: CommissioningDirectJointMoveResponse = {
  positions: jointState.positions,
  units: jointState.units,
  raw_positions: jointState.raw_positions,
  duration_s: 1,
  frame_count: 20,
  completed: true,
  message: jointState.message,
};

const ikResponse: InverseKinematicsResponse = {
  success: true,
  joint_state_optional: { positions: jointState.positions, units: jointState.units },
  best_joint_state: { positions: jointState.positions, units: jointState.units },
  iterations: 3,
  position_error_mm: 0.01,
  orientation_error_deg: 0.01,
  termination_reason: 'CONVERGED',
  warnings: [],
  kinematics_fingerprint: 'b'.repeat(64),
};

function runtime(): RuntimeStatus {
  return {
    backend: 'connected',
    stale: false,
    controlMode: 'REAL',
    hardwareAccessPolicy: 'FULL',
    realMotionEnabled: false,
    meta: null,
    robot: {
      ...robotFor('V2', false),
      control_mode: 'REAL',
      hardware_access_policy: 'FULL',
    } as RuntimeStatus['robot'],
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
    revoke: vi.fn().mockResolvedValue(undefined),
    refresh: vi.fn().mockResolvedValue(undefined),
  };
}

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(useRuntimeStatus).mockReturnValue(runtime());
  vi.mocked(getCommissioningMotionStatus).mockResolvedValue(authorizedStatus);
  vi.mocked(startCommissioningMotionSession).mockResolvedValue(authorizedStatus);
  vi.mocked(getCommissioningDirectJointState).mockResolvedValue(jointState);
  vi.mocked(getForwardKinematicsForState).mockResolvedValue(fkResponse);
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
  });
  vi.mocked(moveCommissioningDirectJoints).mockResolvedValue(moveResponse);
  vi.mocked(solveInverseKinematics).mockResolvedValue(ikResponse);
});

describe('CommissioningControlAdapter', () => {
  it('renders only the shared product UI and requires an explicit authorization click', async () => {
    const context = sessionContext(false);
    vi.mocked(useRealSession).mockReturnValue(context);
    render(<CommissioningControlAdapter />);

    expect(screen.getByRole('region', { name: '机械臂预览' })).toBeVisible();
    expect(screen.getByRole('region', { name: '运动控制' })).toBeVisible();
    expect(screen.queryByRole('heading', { name: '单关节直接控制' })).not.toBeInTheDocument();

    await userEvent.click(screen.getByRole('button', { name: '启用真机控制' }));
    await waitFor(() => expect(context.authorize).toHaveBeenCalledWith(
      'COMMISSIONING_MOTION_TEST',
      'I UNDERSTAND THIS IS A SINGLE-JOINT MOTION TEST',
      true,
      true,
    ));
    expect(startCommissioningMotionSession).toHaveBeenCalledTimes(1);
  });

  it('maps the shared speed selector and Joint controls to the verified direct adapter', async () => {
    vi.mocked(useRealSession).mockReturnValue(sessionContext(true));
    render(<CommissioningControlAdapter />);
    const step = await screen.findByRole('button', { name: 'Step J10 positive' });
    await waitFor(() => expect(step).toBeEnabled());

    fireEvent.pointerDown(step, { pointerId: 1 });
    fireEvent.pointerUp(step, { pointerId: 1 });
    await waitFor(() => expect(directCommissioningStep).toHaveBeenCalledWith('j10', 5, 20));

    const speedGroup = screen.getByRole('radiogroup', { name: '共享速度档位' });
    fireEvent.click(within(speedGroup).getByRole('radio', { name: '速度 5：极高' }));
    fireEvent.pointerDown(step, { pointerId: 2 });
    fireEvent.pointerUp(step, { pointerId: 2 });
    await waitFor(() => expect(directCommissioningStep).toHaveBeenLastCalledWith('j10', 15, 50));
  });

  it('routes grouped targets, Home, Cartesian IK, and Stop through commissioning APIs', async () => {
    vi.mocked(useRealSession).mockReturnValue(sessionContext(true));
    render(<CommissioningControlAdapter />);
    const move = await screen.findByRole('button', { name: '移动全部关节' });
    await waitFor(() => expect(move).toBeEnabled());

    fireEvent.change(screen.getByLabelText('J10 target (mm)'), { target: { value: '12.5' } });
    fireEvent.click(move);
    await waitFor(() => expect(moveCommissioningDirectJoints).toHaveBeenCalledWith(
      { ...jointState.positions, j10: 12.5 },
      1,
    ));

    fireEvent.click(screen.getByRole('button', { name: 'Cartesian' }));
    const solve = screen.getByRole('button', { name: '检查逆解' });
    await waitFor(() => expect(solve).toBeEnabled());
    fireEvent.click(solve);
    await waitFor(() => expect(solveInverseKinematics).toHaveBeenCalledTimes(1));

    fireEvent.click(screen.getByRole('button', { name: '停止运动（面板）' }));
    await waitFor(() => expect(stopCommissioningDirectJog).toHaveBeenCalledWith(false));
  });

  it('starts, heartbeats, and stops a continuous commissioning jog through the shared hold button', async () => {
    vi.mocked(useRealSession).mockReturnValue(sessionContext(true));
    render(<CommissioningControlAdapter />);
    const hold = await screen.findByRole('button', { name: 'Step J11 negative' });
    await waitFor(() => expect(hold).toBeEnabled());

    fireEvent.pointerDown(hold, { pointerId: 8 });
    await waitFor(() => expect(startCommissioningDirectJog).toHaveBeenCalledWith('j11', -1, 12));
    await waitFor(() => expect(heartbeatCommissioningDirectJog).toHaveBeenCalled(), { timeout: 600 });
    fireEvent.pointerUp(hold, { pointerId: 8 });

    await waitFor(() => expect(stopCommissioningDirectJog).toHaveBeenCalledWith(false));
  });

  it('fails a continuous commissioning jog safe on window blur', async () => {
    vi.mocked(useRealSession).mockReturnValue(sessionContext(true));
    render(<CommissioningControlAdapter />);
    const hold = await screen.findByRole('button', { name: 'Step J12 positive' });
    await waitFor(() => expect(hold).toBeEnabled());

    fireEvent.pointerDown(hold, { pointerId: 9 });
    await waitFor(() => expect(startCommissioningDirectJog).toHaveBeenCalled());
    fireEvent.blur(window);

    await waitFor(() => expect(stopCommissioningDirectJog).toHaveBeenCalledWith(false));
  });

  it('explicitly stops before revoking a commissioning control session', async () => {
    const context = sessionContext(true);
    vi.mocked(useRealSession).mockReturnValue(context);
    render(<CommissioningControlAdapter />);
    const end = await screen.findByRole('button', { name: '结束控制' });

    fireEvent.click(end);

    await waitFor(() => expect(stopCommissioningDirectJog).toHaveBeenCalledWith(false));
    expect(context.revoke).toHaveBeenCalledTimes(1);
    expect(context.refresh).toHaveBeenCalledTimes(1);
  });
});
