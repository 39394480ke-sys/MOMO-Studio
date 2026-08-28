import { Cable, CircleStop, PlugZap } from 'lucide-react';

import type { RobotStatus, RobotWebSocketState } from '../../api/types';
import type { MotionAvailability } from './controlTypes';

interface ControlSafetyBarProps {
  backendOnline: boolean;
  stale: boolean;
  robot: RobotStatus | null;
  lifecyclePending: 'connect' | 'disconnect' | 'stop' | 'switch' | null;
  lifecycleAllowed: boolean;
  stopAllowed: boolean;
  modeLabel: 'DRY RUN' | 'READ ONLY' | 'REAL MOTION LOCKED' | 'REAL CAPABILITY AUTHORIZED';
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
  lifecycleAllowed,
  stopAllowed,
  modeLabel,
  motionPending,
  availability,
  socketState,
  onConnect,
  onDisconnect,
  onStop,
}: ControlSafetyBarProps) {
  const lifecycleBusy = lifecyclePending !== null;
  const stopDisabled = !stopAllowed;
  return (
    <section className="control-safety-bar" aria-label="运行安全控制">
      <div className="control-safety-bar__status">
        <span className="dry-run-badge">{modeLabel}</span>
        <span>{availability.allowed ? '运动已就绪' : availability.reason}</span>
        <span>实时状态：{socketState === 'open' ? 'WebSocket' : 'REST 备用通道'}</span>
      </div>
      <div className="command-bar">
        <button
          className="command-button command-button--primary"
          disabled={!lifecycleAllowed || !backendOnline || stale || lifecycleBusy || robot?.connected === true}
          onClick={() => void onConnect()}
          type="button"
        >
          <PlugZap aria-hidden="true" />
          {lifecyclePending === 'connect' ? '连接中' : '连接'}
        </button>
        <button
          className="command-button"
          disabled={!lifecycleAllowed || !backendOnline || stale || lifecycleBusy || robot?.connected !== true}
          onClick={() => void onDisconnect()}
          type="button"
        >
          <Cable aria-hidden="true" />
          {lifecyclePending === 'disconnect' ? '断开中' : '断开连接'}
        </button>
        <button
          className="command-button command-button--stop control-global-stop"
          disabled={stopDisabled}
          onClick={() => void onStop()}
          type="button"
        >
          <CircleStop aria-hidden="true" />
          {motionPending === 'stop' ? '停止中' : '停止运动'}
        </button>
      </div>
      <p className="software-stop-note">
        软件停止不能替代物理急停按钮。
      </p>
    </section>
  );
}
