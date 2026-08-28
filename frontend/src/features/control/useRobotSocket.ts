import { useEffect, useState } from 'react';

import { normalizeCommandStatus } from '../../api/client';
import { robotWebSocketUrl } from '../../api/config';
import type {
  RobotSocketSnapshot,
  RobotStatus,
  RobotWebSocketState,
} from '../../api/types';

const EMPTY_SNAPSHOT: RobotSocketSnapshot = Object.freeze({
  robot: null,
  tcpPose: null,
  stateSequence: null,
  command: null,
});
const SOCKET_SILENCE_TIMEOUT_MS = 1500;

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function recordsIn(value: unknown): Record<string, unknown>[] {
  if (!isRecord(value)) return [];
  const records = [value];
  for (const key of ['payload', 'data', 'status']) {
    if (isRecord(value[key])) records.push(value[key]);
  }
  return records;
}

function robotFrom(records: Record<string, unknown>[]): RobotStatus | null {
  const candidates: unknown[] = [];
  for (const record of records) {
    candidates.push(record, record.robot, record.robot_status);
  }
  for (const candidate of candidates) {
    if (
      isRecord(candidate) &&
      typeof candidate.robot_id === 'string' &&
      candidate.control_mode === 'DRY_RUN' &&
      candidate.hardware_access_policy === 'DISABLED' &&
      candidate.hardware_accessed === false &&
      typeof candidate.stale === 'boolean' &&
      isRecord(candidate.positions) &&
      isRecord(candidate.units)
    ) {
      return candidate as unknown as RobotStatus;
    }
  }
  return null;
}

function tcpPoseFrom(records: Record<string, unknown>[]): RobotSocketSnapshot['tcpPose'] {
  const candidates: unknown[] = [];
  for (const record of records) {
    candidates.push(record.tcp_pose, record.fk, record.forward_kinematics);
  }
  for (const candidate of candidates) {
    if (
      isRecord(candidate) &&
      isRecord(candidate.position_mm) &&
      isRecord(candidate.orientation_quaternion_xyzw)
    ) {
      return candidate as unknown as NonNullable<RobotSocketSnapshot['tcpPose']>;
    }
  }
  return null;
}

function commandFrom(records: Record<string, unknown>[]) {
  const candidates: unknown[] = [];
  for (const record of records) {
    candidates.push(record.command_status, record.command, record.motion_command);
    if (typeof record.command_id === 'string') candidates.push(record);
  }
  for (const candidate of candidates) {
    try {
      if (candidate !== undefined) return normalizeCommandStatus(candidate);
    } catch {
      // A mixed robot/FK event may contain a non-status `command` field.
    }
  }
  return null;
}

export function parseRobotSocketMessage(value: unknown): Partial<RobotSocketSnapshot> {
  const records = recordsIn(value);
  if (records.length === 0) return {};
  const robot = robotFrom(records);
  const tcpPose = tcpPoseFrom(records);
  const stateSequence = records.find(
    (record) => typeof record.state_sequence === 'number',
  )?.state_sequence;
  const command = commandFrom(records);
  return {
    ...(robot ? { robot } : {}),
    ...(tcpPose ? { tcpPose } : {}),
    ...(typeof stateSequence === 'number' ? { stateSequence } : {}),
    ...(command ? { command } : {}),
  };
}

export function useRobotSocket(enabled: boolean): {
  connectionState: RobotWebSocketState;
  snapshot: RobotSocketSnapshot;
} {
  const [connectionState, setConnectionState] = useState<RobotWebSocketState>('disabled');
  const [snapshot, setSnapshot] = useState<RobotSocketSnapshot>(EMPTY_SNAPSHOT);

  useEffect(() => {
    if (!enabled) {
      setConnectionState('disabled');
      setSnapshot(EMPTY_SNAPSHOT);
      return;
    }
    if (typeof WebSocket === 'undefined') {
      setConnectionState('unsupported');
      return;
    }

    let disposed = false;
    let reconnectTimer: number | null = null;
    let silenceTimer: number | null = null;
    let socket: WebSocket | null = null;
    let consecutiveRetryCount = 0;
    let totalRetryCount = 0;

    const connect = () => {
      if (disposed) return;
      setConnectionState('connecting');
      // The browser supplies the scoped HttpOnly cookie. Never add a token to this
      // URL or expose it through a JavaScript-readable WebSocket subprotocol.
      const currentSocket = new WebSocket(robotWebSocketUrl());
      let closeHandled = false;
      socket = currentSocket;

      const clearSilenceTimer = () => {
        if (silenceTimer !== null) {
          window.clearTimeout(silenceTimer);
          silenceTimer = null;
        }
      };
      const handleClose = () => {
        if (disposed || closeHandled || socket !== currentSocket) return;
        closeHandled = true;
        clearSilenceTimer();
        setConnectionState('closed');
        setSnapshot(EMPTY_SNAPSHOT);
        if (totalRetryCount >= 5) return;
        const delayMs = Math.min(8000, 500 * 2 ** consecutiveRetryCount);
        consecutiveRetryCount += 1;
        totalRetryCount += 1;
        reconnectTimer = window.setTimeout(connect, delayMs);
      };
      const armSilenceTimer = () => {
        clearSilenceTimer();
        silenceTimer = window.setTimeout(() => {
          if (disposed || socket !== currentSocket) return;
          handleClose();
          currentSocket.close();
        }, SOCKET_SILENCE_TIMEOUT_MS);
      };

      currentSocket.addEventListener('open', () => {
        if (!disposed && !closeHandled && socket === currentSocket) {
          setConnectionState('open');
          armSilenceTimer();
        }
      });
      currentSocket.addEventListener('message', (event) => {
        if (
          disposed ||
          closeHandled ||
          socket !== currentSocket ||
          typeof event.data !== 'string'
        ) return;
        try {
          const update = parseRobotSocketMessage(JSON.parse(event.data));
          if (Object.keys(update).length > 0) {
            setSnapshot((current) => ({ ...current, ...update }));
          }
          if (update.robot && update.tcpPose && update.stateSequence !== undefined) {
            consecutiveRetryCount = 0;
            armSilenceTimer();
          }
        } catch {
          // Ignore malformed or forward-incompatible events; REST remains the fallback.
        }
      });
      currentSocket.addEventListener('close', handleClose);
      currentSocket.addEventListener('error', () => currentSocket.close());
    };

    connect();
    return () => {
      disposed = true;
      if (reconnectTimer !== null) window.clearTimeout(reconnectTimer);
      if (silenceTimer !== null) window.clearTimeout(silenceTimer);
      socket?.close();
    };
  }, [enabled]);

  return { connectionState, snapshot };
}
