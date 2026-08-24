import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { AppContent } from '../app/App';
import { mockStage3Backend, robotFor, stage3Ids } from '../test/stage3Fixtures';

type WebSocketListener = (event: Event | MessageEvent) => void;

class ControllableWebSocket {
  static instances: ControllableWebSocket[] = [];
  readonly listeners = new Map<string, WebSocketListener[]>();
  readonly url: string;

  constructor(url: string) {
    this.url = url;
    ControllableWebSocket.instances.push(this);
  }

  addEventListener(type: string, listener: EventListener) {
    const listeners = this.listeners.get(type) ?? [];
    listeners.push(listener as WebSocketListener);
    this.listeners.set(type, listeners);
  }

  close() {
    // Tests explicitly emit close when exercising the fallback boundary.
  }

  emit(type: string, event: Event | MessageEvent = new Event(type)) {
    for (const listener of this.listeners.get(type) ?? []) listener(event);
  }
}

function renderControl() {
  return render(
    <MemoryRouter initialEntries={['/control']}>
      <AppContent />
    </MemoryRouter>,
  );
}

async function waitForMotionReady() {
  expect(await screen.findByText('运动已就绪')).toBeVisible();
  expect(screen.getByRole('button', { name: '移动全部关节' })).toBeEnabled();
}

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
  ControllableWebSocket.instances = [];
});

