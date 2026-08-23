import { useRuntimeStatus } from './runtimeStatusContext';

export function StatusHeader() {
  const { backend, controlMode, robot, stale } = useRuntimeStatus();
  const backendLabel =
    backend === 'connected'
      ? stale
        ? 'Backend stale'
        : 'Backend connected'
      : 'Backend unavailable';

  return (
    <header className="status-header" aria-label="System status">
      <div className={`status-item status-item--backend status-item--${backend}`} role="status">
        <span className="status-dot" aria-hidden="true" />
        <span>{backendLabel}</span>
      </div>
      <div className="status-item status-item--mode">
        <span className="status-dot" aria-hidden="true" />
        <span>{controlMode}</span>
      </div>
      <div className="status-item status-item--robot">
        <span className="status-dot" aria-hidden="true" />
        <span>{robot ? `${robot.robot_id} · ${robot.variant}` : 'Active robot pending'}</span>
      </div>
      <div className="status-item status-item--locked">
        <span className="status-dot" aria-hidden="true" />
        <span>Real motion disabled</span>
      </div>
    </header>
  );
}
