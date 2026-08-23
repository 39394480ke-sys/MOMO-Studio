import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { AppContent } from './App';

const profile = {
  schema_version: '1.0.0',
  variant: 'V2',
  display_name: 'MOMO V2 Example',
  has_linear_rail: true,
  enabled_joints: ['j10', 'j11', 'j12', 'j13', 'j14', 'j15'],
  joint_definitions: [
    { joint_id: 'j10', joint_type: 'PRISMATIC', domain_unit: 'mm', minimum: 0, maximum: 500, home: 0 },
    ...['j11', 'j12', 'j13', 'j14', 'j15'].map((joint_id) => ({
      joint_id,
      joint_type: 'REVOLUTE',
      domain_unit: 'deg',
      minimum: -180,
      maximum: 180,
      home: 0,
    })),
  ],
  urdf_reference: null,
  tcp_link: 'tool0',
  template: true,
  verification_status: 'VERIFIED_FOR_DRY_RUN',
  source: 'example',
  source_revision: 'stage-2',
  description: 'example',
};

const robot = {
  robot_id: 'primary',
  variant: 'V2',
  control_mode: 'DRY_RUN',
  hardware_access_policy: 'DISABLED',
  connection_state: 'DISCONNECTED',
  connected: false,
  profile_fingerprint: 'a'.repeat(64),
  profile_verification_status: 'VERIFIED_FOR_DRY_RUN',
  calibration_status: 'TEMPLATE_ONLY',
  positions: { j10: 0, j11: 0, j12: 0, j13: 0, j14: 0, j15: 0 },
  units: { j10: 'mm', j11: 'deg', j12: 'deg', j13: 'deg', j14: 'deg', j15: 'deg' },
  raw_positions: null,
  last_error: null,
  updated_at: '2026-08-24T00:00:00Z',
  state_sequence: 0,
  hardware_accessed: false,
};

const v1Profile = {
  ...profile,
  variant: 'V1',
  display_name: 'MOMO V1 Example',
  has_linear_rail: false,
  enabled_joints: ['j11', 'j12', 'j13', 'j14', 'j15'],
  joint_definitions: profile.joint_definitions.slice(1),
};

const v1Robot = {
  ...robot,
  variant: 'V1',
  positions: { j11: 0, j12: 0, j13: 0, j14: 0, j15: 0 },
  units: { j11: 'deg', j12: 'deg', j13: 'deg', j14: 'deg', j15: 'deg' },
};

const healthyResponse = {
  status: 'ok',
  product: 'MOMO Studio',
  version: '0.1.0',
  stage: 2,
  control_mode: 'DRY_RUN',
  hardware_access_policy: 'DISABLED',
  real_motion_enabled: false,
};

const metaResponse = {
  product: 'MOMO Studio',
  version: '0.1.0',
  api_version: 'v1',
  stage: 2,
  active_robot_variant: 'V2',
  supported_robot_variants: ['V1', 'V2'],
  supported_control_modes: ['DRY_RUN', 'REAL'],
  active_control_mode: 'DRY_RUN',
  hardware_access_policy: 'DISABLED',
  real_motion_enabled: false,
};

const calibration = {
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
  blocking_reasons: ['Stage 2 hardware access policy is DISABLED'],
};

const diagnostics = {
  hardware_access_policy: 'DISABLED',
  runtime_state_path: 'data/runtime/robots/primary.json',
  runtime_state_valid: true,
  runtime_state_diagnostic: 'No saved runtime state',
  quarantined_runtime_file: null,
  backend_version: '0.1.0',
  legacy_source_commit: 'ff8bbda0c2222cb57951c7913f7f12f5777b98fa',
  stage_policy: 'STAGE_2_DRY_RUN_ONLY',
  active_profile_fingerprint: 'a'.repeat(64),
  hardware_accessed: false,
};

function jsonResponse(body: unknown, ok = true): Response {
  return {
    ok,
    status: ok ? 200 : 500,
    json: vi.fn().mockResolvedValue(body),
  } as unknown as Response;
}

