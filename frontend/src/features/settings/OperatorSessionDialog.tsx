import { ShieldAlert, X } from 'lucide-react';
import { useEffect, useRef, useState } from 'react';

import type { DeviceConfirmationEvidence } from '../../api/types';

interface OperatorSessionDialogProps {
  evidence: DeviceConfirmationEvidence;
  pending: boolean;
  error: string | null;
  onCancel: () => void;
  onConfirm: (confirmationText: string, physicalEstopConfirmed: boolean) => void;
}

function EvidenceValue({ value }: { value: string | null }) {
  return <code>{value ?? 'Not configured'}</code>;
}

export function OperatorSessionDialog({
  evidence,
  pending,
  error,
  onCancel,
  onConfirm,
}: OperatorSessionDialogProps) {
  const [confirmationText, setConfirmationText] = useState('');
  const [physicalEstopConfirmed, setPhysicalEstopConfirmed] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    inputRef.current?.focus();
  }, []);

  const canConfirm =
    confirmationText === evidence.required_confirmation_text &&
    physicalEstopConfirmed &&
    !pending;
  const commissioning = evidence.session_purpose === 'COMMISSIONING_READ_ONLY';

  return (
    <div className="real-dialog-backdrop" role="presentation">
      <section
        aria-describedby="operator-session-description"
        aria-labelledby="operator-session-title"
        aria-modal="true"
        className="real-dialog"
        role="dialog"
      >
        <div className="real-dialog__header">
          <div>
            <p className="section-kicker">Short-lived authorization · {evidence.session_purpose}</p>
            <h2 id="operator-session-title">
              {commissioning ? 'Open READ ONLY Commissioning Session' : 'Open Real Motion Session'}
            </h2>
          </div>
          <button
            aria-label="Close Operator Session dialog"
            className="icon-button"
            disabled={pending}
            onClick={onCancel}
            type="button"
          >
            <X aria-hidden="true" />
          </button>
        </div>

        <div className="real-dialog__warning" id="operator-session-description">
          <ShieldAlert aria-hidden="true" />
          <p>
            {commissioning
              ? 'This session can read only the configured Servo IDs for diagnostics and calibration. It cannot move, Home, scan, change torque, or write registers.'
              : 'This is software motion authorization, not a physical emergency stop. Keep the physical E-stop reachable and the robot workspace clear.'}
          </p>
        </div>

        <dl className="real-evidence-grid">
          <div><dt>Robot</dt><dd><EvidenceValue value={evidence.robot_id} /></dd></div>
          <div><dt>Purpose</dt><dd>{evidence.session_purpose}</dd></div>
          <div><dt>Variant</dt><dd>{evidence.variant ?? 'Not configured'}</dd></div>
          <div><dt>Profile</dt><dd><EvidenceValue value={evidence.profile_fingerprint} /></dd></div>
          <div><dt>Calibration</dt><dd><EvidenceValue value={evidence.calibration_fingerprint} /></dd></div>
          <div><dt>Kinematics</dt><dd><EvidenceValue value={evidence.kinematics_fingerprint} /></dd></div>
          <div><dt>Serial</dt><dd><EvidenceValue value={evidence.masked_serial_port} /></dd></div>
          <div><dt>Servo IDs</dt><dd>{evidence.masked_servo_ids.join(', ') || 'Not configured'}</dd></div>
          <div><dt>Protocol</dt><dd><EvidenceValue value={evidence.protocol} /></dd></div>
        </dl>

        <label className="real-confirmation-field">
          <span>Type the exact confirmation text</span>
          <code>{evidence.required_confirmation_text}</code>
          <input
            autoComplete="off"
            disabled={pending}
            onChange={(event) => setConfirmationText(event.target.value)}
            ref={inputRef}
            spellCheck={false}
            value={confirmationText}
          />
        </label>

        <label className="real-estop-check">
          <input
            checked={physicalEstopConfirmed}
            disabled={pending}
            onChange={(event) => setPhysicalEstopConfirmed(event.target.checked)}
            type="checkbox"
          />
          <span>I confirm a tested physical E-stop is present and reachable.</span>
        </label>

        {error && <p className="real-inline-error" role="alert">{error}</p>}

        <div className="real-dialog__actions">
          <button className="command-button" disabled={pending} onClick={onCancel} type="button">
            Cancel
          </button>
          <button
            className="command-button command-button--danger-solid"
            disabled={!canConfirm}
            onClick={() => onConfirm(confirmationText, physicalEstopConfirmed)}
            type="button"
          >
            {pending
              ? 'Authorizing…'
              : commissioning
                ? 'Authorize READ ONLY session'
                : 'Authorize Real Motion session'}
          </button>
        </div>
      </section>
    </div>
  );
}