describe('Stage 3 Control workspace', () => {
  it('never reuses Dry Run motion or lifecycle routes in REAL / READ_ONLY commissioning', async () => {
    const backend = mockStage3Backend({
      controlMode: 'REAL',
      hardwareAccessPolicy: 'READ_ONLY',
      realMotionEnabled: false,
    });
    renderControl();

    expect((await screen.findAllByText('Commissioning READ ONLY · 禁止运动')).length)
      .toBeGreaterThan(0);
    expect(screen.getAllByText('READ ONLY').length).toBeGreaterThan(0);
    expect(screen.getByRole('button', { name: '连接' })).toBeDisabled();
    expect(screen.getByRole('button', { name: '断开连接' })).toBeDisabled();
    expect(screen.getByRole('button', { name: '停止运动' })).toBeDisabled();
    expect(screen.getByRole('button', { name: '移动全部关节' })).toBeDisabled();
    expect(screen.getByRole('button', { name: 'Step J11 positive' })).toBeDisabled();
    expect(screen.getByRole('button', { name: '移动到位姿' })).toBeDisabled();
    expect(screen.getByRole('button', { name: '机器人回零' })).toBeDisabled();
    expect(backend.requestsFor('/robot/connect')).toHaveLength(0);
    expect(backend.requestsFor('/motion/joints')).toHaveLength(0);
    expect(backend.requestsFor('/motion/home')).toHaveLength(0);
  });

  it('renders responsive keyed V2 controls with J10 in millimetres and no unrelated tools', async () => {
    mockStage3Backend();
    const view = renderControl();
    await waitForMotionReady();

    expect(screen.getByLabelText('J10 target (mm)')).toBeVisible();
    expect(screen.getByLabelText('J11 target (deg)')).toBeVisible();
    expect(screen.getByText('0.00, 0.00, 0.00 deg')).toBeVisible();
    expect(view.container.querySelector('.control-workspace-grid')).toBeInTheDocument();
    expect(view.container.querySelector('.control-workspace-sidebar')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /record|capture|teach|playback/i })).not.toBeInTheDocument();
  });

  it('submits exact joint, step, Cartesian, IK, pose, and Home DTOs', async () => {
    const user = userEvent.setup();
    const backend = mockStage3Backend();
    renderControl();
    await waitForMotionReady();

    const j10 = screen.getByLabelText('J10 target (mm)');
    await user.clear(j10);
    await user.type(j10, '42.5');
    await user.click(screen.getByRole('button', { name: '移动全部关节' }));
    await waitFor(() => expect(backend.requestsFor('/motion/joints')).toHaveLength(1));
    expect(backend.lastBody('/motion/joints')).toEqual(expect.objectContaining({
      source: 'CONTROL',
      expected_state_sequence: 7,
      expected_profile_fingerprint: stage3Ids.profileFingerprint,
      expected_kinematics_fingerprint: stage3Ids.kinematicsFingerprint,
      speed_scale: 0.5,
      duration_s: 1,
      joint_state: {
        positions: { j10: 42.5, j11: 0, j12: 0, j13: 0, j14: 0, j15: 0 },
        units: { j10: 'mm', j11: 'deg', j12: 'deg', j13: 'deg', j14: 'deg', j15: 'deg' },
      },
    }));
    expect((backend.lastBody('/motion/joints') as { idempotency_key: string }).idempotency_key)
      .toMatch(/^control-move-joints-/);

    await user.click(screen.getByRole('button', { name: 'Step J10 negative' }));
    await waitFor(() => expect(backend.requestsFor('/motion/jog-step')).toHaveLength(1));
    expect(backend.lastBody('/motion/jog-step')).toEqual(expect.objectContaining({
      joint_id: 'j10', delta: -5, unit: 'mm', duration_s: 1,
    }));

    await user.click(screen.getByRole('button', { name: 'TOOL' }));
    await user.click(screen.getByRole('button', { name: 'Jog Rz positive' }));
    await waitFor(() => expect(backend.requestsFor('/motion/cartesian-jog')).toHaveLength(1));
    expect(backend.lastBody('/motion/cartesian-jog')).toEqual(expect.objectContaining({
      frame: 'TOOL',
      delta_position_mm: { x: 0, y: 0, z: 0 },
      delta_rotation_deg: { x: 0, y: 0, z: 3 },
      translation_unit: 'mm',
      rotation_unit: 'deg',
      duration_s: 1,
    }));

    await user.click(screen.getByRole('button', { name: '检查逆解' }));
    await waitFor(() => expect(backend.requestsFor('/kinematics/ik')).toHaveLength(1));
    expect(backend.lastBody('/kinematics/ik')).toEqual({
      target_pose: {
        frame: 'base',
        position_mm: { x: 101, y: 202, z: 303 },
        orientation_quaternion_xyzw: { x: 0, y: 0, z: 0, w: 1 },
      },
      position_unit: 'mm',
      orientation_unit: 'quaternion_xyzw',
      seed_joint_state: {
        positions: { j10: 0, j11: 0, j12: 0, j13: 0, j14: 0, j15: 0 },
        units: { j10: 'mm', j11: 'deg', j12: 'deg', j13: 'deg', j14: 'deg', j15: 'deg' },
      },
      position_only: false,
      maximum_iterations: 200,
    });
    expect(await screen.findByText('逆解可达')).toBeVisible();

    await user.click(screen.getByRole('button', { name: '移动到位姿' }));
    await waitFor(() => expect(backend.requestsFor('/motion/pose')).toHaveLength(1));
    expect(backend.lastBody('/motion/pose')).toEqual(expect.objectContaining({
      target_pose: expect.objectContaining({ frame: 'base' }),
      position_unit: 'mm',
      orientation_unit: 'quaternion_xyzw',
      duration_s: 1,
    }));

    await user.click(screen.getByRole('button', { name: '机器人回零' }));
    expect(backend.requestsFor('/motion/home')).toHaveLength(0);
    expect(screen.getByRole('alertdialog', { name: '确认回零' })).toBeVisible();
    await user.click(screen.getByRole('button', { name: '取消回零' }));
    expect(screen.queryByRole('alertdialog', { name: '确认回零' })).not.toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: '机器人回零' }));
    await user.click(screen.getByRole('button', { name: '确认回零' }));
    await waitFor(() => expect(backend.requestsFor('/motion/home')).toHaveLength(1));
    expect(backend.lastBody('/motion/home')).toEqual(expect.objectContaining({
      confirm: 'HOME', duration_s: 1,
    }));

    expect(screen.getByText('预检通过')).toBeVisible();
    expect(screen.getByText('operator_intent')).toBeVisible();
  });

  it('keeps motion disabled while disconnected, but leaves connection available', async () => {
    mockStage3Backend({ connected: false });
    renderControl();
    expect(await screen.findByText('DISCONNECTED')).toBeVisible();
    expect(screen.getByRole('button', { name: '连接' })).toBeEnabled();
    expect(screen.getByRole('button', { name: '移动全部关节' })).toBeDisabled();
    expect(screen.getByRole('button', { name: 'Step J10 positive' })).toBeDisabled();
    expect(screen.getByLabelText('J10 target (mm)')).toBeDisabled();
    expect(screen.getByLabelText('关节单步 (deg)')).toBeDisabled();
    expect(screen.getByRole('button', { name: '检查逆解' })).toBeDisabled();
    expect(screen.getByRole('button', { name: '机器人回零' })).toBeDisabled();
  });

  it('fails motion closed immediately while Disconnect is pending', async () => {
    const user = userEvent.setup();
    let releaseDisconnect!: () => void;
    const disconnectGate = new Promise<void>((resolve) => {
      releaseDisconnect = resolve;
    });
    mockStage3Backend({ disconnectGate });
    renderControl();
    await waitForMotionReady();

    await user.click(screen.getByRole('button', { name: /^断开连接$/ }));

    expect((await screen.findAllByText('机器人生命周期操作进行中 · 运动已禁用')).length).toBeGreaterThan(0);
    expect(screen.getByRole('button', { name: '移动全部关节' })).toBeDisabled();
    expect(screen.getByRole('button', { name: 'Step J11 positive' })).toBeDisabled();
    expect(screen.getByRole('button', { name: 'Hold J11 positive jog' })).toBeDisabled();
    expect(screen.getByRole('button', { name: '检查逆解' })).toBeDisabled();
    expect(screen.getByRole('button', { name: '移动到位姿' })).toBeDisabled();
    expect(screen.getByRole('button', { name: '机器人回零' })).toBeDisabled();
    expect(screen.getByRole('button', { name: '停止运动' })).toBeEnabled();

    releaseDisconnect();
    expect(await screen.findByText('DISCONNECTED')).toBeVisible();
  });

  it('fails closed when an HTTP 200 RobotStatus explicitly reports stale', async () => {
    mockStage3Backend({ robotStale: true });
    renderControl();

    expect(await screen.findByText('机器人状态已过期 · 运动已禁用')).toBeVisible();
    expect(screen.getByRole('button', { name: '移动全部关节' })).toBeDisabled();
    expect(screen.getByRole('button', { name: 'Step J10 positive' })).toBeDisabled();
    expect(screen.getByRole('button', { name: '检查逆解' })).toBeDisabled();
    expect(screen.getByRole('button', { name: '停止运动' })).toBeDisabled();
  });

  it('immediately disables motion when a live WebSocket RobotStatus becomes stale', async () => {
    mockStage3Backend();
    vi.stubGlobal('WebSocket', ControllableWebSocket);
    renderControl();
    await waitForMotionReady();
    const webSocket = ControllableWebSocket.instances[0];

    act(() => {
      webSocket?.emit('open');
      webSocket?.emit('message', new MessageEvent('message', {
        data: JSON.stringify({
          robot_status: { ...robotFor('V2', true), stale: true },
          tcp_pose: {
            frame: 'base',
            position_mm: { x: 101, y: 202, z: 303 },
            orientation_quaternion_xyzw: { x: 0, y: 0, z: 0, w: 1 },
          },
          state_sequence: 7,
          hardware_accessed: false,
        }),
      }));
    });

    expect(await screen.findByText('机器人状态已过期 · 运动已禁用')).toBeVisible();
    expect(screen.getByRole('button', { name: '移动全部关节' })).toBeDisabled();
    expect(screen.getByRole('button', { name: 'Step J11 positive' })).toBeDisabled();
  });

  it('shows unreachable IK evidence and structured IK request errors', async () => {
    const user = userEvent.setup();
    mockStage3Backend({ ikSuccess: false });
    const first = renderControl();
    await waitForMotionReady();
    await user.click(screen.getByRole('button', { name: '检查逆解' }));
    expect(await screen.findByText('逆解不可达')).toBeVisible();
    expect(screen.getByText('UNREACHABLE')).toBeVisible();
    expect(screen.getByText('No solution within limits')).toBeVisible();

    first.unmount();
    mockStage3Backend({ ikError: true });
    renderControl();
    await waitForMotionReady();
    await user.click(screen.getByRole('button', { name: '检查逆解' }));
    expect(await screen.findByText(/IK_INVALID_TARGET: IK target is outside/)).toBeVisible();
  });

  it('renders failed checks from a structured preflight rejection', async () => {
    const user = userEvent.setup();
    mockStage3Backend({ preflightReject: true });
    renderControl();
    await waitForMotionReady();
    await user.click(screen.getByRole('button', { name: 'Step J11 positive' }));

    expect(await screen.findByText('预检未通过')).toBeVisible();
    expect(screen.getByText('workspace_bounds')).toBeVisible();
    expect(screen.getByText(/Target Z exceeds provisional bounds/)).toBeVisible();
    expect(screen.getByText(/MOTION_PREFLIGHT_REJECTED/)).toBeVisible();
  });

  it('drops a closed WebSocket snapshot and submits against fresh REST/FK state', async () => {
    const user = userEvent.setup();
    const backend = mockStage3Backend();
    vi.stubGlobal('WebSocket', ControllableWebSocket);
    renderControl();
    await waitForMotionReady();
    const webSocket = ControllableWebSocket.instances[0];
    expect(webSocket).toBeDefined();

    const socketRobot = { ...robotFor('V2', true), state_sequence: 99 };
    act(() => {
      webSocket?.emit('open');
      webSocket?.emit('message', new MessageEvent('message', {
        data: JSON.stringify({
          robot_status: socketRobot,
          tcp_pose: {
            frame: 'base',
            position_mm: { x: 9, y: 9, z: 9 },
            orientation_quaternion_xyzw: { x: 0, y: 0, z: 0, w: 1 },
          },
          state_sequence: 99,
          hardware_accessed: false,
        }),
      }));
    });
    await waitFor(() => expect(screen.getByText('99')).toBeVisible());
    const fkRequestsWhileOpen = backend.requestsFor('/robot/fk').length;
    act(() => {
      webSocket?.emit('message', new MessageEvent('message', {
        data: JSON.stringify({
          robot_status: { ...socketRobot, state_sequence: 100 },
          tcp_pose: {
            frame: 'base',
            position_mm: { x: 10, y: 10, z: 10 },
            orientation_quaternion_xyzw: { x: 0, y: 0, z: 0, w: 1 },
          },
          state_sequence: 100,
          hardware_accessed: false,
        }),
      }));
    });
    await waitFor(() => expect(screen.getByText('100')).toBeVisible());
    expect(backend.requestsFor('/robot/fk')).toHaveLength(fkRequestsWhileOpen);

    act(() => webSocket?.emit('close'));
    await waitFor(() => expect(screen.getByText(/实时状态：REST 备用通道/)).toBeVisible());
    await waitFor(() => expect(screen.getByRole('button', { name: 'Step J11 positive' })).toBeEnabled());
    await user.click(screen.getByRole('button', { name: 'Step J11 positive' }));
    await waitFor(() => expect(backend.requestsFor('/motion/jog-step')).toHaveLength(1));
    expect(backend.lastBody('/motion/jog-step')).toEqual(expect.objectContaining({
      expected_state_sequence: 7,
    }));
  });

  it('locks every other motion control for an active command, polls progress, and keeps Stop enabled', async () => {
    const user = userEvent.setup();
    const backend = mockStage3Backend({
      motionState: 'ACCEPTED',
      polledCommandStates: ['RUNNING', 'RUNNING', 'RUNNING'],
    });
    renderControl();
    await waitForMotionReady();

    await user.click(screen.getByRole('button', { name: 'Step J11 positive' }));
    await waitFor(() => expect(screen.getByRole('button', { name: '移动全部关节' })).toBeDisabled());
    expect(screen.getByRole('button', { name: '移动到位姿' })).toBeDisabled();
    expect(screen.getByRole('button', { name: '机器人回零' })).toBeDisabled();
    expect(screen.getByRole('button', { name: '停止运动' })).toBeEnabled();

    expect(await screen.findByText(/35%/, {}, { timeout: 1200 })).toBeVisible();
    await waitFor(() => expect(backend.requestsFor(`/motion/commands/${stage3Ids.commandId}`).length).toBeGreaterThan(1), {
      timeout: 1500,
    });

    await user.click(screen.getByRole('button', { name: '停止运动' }));
    await waitFor(() => expect(backend.requestsFor('/motion/stop')).toHaveLength(1));
    expect(await screen.findByText('CANCELLED')).toBeVisible();
    expect(screen.getByRole('button', { name: '移动全部关节' })).toBeEnabled();
  });

  it.each(['FAILED', 'SAFETY_STATE_UNCERTAIN'] as const)(
    'keeps motion fail-closed when Stop returns HTTP 200 %s',
    async (stopResult) => {
      const user = userEvent.setup();
      const backend = mockStage3Backend({
        motionState: 'ACCEPTED',
        polledCommandStates: ['RUNNING'],
        stopResult,
      });
      renderControl();
      await waitForMotionReady();

      await user.click(screen.getByRole('button', { name: 'Step J11 positive' }));
      await waitFor(() => expect(screen.getByRole('button', { name: '移动全部关节' })).toBeDisabled());
      await user.click(screen.getByRole('button', { name: '停止运动' }));

      expect(await screen.findByText('CANCELLED')).toBeVisible();
      expect(await screen.findByText(new RegExp(`Motion Stop returned ${stopResult}`))).toBeVisible();
      expect(screen.getAllByText(/运动安全状态不确定/).length).toBeGreaterThan(0);
      expect(screen.getByRole('button', { name: '移动全部关节' })).toBeDisabled();
      expect(screen.getByRole('button', { name: '移动到位姿' })).toBeDisabled();
      expect(screen.getByRole('button', { name: '停止运动' })).toBeEnabled();
      expect(backend.requestsFor(`/motion/commands/${stage3Ids.commandId}`).length).toBeGreaterThan(0);
    },
  );

  it('keeps the active hold button live through command lock, heartbeats its lease, and stops on pointerup', async () => {
    const backend = mockStage3Backend({ polledCommandStates: ['RUNNING'] });
    renderControl();
    await waitForMotionReady();
    const hold = screen.getByRole('button', { name: 'Hold J10 positive jog' });

    fireEvent.pointerDown(hold, { pointerId: 1 });
    await waitFor(() => expect(backend.requestsFor('/motion/jog/start')).toHaveLength(1));
    await waitFor(() => expect(hold).toHaveAttribute('aria-pressed', 'true'));
    expect(hold).toBeEnabled();
    expect(screen.getByRole('button', { name: '移动全部关节' })).toBeDisabled();
    await waitFor(
      () => expect(backend.requestsFor(`/motion/jog/${stage3Ids.jogSessionId}/heartbeat`).length).toBeGreaterThan(0),
      { timeout: 600 },
    );

    fireEvent.pointerUp(hold, { pointerId: 1 });
    await waitFor(() => {
      expect(backend.requestsFor(`/motion/jog/${stage3Ids.jogSessionId}/stop`)).toHaveLength(1);
    });
    expect(backend.lastBody('/motion/jog/start')).toEqual(expect.objectContaining({
      joint_id: 'j10', direction: 1, speed_units_s: 20, unit: 'mm',
    }));
    expect(backend.lastBody('/motion/jog/start')).not.toHaveProperty('lease_timeout_ms');
  });

  it.each([
    ['pointer cancel', (button: HTMLElement) => fireEvent.pointerCancel(button)],
    ['button blur', (button: HTMLElement) => fireEvent.blur(button)],
    ['window blur', () => fireEvent.blur(window)],
    ['hidden document', () => {
      vi.spyOn(document, 'visibilityState', 'get').mockReturnValue('hidden');
      fireEvent(document, new Event('visibilitychange'));
    }],
  ])('stops an active hold jog on %s', async (_label, release) => {
    const backend = mockStage3Backend({ polledCommandStates: ['RUNNING'] });
    renderControl();
    await waitForMotionReady();
    const hold = screen.getByRole('button', { name: 'Hold J11 negative jog' });
    fireEvent.pointerDown(hold, { pointerId: 2 });
    await waitFor(() => expect(backend.requestsFor('/motion/jog/start')).toHaveLength(1));
    release(hold);
    await waitFor(() => {
      expect(backend.requestsFor(`/motion/jog/${stage3Ids.jogSessionId}/stop`)).toHaveLength(1);
    });
  });

  it('stops with keepalive when the page is hidden for unload', async () => {
    const backend = mockStage3Backend({ polledCommandStates: ['RUNNING'] });
    renderControl();
    await waitForMotionReady();
    const hold = screen.getByRole('button', { name: 'Hold J12 positive jog' });
    fireEvent.pointerDown(hold, { pointerId: 3 });
    await waitFor(() => expect(backend.requestsFor('/motion/jog/start')).toHaveLength(1));
    fireEvent(window, new Event('pagehide'));
    await waitFor(() => {
      expect(backend.requestsFor(`/motion/jog/${stage3Ids.jogSessionId}/stop`)).toHaveLength(1);
    });
    expect(backend.requestsFor(`/motion/jog/${stage3Ids.jogSessionId}/stop`)[0]?.init)
      .toEqual(expect.objectContaining({ method: 'POST', keepalive: true }));
  });

  it('stops on lost pointer capture', async () => {
    const backend = mockStage3Backend({ polledCommandStates: ['RUNNING'] });
    renderControl();
    await waitForMotionReady();
    const hold = screen.getByRole('button', { name: 'Hold J13 negative jog' });
    fireEvent.pointerDown(hold, { pointerId: 4 });
    await waitFor(() => expect(backend.requestsFor('/motion/jog/start')).toHaveLength(1));
    fireEvent.lostPointerCapture(hold, { pointerId: 4 });
    await waitFor(() => {
      expect(backend.requestsFor(`/motion/jog/${stage3Ids.jogSessionId}/stop`)).toHaveLength(1);
    });
  });

  it('reports heartbeat failure and relies on the bounded backend lease TTL', async () => {
    const backend = mockStage3Backend({ heartbeatError: true, polledCommandStates: ['RUNNING'] });
    renderControl();
    await waitForMotionReady();
    const hold = screen.getByRole('button', { name: 'Hold J12 positive jog' });
    fireEvent.pointerDown(hold, { pointerId: 3 });
    await waitFor(() => expect(backend.requestsFor('/motion/jog/start')).toHaveLength(1));
    await waitFor(() => expect(screen.getByText(/JOG_LEASE_EXPIRED/)).toBeVisible(), { timeout: 700 });
    await waitFor(() => {
      expect(backend.requestsFor(`/motion/jog/${stage3Ids.jogSessionId}/stop`)).toHaveLength(1);
    });

    expect(backend.lastBody('/motion/jog/start')).not.toHaveProperty('lease_timeout_ms');
  });
});