function mockBackendOnline(options?: {
  initialRobot?: Record<string, unknown>;
  initialProfile?: Record<string, unknown>;
  connectError?: string;
}) {
  let currentRobot = options?.initialRobot ?? robot;
  let currentProfile = options?.initialProfile ?? profile;
  let offline = false;
  const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
    const path = String(input);
    if (offline) return Promise.reject(new Error('offline'));
    if (path.endsWith('/health')) return Promise.resolve(jsonResponse(healthyResponse));
    if (path.endsWith('/meta')) return Promise.resolve(jsonResponse(metaResponse));
    if (path.endsWith('/robot/profile')) return Promise.resolve(jsonResponse({ profile: currentProfile, fingerprint: 'a'.repeat(64), real_eligible: false }));
    if (path.endsWith('/calibration/status')) return Promise.resolve(jsonResponse(calibration));
    if (path.endsWith('/robot/diagnostics')) return Promise.resolve(jsonResponse(diagnostics));
    if (path.endsWith('/robot/connect')) {
      if (options?.connectError) {
        return Promise.resolve(jsonResponse({ message: options.connectError }, false));
      }
      currentRobot = { ...currentRobot, connection_state: 'CONNECTED', connected: true, state_sequence: 2 };
      return Promise.resolve(jsonResponse({ status: currentRobot, hardware_accessed: false }));
    }
    if (path.endsWith('/robot/disconnect')) {
      currentRobot = { ...currentRobot, connection_state: 'DISCONNECTED', connected: false, state_sequence: 4 };
      return Promise.resolve(jsonResponse({ status: currentRobot, hardware_accessed: false }));
    }
    if (path.endsWith('/robot/stop')) return Promise.resolve(jsonResponse({ result: currentRobot.connected ? 'STOPPED' : 'NOT_CONNECTED', status: currentRobot, hardware_accessed: false }));
    if (path.endsWith('/robot/variant')) {
      const requested = JSON.parse(String(init?.body)) as { variant: 'V1' | 'V2' };
      currentProfile = requested.variant === 'V1' ? v1Profile : profile;
      currentRobot = requested.variant === 'V1' ? v1Robot : robot;
      return Promise.resolve(jsonResponse({ status: currentRobot, hardware_accessed: false }));
    }
    if (path.endsWith('/robot')) return Promise.resolve(jsonResponse(currentRobot));
    void init;
    return Promise.reject(new Error(`Unhandled ${path}`));
  });
  vi.stubGlobal('fetch', fetchMock);
  return {
    fetchMock,
    goOffline: () => {
      offline = true;
    },
    setProfile: (next: Record<string, unknown>) => {
      currentProfile = next;
    },
  };
}

function renderRoute(path: string) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <AppContent />
    </MemoryRouter>,
  );
}

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

