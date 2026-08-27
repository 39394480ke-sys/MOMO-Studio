import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import {
  ApiError,
  armRawDirectionJoint,
  confirmRawDirectionDraft,
  getRawDirectionStatus,
  startRawDirectionSession,
  recordRawDirectionAlignment,
  stepRawDirectionJoint,
  stopRawDirectionTest,
} from '../../api/client';
import type { RawDirectionStatus } from '../../api/types';
import { RealSessionContext } from '../../components/realSessionContext';
import { realSessionFixture } from '../../test/realSessionFixtures';
import { RawDirectionPanel } from './RawDirectionPanel';

vi.mock('../../api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../../api/client')>();
  return {
    ...actual,
    armRawDirectionJoint: vi.fn(),
    confirmRawDirectionDraft: vi.fn(),
    getRawDirectionStatus: vi.fn(),
    heartbeatRawDirectionTest: vi.fn(),
    recordRawDirectionAlignment: vi.fn(),
    startRawDirectionSession: vi.fn(),
    stepRawDirectionJoint: vi.fn(),
    stopRawDirectionTest: vi.fn(),
  };
});

const sessionId = '11111111-1111-4111-8111-111111111111';
const commandId = '22222222-2222-4222-8222-222222222222';

function status(overrides: Partial<RawDirectionStatus> = {}): RawDirectionStatus {
  return {
    state: 'ZERO_CAPTURED',
    session_id: sessionId,
    active_joint_id: null,
    command_count: 0,
    session_expires_at: '2099-08-27T00:05:00Z',
    deadman_expires_at: null,
    zero_snapshot: {
      session_id: sessionId,
      robot_unit_id: 'MOMO-V2-UNIT-001',
      captured_at: '2026-08-27T00:00:00Z',
      raw_by_joint: { j10: 1851 },
    },
    last_observation: null,
    observations: [],
    calibration_draft: {
      robot_unit_id: 'MOMO-V2-UNIT-001',
      profile_fingerprint: 'a'.repeat(64),
      source: 'MOMO_RobotARM',
      source_revision: 'ff8bbda0c2222cb57951c7913f7f12f5777b98fa',
      complete_for_review: false,
      confirmed_for_review: false,
      confirmed_at: null,
      joints: [{
        joint_id: 'j10',
        servo_id: 10,
        home_present_raw: 1851,
        profile_direction_candidate: 1,
        matches_urdf: null,
        resolved_calibration_direction: null,
        phase_candidate: 28,
        raw_bounds_candidate: [-30719, 30719],
      }],
    },
    failure_reason: null,
    ...overrides,
  };
}

function renderPanel() {
  const context = realSessionFixture({
    session: {
      active: true,
      session_id: sessionId,
      expires_at: '2099-08-27T00:05:00Z',
      purpose: 'RAW_DIRECTION_TEST',
      scopes: ['RAW_DIRECTION_TEST'],
    },
    capabilities: {
      raw_direction_test: {
        ready: true,
        authorized: true,
        blocked_reasons: [],
        required_evidence: [],
      },
    },
  });
  return render(
    <RealSessionContext.Provider value={context}>
      <RawDirectionPanel />
    </RealSessionContext.Provider>,
  );
}

beforeEach(() => {
  vi.mocked(getRawDirectionStatus).mockResolvedValue(status());
  vi.mocked(stopRawDirectionTest).mockResolvedValue(status({ state: 'COMPLETED' }));
});

afterEach(() => {
  vi.clearAllMocks();
});

