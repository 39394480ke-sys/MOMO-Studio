import { Cable, CircleStop, PlugZap, RefreshCw, TriangleAlert } from 'lucide-react';

import { PageIntro } from '../components/PageIntro';
import { useRuntimeStatus } from '../components/runtimeStatusContext';

function formatUpdatedAt(value: string | undefined): string {
  if (!value) return 'Waiting for backend';
  return new Intl.DateTimeFormat(undefined, {
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  }).format(new Date(value));
}

export function ControlPage() {
  const {
    backend,
    stale,
    robot,
    profile,
    calibration,
    error,
    pendingAction,
    refresh,
    connect,
    disconnect,
    stop,
  } = useRuntimeStatus();
  const busy = pendingAction !== null;
  const online = backend === 'connected';
  const jointOrder = profile?.profile.enabled_joints ?? Object.keys(robot?.positions ?? {});
  const jointDefinitions = Object.fromEntries(
    (profile?.profile.joint_definitions ?? []).map((definition) => [
      definition.joint_id,
      definition,
    ]),
  );

  return (
    <div className="page">
      <PageIntro
        title="Control"
        description="Stage 2: Motion controls are not enabled yet."
        detail="Dry Run connection and read-only joint state."
      />

      {(error || stale) && (
        <div className="runtime-alert" role="alert">
          <TriangleAlert aria-hidden="true" />
          <div>
            <strong>{stale ? 'Backend unavailable · showing stale state' : 'Request failed'}</strong>
            {error && <span>{error}</span>}
          </div>
          <button aria-label="Retry backend request" onClick={() => void refresh()} type="button">
            <RefreshCw aria-hidden="true" />
          </button>
        </div>
      )}

      <section className="control-section" aria-labelledby="active-robot-title">
        <div className="section-heading">
          <div>
            <p className="section-kicker">Active Robot</p>
            <h2 id="active-robot-title">{robot ? `${robot.robot_id} · ${robot.variant}` : 'Loading'}</h2>
          </div>
          <div className={`connection-state connection-state--${robot?.connection_state.toLowerCase() ?? 'pending'}`}>
            <span aria-hidden="true" />
            {robot?.connection_state ?? 'PENDING'}
          </div>
        </div>

        <dl className="runtime-facts">
          <div>
            <dt>Mode</dt>
            <dd>{robot?.control_mode ?? 'DRY_RUN'}</dd>
          </div>
          <div>
            <dt>Profile</dt>
            <dd>{robot?.profile_verification_status ?? 'Pending'}</dd>
          </div>
          <div>
            <dt>Calibration</dt>
            <dd>{calibration?.status ?? robot?.calibration_status ?? 'Pending'}</dd>
          </div>
          <div>
            <dt>Updated</dt>
            <dd>{formatUpdatedAt(robot?.updated_at)}</dd>
          </div>
        </dl>

        <div className="command-bar" aria-label="Dry Run connection controls">
          <button
            className="command-button command-button--primary"
            disabled={!online || busy || robot?.connected === true}
            onClick={() => void connect()}
            type="button"
          >
            <PlugZap aria-hidden="true" />
            {pendingAction === 'connect' ? 'Connecting' : 'Connect'}
          </button>
          <button
            className="command-button"
            disabled={!online || busy || robot?.connected !== true}
            onClick={() => void disconnect()}
            type="button"
          >
            <Cable aria-hidden="true" />
            {pendingAction === 'disconnect' ? 'Disconnecting' : 'Disconnect'}
          </button>
          <button
            className="command-button command-button--stop"
            disabled={!online || busy}
            onClick={() => void stop()}
            type="button"
          >
            <CircleStop aria-hidden="true" />
            {pendingAction === 'stop' ? 'Stopping' : 'Stop'}
          </button>
        </div>
      </section>

      <section className="control-section" aria-labelledby="joint-state-title">
        <div className="section-heading section-heading--compact">
          <div>
            <p className="section-kicker">Telemetry</p>
            <h2 id="joint-state-title">Joint State</h2>
          </div>
          <span className="read-only-label">Read only</span>
        </div>
        {robot ? (
          <div className="joint-grid">
            {jointOrder.map((jointId) => (
              <article className="joint-card" key={jointId}>
                <div>
                  <span className="joint-card__id">{jointId.toUpperCase()}</span>
                  <span className="joint-card__type">
                    {jointDefinitions[jointId]?.joint_type === 'PRISMATIC'
                      ? 'Linear rail'
                      : 'Revolute'}
                  </span>
                </div>
                <p>
                  <strong>{robot.positions[jointId].toFixed(2)}</strong>
                  <span>{robot.units[jointId]}</span>
                </p>
              </article>
            ))}
          </div>
        ) : (
          <p className="empty-state">Joint state will appear when the backend is available.</p>
        )}
      </section>
    </div>
  );
}
