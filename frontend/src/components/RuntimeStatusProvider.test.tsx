import { act, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import {
  connectRobot,
  disconnectRobot,
  getBootstrapData,
  stopRobot,
  switchRobotVariant,
} from '../api/client';
import type { BootstrapResponse, RobotProfile, RobotStatus } from '../api/types';
import { robotFor, v2Profile } from '../test/stage3Fixtures';
import { RuntimeStatusProvider } from './RuntimeStatusProvider';
import { useRuntimeStatus } from './runtimeStatusContext';

vi.mock('../api/client', () => ({
  connectRobot: vi.fn(),
  disconnectRobot: vi.fn(),
  getBootstrapData: vi.fn(),
  stopRobot: vi.fn(),
  switchRobotVariant: vi.fn(),
}));

const PROFILE_FINGERPRINT = 'a'.repeat(64);
const KINEMATICS_FINGERPRINT = 'b'.repeat(64);

function bootstrap(connected: boolean): BootstrapResponse {
  return {
    health: {
      status: 'ok',
      product: 'MOMO Studio',
      version: '0.1.0-rc1',
      stage: 8,
      control_mode: 'DRY_RUN',
      hardware_access_policy: 'DISABLED',
      real_motion_enabled: false,
    },
    meta: {
      product: 'MOMO Studio',
      version: '0.1.0-rc1',
      api_version: 'v1',
      stage: 8,
      release_status: 'FIELD_ACCEPTANCE_REQUIRED',
      dry_run_validated: true,
      real_hardware_field_acceptance: 'PENDING',
      active_robot_variant: 'V2',
      supported_robot_variants: ['V1', 'V2'],
      supported_control_modes: ['DRY_RUN', 'REAL'],
      active_control_mode: 'DRY_RUN',
      hardware_access_policy: 'DISABLED',
      real_motion_enabled: false,
    },
    robot: robotFor('V2', connected) as RobotStatus,
    profile: {
      profile: v2Profile as RobotProfile,
      fingerprint: PROFILE_FINGERPRINT,
      kinematics_fingerprint: KINEMATICS_FINGERPRINT,
      real_eligible: false,
    },
    calibration: {
      status: 'TEMPLATE_ONLY',
      configured: true,
      template: true,
      variant_match: true,
      profile_match: true,
      joint_set_match: true,
      mapping_match: true,
      complete: true,
      calibration_valid: true,
      real_readiness: 'BLOCKED_BY_STAGE_POLICY',
      blocking_reasons: ['Stage 4 remains Dry Run only'],
    },
    diagnostics: {
      hardware_access_policy: 'DISABLED',
      runtime_state_path: 'data/runtime/robots/primary.json',
      runtime_state_valid: true,
      runtime_state_diagnostic: 'No saved runtime state',
      quarantined_runtime_file: null,
      backend_version: '0.1.0',
      legacy_source_commit: 'ff8bbda0c2222cb57951c7913f7f12f5777b98fa',
      stage_policy: 'STAGE_4_DRY_RUN_ONLY',
      active_profile_fingerprint: PROFILE_FINGERPRINT,
      active_kinematics_fingerprint: KINEMATICS_FINGERPRINT,
      hardware_accessed: false,
    },
  };
}

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((resolvePromise, rejectPromise) => {
    resolve = resolvePromise;
    reject = rejectPromise;
  });
  return { promise, resolve, reject };
}

function RuntimeProbe() {
  const runtime = useRuntimeStatus();
  return (
    <div>
      <output>{runtime.robot?.connection_state ?? 'NO_STATUS'}</output>
      <output>{runtime.backend === 'connected' ? 'BACKEND_CONNECTED' : 'BACKEND_UNAVAILABLE'}</output>
      <output>{runtime.stale ? 'STALE' : 'FRESH'}</output>
      <output>{runtime.controlMode}</output>
      <output>{runtime.hardwareAccessPolicy}</output>
      <button type="button" onClick={() => void runtime.connect()}>
        Connect probe
      </button>
    </div>
  );
}

beforeEach(() => {
  vi.mocked(connectRobot).mockReset();
  vi.mocked(disconnectRobot).mockReset();
  vi.mocked(getBootstrapData).mockReset();
  vi.mocked(stopRobot).mockReset();
  vi.mocked(switchRobotVariant).mockReset();
});

afterEach(() => {
  vi.useRealTimers();
});

