import { useRuntimeStatus } from './runtimeStatusContext';

export function StatusHeader() {
  const {
    backend,
    controlMode,
    hardwareAccessPolicy,
    realMotionEnabled,
    robot,
    stale,
  } = useRuntimeStatus();
  const backendLabel =
    backend === 'connected'
      ? stale
        ? '后端状态已过期'
        : '后端已连接'
      : '后端不可用';
  const modeLabel = controlMode === 'DRY RUN'
    ? 'DRY RUN'
    : hardwareAccessPolicy === 'READ_ONLY'
      ? 'COMMISSIONING · READ ONLY'
      : hardwareAccessPolicy === 'FULL'
        ? 'REAL · FULL'
        : 'REAL · 硬件禁用';
  const motionLabel = controlMode === 'DRY RUN' || hardwareAccessPolicy === 'DISABLED'
    ? '真实运动已禁用'
    : hardwareAccessPolicy === 'READ_ONLY'
      ? '投产只读 · 禁止运动'
      : realMotionEnabled
        ? '真实运动需 REAL_MOTION 会话'
        : '真实运动未启用';

  return (
    <header className="status-header" aria-label="系统状态">
      <div className={`status-item status-item--backend status-item--${backend}`} role="status">
        <span className="status-dot" aria-hidden="true" />
        <span>{backendLabel}</span>
      </div>
      <div className="status-item status-item--mode">
        <span className="status-dot" aria-hidden="true" />
        <span>{modeLabel}</span>
      </div>
      <div className="status-item status-item--robot">
        <span className="status-dot" aria-hidden="true" />
        <span>{robot ? `${robot.robot_id} · ${robot.variant}` : '等待活动机器人'}</span>
      </div>
      <div className="status-item status-item--locked">
        <span className="status-dot" aria-hidden="true" />
        <span>{motionLabel}</span>
      </div>
    </header>
  );
}