describe('Raw direction field panel', () => {
  it('sends one fixed Raw step for one explicit click', async () => {
    let releaseArm!: () => void;
    vi.mocked(armRawDirectionJoint).mockImplementation(() => new Promise((resolve) => {
      releaseArm = () => resolve(status({ state: 'ARMED', active_joint_id: 'j10' }));
    }));
    renderPanel();

    const rawPlus = await screen.findByRole('button', { name: '测试 J10 正方向' });
    fireEvent.click(rawPlus);
    await waitFor(() => expect(armRawDirectionJoint).toHaveBeenCalledWith('j10'));
    expect(stepRawDirectionJoint).not.toHaveBeenCalled();
    releaseArm();

    await waitFor(() => expect(stepRawDirectionJoint).toHaveBeenCalledWith('j10', 'RAW_PLUS'));
    expect(stopRawDirectionTest).not.toHaveBeenCalled();
  });

  it('does not expose an expired runtime from another operator session', async () => {
    vi.mocked(getRawDirectionStatus).mockResolvedValue(status({
      state: 'EXPIRED',
      session_id: '99999999-9999-4999-8999-999999999999',
      failure_reason: 'SESSION_EXPIRED',
    }));
    vi.mocked(startRawDirectionSession).mockResolvedValue(status());
    renderPanel();

    expect(await screen.findByRole('button', { name: '读取六轴零点并开始' })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: '测试 J10 正方向' })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: '读取六轴零点并开始' }));
    await waitFor(() => expect(startRawDirectionSession).toHaveBeenCalledTimes(1));
  });

  it('does not expose stale controls for a failed runtime in the current session', async () => {
    vi.mocked(getRawDirectionStatus).mockResolvedValue(status({
      state: 'FAILED',
      failure_reason: 'STEP_SETTLE_TIMEOUT',
    }));
    renderPanel();

    expect(await screen.findByRole('alert')).toHaveTextContent('上一次方向测试未完整结束');
    expect(screen.getByRole('button', { name: '读取六轴零点并开始' })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: '测试 J10 正方向' })).not.toBeInTheDocument();
  });

  it('requires zero recapture after a structured physical step failure', async () => {
    vi.mocked(armRawDirectionJoint).mockResolvedValue(
      status({ state: 'ARMED', active_joint_id: 'j10' }),
    );
    vi.mocked(stepRawDirectionJoint).mockRejectedValue(new ApiError({
      status: 409,
      code: 'RAW_DIRECTION_EXECUTION_FAILED',
      message: 'Raw direction step did not complete',
      details: {
        reason: 'STEP_SETTLE_TIMEOUT',
        target_raw: 2180,
        observed_raw: 2168,
        hold_requested: true,
      },
    }));
    renderPanel();

    fireEvent.click(await screen.findByRole('button', { name: '测试 J10 正方向' }));
    expect(await screen.findByRole('alert')).toHaveTextContent(
      '小步未完成，系统已请求保持（目标 Raw 2180，最后 Raw 2168）',
    );
    expect(screen.getByRole('button', { name: '读取六轴零点并开始' })).toBeInTheDocument();
    expect(screen.queryByText('实体方向是否与 URDF 动画一致？')).not.toBeInTheDocument();
  });

  it('requires both signs before offering one URDF judgment and final draft confirmation', async () => {
    const minus = {
      command_id: commandId,
      joint_id: 'j10',
      servo_id: 10,
      direction: 'RAW_MINUS' as const,
      zero_raw: 1851,
      start_raw: 1851,
      target_raw: 1843,
      final_raw: 1843,
      completed_at: '2026-08-27T00:01:00Z',
      software_only_adapter: true,
    };
    const plus = {
      ...minus,
      command_id: '33333333-3333-4333-8333-333333333333',
      direction: 'RAW_PLUS' as const,
      start_raw: 1843,
      target_raw: 1851,
      final_raw: 1851,
    };
    const readyForJudgment = status({
      observations: [minus, plus],
      last_observation: plus,
      calibration_draft: {
        ...status().calibration_draft!,
        complete_for_review: false,
      },
    });
    const complete = status({
      ...readyForJudgment,
      calibration_draft: {
        ...readyForJudgment.calibration_draft!,
        complete_for_review: true,
        joints: [{
          ...readyForJudgment.calibration_draft!.joints[0],
          matches_urdf: true,
          resolved_calibration_direction: 1,
        }],
      },
    });
    vi.mocked(getRawDirectionStatus).mockResolvedValue(readyForJudgment);
    vi.mocked(recordRawDirectionAlignment).mockResolvedValue(complete);
    vi.mocked(confirmRawDirectionDraft).mockResolvedValue(status({
      ...complete,
      calibration_draft: {
        ...complete.calibration_draft!,
        confirmed_for_review: true,
        confirmed_at: '2026-08-27T00:02:00Z',
      },
    }));
    renderPanel();

    expect(await screen.findByText('实体方向是否与 URDF 动画一致？')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: '一致，继续下一轴' }));
    await waitFor(() => expect(recordRawDirectionAlignment).toHaveBeenCalledWith('j10', true));
    fireEvent.click(await screen.findByRole('button', { name: '统一确认本次标定草稿' }));
    await waitFor(() => expect(confirmRawDirectionDraft).toHaveBeenCalledTimes(1));
  });
});
