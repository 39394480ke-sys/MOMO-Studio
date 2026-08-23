import { Check, CircleAlert, Clock3, TriangleAlert } from 'lucide-react';

import type { MotionCommandStatus, MotionPreflightReport } from '../../api/types';

interface CommandStatusPanelProps {
  command: MotionCommandStatus | null;
  commandError: string | null;
  fkError: string | null;
  robotError: string | null;
  rejectedPreflight: MotionPreflightReport | null;
}

function PreflightEvidence({ preflight }: { preflight: MotionPreflightReport }) {
  return (
    <div className="preflight-report">
      <strong>{preflight.accepted ? 'Preflight accepted' : 'Preflight rejected'}</strong>
      <ul>
        {preflight.checks.map((check, index) => (
          <li
            className={check.passed ? 'preflight-check--passed' : 'preflight-check--failed'}
            key={`${check.name}:${index}`}
          >
            {check.passed ? <Check aria-hidden="true" /> : <TriangleAlert aria-hidden="true" />}
            <span><strong>{check.name}</strong> {check.detail}</span>
          </li>
        ))}
      </ul>
      {preflight.warnings.length > 0 ? <p>{preflight.warnings.join(' · ')}</p> : null}
    </div>
  );
}

export function CommandStatusPanel({
  command,
  commandError,
  fkError,
  robotError,
  rejectedPreflight,
}: CommandStatusPanelProps) {
  const preflight = command?.preflight;
  return (
    <section className="control-panel control-panel--command" aria-labelledby="command-status-title">
      <div className="section-heading section-heading--compact">
        <div>
          <p className="section-kicker">Command / Preflight</p>
          <h2 id="command-status-title">Execution status</h2>
        </div>
        <span className={`command-state command-state--${command?.state.toLowerCase() ?? 'idle'}`}>
          {command?.state ?? 'IDLE'}
        </span>
      </div>

      {command ? (
        <div className="command-status-body" role="status">
          <code>{command.command_id}</code>
          <div className="command-progress" aria-label="Command progress">
            <span style={{ width: `${Math.max(0, Math.min(1, command.progress ?? 0)) * 100}%` }} />
          </div>
          <p>{Math.round((command.progress ?? 0) * 100)}% {command.message ?? ''}</p>
          {preflight ? (
            <PreflightEvidence preflight={preflight} />
          ) : (
            <p className="inline-status"><Clock3 aria-hidden="true" /> Waiting for preflight evidence.</p>
          )}
          {command.error ? <p className="motion-error"><CircleAlert aria-hidden="true" /> {command.error}</p> : null}
        </div>
      ) : (
        <p className="empty-state">No motion command has been submitted in this session.</p>
      )}

      {rejectedPreflight ? <PreflightEvidence preflight={rejectedPreflight} /> : null}

      {[commandError, fkError, robotError].filter(Boolean).map((error) => (
        <p className="motion-error" key={error} role="alert"><CircleAlert aria-hidden="true" /> {error}</p>
      ))}
    </section>
  );
}
