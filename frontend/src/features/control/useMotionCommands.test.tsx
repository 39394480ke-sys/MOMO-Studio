import { act, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import type { JointJogStepRequest } from '../../api/types';
import { preflight, stage3Ids } from '../../test/stage3Fixtures';
import { useMotionCommands } from './useMotionCommands';

const request: JointJogStepRequest = {
  source: 'CONTROL',
  expected_state_sequence: 7,
  expected_profile_fingerprint: stage3Ids.profileFingerprint,
  expected_kinematics_fingerprint: stage3Ids.kinematicsFingerprint,
  speed_scale: 0.5,
  idempotency_key: 'poll-budget-test',
  joint_id: 'j11',
  delta: 1,
  unit: 'deg',
  duration_s: 0.25,
};

function jsonResponse(body: unknown, ok = true, status = ok ? 200 : 500): Response {
  return {
    ok,
    status,
    json: vi.fn().mockResolvedValue(body),
  } as unknown as Response;
}

function PollHarness() {
  const motion = useMotionCommands({
    socketCommand: null,
    refreshRuntime: vi.fn().mockResolvedValue(undefined),
  });
  return (
    <div>
      <button onClick={() => void motion.jogStep(request)} type="button">Start</button>
      <span>{motion.command?.state ?? 'IDLE'}</span>
      <p>{motion.error}</p>
    </div>
  );
}

function mockPolling(mode: 'error' | 'running') {
  let statusRequests = 0;
  vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL) => {
    const path = String(input);
    if (path.endsWith('/motion/jog-step')) {
      return jsonResponse({
        command_id: stage3Ids.commandId,
        status: 'ACCEPTED',
        preflight,
      }, true, 202);
    }
    if (path.includes('/motion/commands/')) {
      statusRequests += 1;
      if (mode === 'error') {
        return jsonResponse({
          code: 'STATUS_UNAVAILABLE',
          message: 'Command status unavailable',
          details: {},
        }, false, 503);
      }
      return jsonResponse({
        command_id: stage3Ids.commandId,
        state: 'RUNNING',
        progress: 0.5,
        preflight,
        error: null,
        hardware_accessed: false,
      });
    }
    throw new Error(`Unhandled ${path}`);
  }));
  return () => statusRequests;
}

async function startCommand() {
  await act(async () => {
    fireEvent.click(screen.getByRole('button', { name: 'Start' }));
    await Promise.resolve();
    await Promise.resolve();
  });
  expect(screen.getByText('ACCEPTED')).toBeVisible();
}

afterEach(() => {
  vi.useRealTimers();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

describe('motion command REST polling budgets', () => {
  it('stops scheduling after five consecutive status failures while retaining the active state', async () => {
    vi.useFakeTimers();
    const statusRequests = mockPolling('error');
    render(<PollHarness />);
    await startCommand();

    await act(async () => vi.advanceTimersByTimeAsync(10_000));
    expect(statusRequests()).toBe(5);
    expect(screen.getByText(/polling stopped after 5 consecutive failures/)).toBeVisible();
    expect(screen.getByText('ACCEPTED')).toBeVisible();

    await act(async () => vi.advanceTimersByTimeAsync(120_000));
    expect(statusRequests()).toBe(5);
  });

  it('stops a perpetually running REST poll after the duration budget', async () => {
    vi.useFakeTimers();
    const statusRequests = mockPolling('running');
    render(<PollHarness />);
    await startCommand();

    await act(async () => vi.advanceTimersByTimeAsync(70_000));
    const exhaustedCount = statusRequests();
    expect(exhaustedCount).toBeGreaterThan(100);
    expect(exhaustedCount).toBeLessThanOrEqual(180);
    expect(screen.getByText(/65 second duration budget/)).toBeVisible();
    expect(screen.getByText('RUNNING')).toBeVisible();

    await act(async () => vi.advanceTimersByTimeAsync(120_000));
    expect(statusRequests()).toBe(exhaustedCount);
  });
});