describe('MOMO Studio Stage 2 shell', () => {
  it.each([
    ['/control', 'Control'],
    ['/studio', 'Studio'],
    ['/library', 'Library'],
    ['/vision', 'Vision'],
    ['/settings', 'Settings'],
  ])('provides the %s route', async (path, heading) => {
    mockBackendOnline();
    renderRoute(path);
    expect(await screen.findByRole('heading', { level: 1, name: heading })).toBeVisible();
  });

  it('renders backend-backed V2 telemetry and keeps the surface read-only', async () => {
    mockBackendOnline();
    renderRoute('/control');
    expect(await screen.findByText('J10')).toBeVisible();
    expect(screen.getByText('mm')).toBeVisible();
    expect(screen.getByText('Stage 2: Motion controls are not enabled yet.')).toBeVisible();
    expect(screen.queryByRole('button', { name: /jog|home|move pose/i })).not.toBeInTheDocument();
    expect(screen.queryByRole('slider')).not.toBeInTheDocument();
    expect(screen.queryByText(/real mode/i)).not.toBeInTheDocument();
  });

  it('switches to V1 in Settings and shows exactly five enabled joints', async () => {
    const user = userEvent.setup();
    mockBackendOnline();
    renderRoute('/settings');
    expect(await screen.findByText('V2 · Linear rail plus five revolute joints')).toBeVisible();
    await user.click(screen.getByRole('button', { name: 'V1' }));
    expect(await screen.findByText('V1 · Five revolute joints · No linear rail')).toBeVisible();
    expect(await screen.findByText('J11, J12, J13, J14, J15')).toBeVisible();
    expect(screen.queryByText('J10')).not.toBeInTheDocument();
  });

  it('renders V1 Control telemetry as five cards without J10', async () => {
    mockBackendOnline({ initialRobot: v1Robot, initialProfile: v1Profile });
    renderRoute('/control');
    expect(await screen.findByText('J11')).toBeVisible();
    expect(screen.getAllByRole('article')).toHaveLength(5);
    expect(screen.queryByText('J10')).not.toBeInTheDocument();
  });

  it('disables both variant choices while the robot is connected', async () => {
    mockBackendOnline({
      initialRobot: { ...robot, connection_state: 'CONNECTED', connected: true },
    });
    renderRoute('/settings');
    expect(await screen.findByText('V2 · Linear rail plus five revolute joints')).toBeVisible();
    expect(screen.getByRole('button', { name: 'V1' })).toBeDisabled();
    expect(screen.getByRole('button', { name: 'V2' })).toBeDisabled();
  });

  it('connects, stops, and disconnects the Dry Run robot', async () => {
    const user = userEvent.setup();
    const { fetchMock } = mockBackendOnline();
    renderRoute('/control');
    await screen.findByText('DISCONNECTED');

    await user.click(screen.getByRole('button', { name: 'Connect' }));
    expect(await screen.findByText('CONNECTED')).toBeVisible();
    await user.click(screen.getByRole('button', { name: 'Stop' }));
    await user.click(screen.getByRole('button', { name: 'Disconnect' }));
    expect(await screen.findByText('DISCONNECTED')).toBeVisible();

    expect(fetchMock).toHaveBeenCalledWith('/api/v1/robot/connect', expect.objectContaining({ method: 'POST' }));
    expect(fetchMock).toHaveBeenCalledWith('/api/v1/robot/stop', expect.objectContaining({ method: 'POST' }));
    expect(fetchMock).toHaveBeenCalledWith('/api/v1/robot/disconnect', expect.objectContaining({ method: 'POST' }));
  });

  it('shows calibration and profile fingerprint diagnostics', async () => {
    mockBackendOnline();
    renderRoute('/settings');
    expect(await screen.findByText('TEMPLATE_ONLY')).toBeVisible();
    expect(screen.getByText('a'.repeat(64))).toBeVisible();
    expect(screen.getByText('BLOCKED_BY_STAGE_POLICY', { exact: false })).toBeVisible();
  });

  it('preserves the last state and labels it stale after a later network failure', async () => {
    const backend = mockBackendOnline();
    renderRoute('/control');
    await screen.findByText('J10');
    backend.goOffline();
    await new Promise((resolve) => window.setTimeout(resolve, 1100));
    expect(await screen.findByText('Backend unavailable · showing stale state')).toBeVisible();
    expect(screen.getByText('J10')).toBeVisible();
  });

  it('renders a readable structured command failure', async () => {
    const user = userEvent.setup();
    mockBackendOnline({ connectError: 'The active Dry Run robot is already connected' });
    renderRoute('/control');
    await screen.findByText('DISCONNECTED');
    await user.click(screen.getByRole('button', { name: 'Connect' }));
    expect(await screen.findByText('The active Dry Run robot is already connected')).toBeVisible();
  });

  it('uses truthful safe fallback when backend is offline', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new Error('offline')));
    renderRoute('/control');
    expect(await screen.findByText('Backend unavailable')).toBeVisible();
    expect(screen.getByText('DRY RUN')).toBeVisible();
    expect(screen.getByText('Real motion disabled')).toBeVisible();
  });
});
