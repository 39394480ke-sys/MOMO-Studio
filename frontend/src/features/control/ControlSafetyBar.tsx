import { Cable, CircleStop, PlugZap } from 'lucide-react';

import type { RobotStatus, RobotWebSocketState } from '../../api/types';
import type { MotionAvailability } from './controlTypes';

interface ControlSafetyBarProps {
  backendOnline: boolean;
  stale: boolean;
  robot: RobotStatus | null;
  lifecyclePending: 'connect' | 'disconnect' | 'stop' | 'switch' | null;
  motionPending: string | null;
  availability: MotionAvailability;
  socketState: RobotWebSocketState;
  onConnect: () => Promise<void>;
  onDisconnect: () => Promise<void>;
  onStop: () => Promise<void>;
}

export function ControlSafetyBar({
  backendOnline,
  stale,
  robot,
  lifecyclePending,
  motionPending,
  availability,
  socketState,
  onConnect,
  onDisconnect,
  onStop,
}: ControlSafetyBarProps) {
  const lifecycleBusy = lifecyclePending !== null;
  const stopDisabled = !backendOnline || stale || motionPending === 'stop';
  return (
    <section className="control-safety-bar" aria-label="Dry Run safety controls">
      <div className="control-safety-bar__status">
        <span className="dry-run-badge">DRY RUN</span>
        <span>{availability.allowed ? 'Motion ready' : availability.reason}</span>
        <span>Live status: {socketState === 'open' ? 'WebSocket' : 'REST fallback'}</span>
      </div>
      <div className="command-bar">
        <button
          className="command-button command-button--primary"
          disabled={!backendOnline || stale || lifecycleBusy || robot?.connected === true}
          onClick={() => void onConnect()}
          type="button"
        >
          <PlugZap aria-hidden="true" />
          {lifecyclePending === 'connect' ? 'Connecting' : 'Connect'}
        </button>
        <button
          className="command-button"
          disabled={!backendOnline || stale || lifecycleBusy || robot?.connected !== true}
          onClick={() => void onDisconnect()}
          type="button"
        >
          <Cable aria-hidden="true" />
          {lifecyclePending === 'disconnect' ? 'Disconnecting' : 'Disconnect'}
        </button>
        <button
          className="command-button command-button--stop control-global-stop"
          disabled={stopDisabled}
          onClick={() => void onStop()}
          type="button"
        >
          <CircleStop aria-hidden="true" />
          {motionPending === 'stop' ? 'Stopping' : 'STOP MOTION'}
        </button>
      </div>
      <p className="software-stop-note">
        Software Stop cancels Dry Run motion. It is not a physical emergency stop.
      </p>
    </section>
  );
}