describe('RuntimeStatusProvider refresh lifecycle', () => {
  it('shows coherent REAL / READ_ONLY state but never reuses the Dry Run lifecycle API', async () => {
    const commissioning = bootstrap(false);
    commissioning.health = {
      ...commissioning.health,
      control_mode: 'REAL',
      hardware_access_policy: 'READ_ONLY',
    };
    commissioning.meta = {
      ...commissioning.meta,
      active_control_mode: 'REAL',
      hardware_access_policy: 'READ_ONLY',
    };
    commissioning.robot = {
      ...commissioning.robot,
      control_mode: 'REAL',
      hardware_access_policy: 'READ_ONLY',
    };
    vi.mocked(getBootstrapData).mockResolvedValue(commissioning);

    render(
      <RuntimeStatusProvider>
        <RuntimeProbe />
      </RuntimeStatusProvider>,
    );

    expect(await screen.findByText('REAL')).toBeVisible();
    expect(screen.getByText('READ_ONLY')).toBeVisible();
    fireEvent.click(screen.getByRole('button', { name: 'Connect probe' }));
    expect(connectRobot).not.toHaveBeenCalled();
  });

  it('accepts a coherent connected REAL product runtime with truthful hardware access', async () => {
    const production = bootstrap(true);
    production.health = {
      ...production.health,
      control_mode: 'REAL',
      hardware_access_policy: 'FULL',
      real_motion_enabled: true,
    };
    production.meta = {
      ...production.meta,
      active_control_mode: 'REAL',
      hardware_access_policy: 'FULL',
      real_motion_enabled: true,
    };
    production.robot = {
      ...production.robot,
      control_mode: 'REAL',
      hardware_access_policy: 'FULL',
      hardware_accessed: true,
    };
    production.diagnostics = {
      ...production.diagnostics,
      hardware_access_policy: 'FULL',
      hardware_accessed: true,
    };
    vi.mocked(getBootstrapData).mockResolvedValue(production);

    render(
      <RuntimeStatusProvider>
        <RuntimeProbe />
      </RuntimeStatusProvider>,
    );

    expect(await screen.findByText('REAL')).toBeVisible();
    expect(screen.getByText('FULL')).toBeVisible();
    expect(screen.getByText('BACKEND_CONNECTED')).toBeVisible();
    expect(screen.getByText('CONNECTED')).toBeVisible();
  });

  it('does not let a deferred bootstrap overwrite a newer Connect response', async () => {
    const oldBootstrap = deferred<BootstrapResponse>();
    vi.mocked(getBootstrapData).mockReturnValue(oldBootstrap.promise);
    vi.mocked(connectRobot).mockResolvedValue({
      status: robotFor('V2', true) as RobotStatus,
      hardware_accessed: false,
    });

    render(
      <RuntimeStatusProvider>
        <RuntimeProbe />
      </RuntimeStatusProvider>,
    );
    expect(getBootstrapData).toHaveBeenCalledTimes(1);
    const oldSignal = vi.mocked(getBootstrapData).mock.calls[0][0];

    fireEvent.click(screen.getByRole('button', { name: 'Connect probe' }));
    expect(await screen.findByText('CONNECTED')).toBeVisible();
    expect(oldSignal?.aborted).toBe(true);

    await act(async () => {
      oldBootstrap.resolve(bootstrap(false));
      await oldBootstrap.promise;
    });

    expect(screen.getByText('CONNECTED')).toBeVisible();
  });

  it('times out a pending refresh fail-closed without accumulating more batches', async () => {
    vi.useFakeTimers();
    const pendingBootstrap = deferred<BootstrapResponse>();
    vi.mocked(getBootstrapData)
      .mockResolvedValueOnce(bootstrap(true))
      .mockReturnValue(pendingBootstrap.promise);

    const view = render(
      <RuntimeStatusProvider>
        <RuntimeProbe />
      </RuntimeStatusProvider>,
    );

    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
    });
    expect(getBootstrapData).toHaveBeenCalledTimes(1);
    expect(screen.getByText('BACKEND_CONNECTED')).toBeVisible();
    expect(screen.getByText('FRESH')).toBeVisible();

    await act(async () => {
      vi.advanceTimersByTime(1000);
    });
    expect(getBootstrapData).toHaveBeenCalledTimes(2);
    const signal = vi.mocked(getBootstrapData).mock.calls[1][0];
    expect(signal?.aborted).toBe(false);

    await act(async () => {
      vi.advanceTimersByTime(900);
    });
    expect(signal?.aborted).toBe(true);
    expect(screen.getByText('BACKEND_UNAVAILABLE')).toBeVisible();
    expect(screen.getByText('STALE')).toBeVisible();

    await act(async () => {
      vi.advanceTimersByTime(5000);
    });
    expect(getBootstrapData).toHaveBeenCalledTimes(2);

    view.unmount();

    await act(async () => {
      pendingBootstrap.resolve(bootstrap(true));
      await pendingBootstrap.promise;
    });
  });

  it('clears the timeout and aborts the pending batch on cleanup', async () => {
    vi.useFakeTimers();
    const pendingBootstrap = deferred<BootstrapResponse>();
    vi.mocked(getBootstrapData).mockReturnValue(pendingBootstrap.promise);

    const view = render(
      <RuntimeStatusProvider>
        <RuntimeProbe />
      </RuntimeStatusProvider>,
    );
    const signal = vi.mocked(getBootstrapData).mock.calls[0][0];

    await act(async () => {
      vi.advanceTimersByTime(500);
    });
    view.unmount();
    expect(signal?.aborted).toBe(true);

    await act(async () => {
      vi.advanceTimersByTime(2000);
    });
    expect(getBootstrapData).toHaveBeenCalledTimes(1);

    await act(async () => {
      pendingBootstrap.resolve(bootstrap(true));
      await pendingBootstrap.promise;
    });
  });
});
