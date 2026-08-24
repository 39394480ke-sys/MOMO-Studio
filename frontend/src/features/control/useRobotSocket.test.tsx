import { act, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { preflight, robotFor } from '../../test/stage3Fixtures';
import { parseRobotSocketMessage, useRobotSocket } from './useRobotSocket';

type SocketListener = (event: Event | MessageEvent) => void;

class FakeWebSocket {
  static instances: FakeWebSocket[] = [];
  readonly listeners = new Map<string, SocketListener[]>();
  readonly url: string;
  readonly protocols: string | string[] | undefined;
  closed = false;

  constructor(url: string, protocols?: string | string[]) {
    this.url = url;
    this.protocols = protocols;
    FakeWebSocket.instances.push(this);
  }

  addEventListener(type: string, listener: EventListener) {
    const listeners = this.listeners.get(type) ?? [];
    listeners.push(listener as SocketListener);
    this.listeners.set(type, listeners);
  }

  close() {
    this.closed = true;
  }

  emit(type: string, event: Event | MessageEvent = new Event(type)) {
    for (const listener of this.listeners.get(type) ?? []) listener(event);
  }
}

function SocketState() {
  const socket = useRobotSocket(true);
  return (
    <>
      <span>{socket.connectionState}</span>
      <output>{socket.snapshot.stateSequence ?? 'NO_SNAPSHOT'}</output>
    </>
  );
}

afterEach(() => {
  vi.useRealTimers();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
  FakeWebSocket.instances = [];
});

describe('robot WebSocket', () => {
  it('uses the browser HttpOnly-cookie transport without a URL or subprotocol token', () => {
    vi.stubGlobal('WebSocket', FakeWebSocket);
    render(<SocketState />);

    const socket = FakeWebSocket.instances[0];
    const url = new URL(socket.url);
    expect(url.pathname).toBe('/api/v1/ws/robot');
    expect(url.search).toBe('');
    expect(url.username).toBe('');
    expect(url.password).toBe('');
    expect(socket.protocols).toBeUndefined();
  });

  it('parses robot, TCP, command progress, and state sequence from the Stage 3 payload', () => {
    const robot = robotFor('V2', true);
    const parsed = parseRobotSocketMessage({
      robot_status: robot,
      tcp_pose: {
        frame: 'base',
        position_mm: { x: 1, y: 2, z: 3 },
        orientation_quaternion_xyzw: { x: 0, y: 0, z: 0, w: 1 },
      },
      command_status: {
        command_id: '11111111-1111-4111-8111-111111111111',
        state: 'RUNNING',
        progress: 0.42,
        preflight,
        error: null,
        hardware_accessed: false,
      },
      state_sequence: 8,
      hardware_accessed: false,
    });

    expect(parsed.robot).toEqual(robot);
    expect(parsed.tcpPose?.position_mm).toEqual({ x: 1, y: 2, z: 3 });
    expect(parsed.command).toEqual(expect.objectContaining({ state: 'RUNNING', progress: 0.42 }));
    expect(parsed.stateSequence).toBe(8);
  });

  it('uses bounded exponential reconnects and leaves REST fallback after five retries', async () => {
    vi.useFakeTimers();
    vi.stubGlobal('WebSocket', FakeWebSocket);
    render(<SocketState />);
    expect(FakeWebSocket.instances).toHaveLength(1);

    for (const delay of [500, 1000, 2000, 4000, 8000]) {
      act(() => FakeWebSocket.instances.at(-1)?.emit('close'));
      await act(async () => vi.advanceTimersByTimeAsync(delay));
    }
    expect(FakeWebSocket.instances).toHaveLength(6);
    act(() => FakeWebSocket.instances.at(-1)?.emit('close'));
    await act(async () => vi.advanceTimersByTimeAsync(20_000));

    expect(FakeWebSocket.instances).toHaveLength(6);
    expect(screen.getByText('closed')).toBeVisible();
  });

  it('does not replenish the total retry budget during open/close flapping', async () => {
    vi.useFakeTimers();
    vi.stubGlobal('WebSocket', FakeWebSocket);
    render(<SocketState />);

    for (const delay of [500, 1000, 2000, 4000, 8000]) {
      const current = FakeWebSocket.instances.at(-1);
      act(() => {
        current?.emit('open');
        current?.emit('close');
      });
      await act(async () => vi.advanceTimersByTimeAsync(delay));
    }
    expect(FakeWebSocket.instances).toHaveLength(6);
    act(() => {
      FakeWebSocket.instances.at(-1)?.emit('open');
      FakeWebSocket.instances.at(-1)?.emit('close');
    });
    await act(async () => vi.advanceTimersByTimeAsync(60_000));

    expect(FakeWebSocket.instances).toHaveLength(6);
    expect(screen.getByText('closed')).toBeVisible();
  });

  it('drops a silent open socket snapshot after fifteen missed backend frames', async () => {
    vi.useFakeTimers();
    vi.stubGlobal('WebSocket', FakeWebSocket);
    render(<SocketState />);
    const current = FakeWebSocket.instances[0];

    act(() => {
      current?.emit('open');
      current?.emit('message', new MessageEvent('message', {
        data: JSON.stringify({
          robot_status: robotFor('V2', true),
          tcp_pose: {
            frame: 'base',
            position_mm: { x: 1, y: 2, z: 3 },
            orientation_quaternion_xyzw: { x: 0, y: 0, z: 0, w: 1 },
          },
          state_sequence: 8,
          hardware_accessed: false,
        }),
      }));
    });
    expect(screen.getByText('open')).toBeVisible();
    expect(screen.getByText('8')).toBeVisible();

    await act(async () => vi.advanceTimersByTimeAsync(1499));
    expect(current?.closed).toBe(false);
    expect(screen.getByText('8')).toBeVisible();

    await act(async () => vi.advanceTimersByTimeAsync(1));
    expect(current?.closed).toBe(true);
    expect(screen.getByText('closed')).toBeVisible();
    expect(screen.getByText('NO_SNAPSHOT')).toBeVisible();

    await act(async () => vi.advanceTimersByTimeAsync(500));
    expect(FakeWebSocket.instances).toHaveLength(2);
  });
});
