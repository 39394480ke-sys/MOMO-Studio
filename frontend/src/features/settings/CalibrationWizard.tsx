import { CircleAlert, RotateCcw, Save, ShieldCheck } from 'lucide-react';
import { useMemo, useState } from 'react';

import {
  ApiError,
  cancelCalibrationSession,
  completeCalibrationSession,
  confirmCalibrationJoint,
  previewCalibrationJoint,
  readCalibrationJoint,
  startCalibrationSession,
} from '../../api/client';
import type {
  CalibrationJointPreview,
  CalibrationRevisionSummary,
  CalibrationWorkflowStatus,
} from '../../api/types';

const JOINT_CONFIRMATION = 'CONFIRM CALIBRATION JOINT';
const SAVE_CONFIRMATION = 'SAVE CALIBRATION';

function errorMessage(error: unknown): string {
  if (error instanceof ApiError || error instanceof Error) return error.message;
  return 'The protected calibration request failed.';
}

function integerOrNull(value: string): number | null {
  if (!/^-?\d+$/.test(value.trim())) return null;
  const result = Number(value);
  return Number.isSafeInteger(result) ? result : null;
}

interface CalibrationWizardProps {
  connected: boolean;
  initiallyConfigured: boolean;
  operatorToken: string;
  onSessionInvalidated?: () => void;
  onStatusChange?: (status: 'NOT_CONFIGURED' | 'DRAFT' | 'CONFIGURED') => void;
}

export function CalibrationWizard({
  connected,
  initiallyConfigured,
  operatorToken,
  onSessionInvalidated,
  onStatusChange,
}: CalibrationWizardProps) {
  const [status, setStatus] = useState<CalibrationWorkflowStatus | null>(null);
  const [selectedJoint, setSelectedJoint] = useState('');
  const [logicalValue, setLogicalValue] = useState('');
  const [direction, setDirection] = useState<-1 | 1>(1);
  const [phase, setPhase] = useState('');
  const [rawLower, setRawLower] = useState('');
  const [rawUpper, setRawUpper] = useState('');
  const [preview, setPreview] = useState<CalibrationJointPreview | null>(null);
  const [jointConfirmation, setJointConfirmation] = useState('');
  const [saveConfirmation, setSaveConfirmation] = useState('');
  const [saved, setSaved] = useState<CalibrationRevisionSummary | null>(null);
  const [pending, setPending] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const selectedConfirmed = Boolean(
    selectedJoint && status?.confirmed_joint_ids.includes(selectedJoint),
  );
  const canPreview = useMemo(() => {
    const logical = Number(logicalValue);
    const lower = integerOrNull(rawLower);
    const upper = integerOrNull(rawUpper);
    const parsedPhase = phase.trim() === '' ? null : integerOrNull(phase);
    return status?.observed_raw !== null && status?.selected_joint_id === selectedJoint &&
      Number.isFinite(logical) && logicalValue.trim() !== '' && lower !== null &&
      upper !== null && lower < upper && (phase.trim() === '' || parsedPhase !== null);
  }, [logicalValue, phase, rawLower, rawUpper, selectedJoint, status]);

  const run = async (name: string, action: () => Promise<void>) => {
    setPending(name);
    setError(null);
    try {
      await action();
    } catch (requestError) {
      setError(errorMessage(requestError));
    } finally {
      setPending(null);
    }
  };

  const selectDraftJoint = (next: CalibrationWorkflowStatus, jointId: string) => {
    const draft = next.draft.joints.find((joint) => joint.joint_id === jointId);
    setSelectedJoint(jointId);
    setLogicalValue(draft?.logical_value === null || draft?.logical_value === undefined
      ? ''
      : String(draft.logical_value));
    setDirection(draft?.direction ?? 1);
    setPhase(draft?.phase === null || draft?.phase === undefined ? '' : String(draft.phase));
    setRawLower(draft?.raw_bounds ? String(draft.raw_bounds[0]) : '');
    setRawUpper(draft?.raw_bounds ? String(draft.raw_bounds[1]) : '');
  };

  const start = () => run('start', async () => {
    const next = await startCalibrationSession(operatorToken);
    setStatus(next);
    selectDraftJoint(next, next.required_joint_ids[0] ?? '');
    setPreview(null);
    setSaved(null);
    onStatusChange?.('DRAFT');
  });

  const read = () => run('read', async () => {
    if (!status || !selectedJoint) return;
    const next = await readCalibrationJoint(operatorToken, status.session_id, selectedJoint);
    setStatus(next);
    setPreview(null);
    setJointConfirmation('');
  });

  const createPreview = () => run('preview', async () => {
    if (!status || !selectedJoint) return;
    const lower = integerOrNull(rawLower);
    const upper = integerOrNull(rawUpper);
    const parsedPhase = phase.trim() === '' ? null : integerOrNull(phase);
    if (lower === null || upper === null || (phase.trim() !== '' && parsedPhase === null)) return;
    const next = await previewCalibrationJoint(operatorToken, status.session_id, {
      joint_id: selectedJoint,
      logical_value: Number(logicalValue),
      direction,
      phase: parsedPhase,
      raw_bounds: [lower, upper],
    });
    setPreview(next);
    setJointConfirmation('');
  });

  const confirm = () => run('confirm', async () => {
    if (!status || !preview) return;
    const next = await confirmCalibrationJoint(
      operatorToken,
      status.session_id,
      preview.joint_id,
      preview.preview_fingerprint,
      jointConfirmation,
    );
    setStatus(next);
    setPreview(null);
    setJointConfirmation('');
  });

  const complete = () => run('complete', async () => {
    if (!status?.save_preview) return;
    const revision = await completeCalibrationSession(
      operatorToken,
      status.session_id,
      status.save_preview.proposed_calibration_fingerprint,
      saveConfirmation,
    );
    setSaved(revision);
    setStatus(null);
    setPreview(null);
    onStatusChange?.('CONFIGURED');
    onSessionInvalidated?.();
  });

  const cancel = () => run('cancel', async () => {
    if (status) await cancelCalibrationSession(operatorToken, status.session_id);
    setStatus(null);
    setPreview(null);
    setSaveConfirmation('');
    onStatusChange?.(initiallyConfigured ? 'CONFIGURED' : 'NOT_CONFIGURED');
  });

  if (saved) {
    return (
      <section className="calibration-wizard" aria-labelledby="calibration-wizard-title">
        <div className="calibration-wizard__complete" role="status">
          <ShieldCheck aria-hidden="true" />
          <div>
            <h3 id="calibration-wizard-title">Calibration revision saved</h3>
            <p>Revision {saved.revision} · {saved.variant}</p>
            <p>Calibration configured · Field acceptance pending · Real motion blocked</p>
            <code>{saved.calibration_fingerprint}</code>
          </div>
        </div>
        <button className="command-button" onClick={() => setSaved(null)} type="button">
          Close summary
        </button>
      </section>
    );
  }

  if (!status) {
    return (
      <section className="calibration-wizard" aria-labelledby="calibration-wizard-title">
        <div>
          <p className="section-kicker">Protected · selected-joint reads only</p>
          <h3 id="calibration-wizard-title">Current-angle Calibration Wizard</h3>
          <strong>{initiallyConfigured ? 'Calibration configured' : 'Not configured'}</strong>
          <p>
            The wizard never moves a joint, writes a servo, changes mode, scans IDs, or
            promotes an example calibration. It requires the current explicit connection.
          </p>
        </div>
        <button
          className="command-button"
          disabled={!connected || pending !== null}
          onClick={() => void start()}
          type="button"
        >
          {initiallyConfigured ? 'Start protected recalibration' : 'Start initial calibration'}
        </button>
        {!connected && <small>Explicitly connect and verify diagnostics first.</small>}
        {error && <p className="real-inline-error" role="alert">{error}</p>}
      </section>
    );
  }

  return (
    <section className="calibration-wizard" aria-labelledby="calibration-wizard-title">
      <div className="settings-section__heading settings-section__heading--inline">
        <div>
          <p className="section-kicker">
            Draft · {status.base_revision === null
              ? 'Initial calibration → Revision 1'
              : `Revision ${status.base_revision} → ${status.base_revision + 1}`}
          </p>
          <h3 id="calibration-wizard-title">Current-angle Calibration Wizard</h3>
        </div>
        <button className="command-button" disabled={pending !== null} onClick={() => void cancel()} type="button">
          Cancel
        </button>
      </div>

      <div className="calibration-wizard__warning">
        <CircleAlert aria-hidden="true" />
        <p>Keep the physical E-stop reachable. Reading a selected position is not a motion command.</p>
      </div>

      {error && <p className="real-inline-error" role="alert">{error}</p>}

      <div className="calibration-wizard__progress" aria-label="Calibration joint progress">
        {status.required_joint_ids.map((jointId) => (
          <span className={status.confirmed_joint_ids.includes(jointId) ? 'is-confirmed' : ''} key={jointId}>
            {jointId.toUpperCase()}
          </span>
        ))}
      </div>

      <div className="calibration-wizard__form">
        <label>
          <span>Selected joint</span>
          <select
            disabled={pending !== null}
            onChange={(event) => {
              selectDraftJoint(status, event.target.value);
              setStatus((current) => current ? {
                ...current,
                selected_joint_id: null,
                observed_raw: null,
                preview: null,
              } : current);
              setPreview(null);
              setJointConfirmation('');
            }}
            value={selectedJoint}
          >
            {status.required_joint_ids.map((jointId) => (
              <option key={jointId} value={jointId}>{jointId.toUpperCase()}</option>
            ))}
          </select>
        </label>
        <div className="calibration-wizard__read">
          <span>Present raw</span>
          <strong>{status.selected_joint_id === selectedJoint && status.observed_raw !== null
            ? status.observed_raw
            : 'Not read'}</strong>
          <button className="command-button" disabled={!selectedJoint || pending !== null} onClick={() => void read()} type="button">
            Read selected joint
          </button>
        </div>
        <label>
          <span>Current logical value</span>
          <input disabled={pending !== null} inputMode="decimal" onChange={(event) => setLogicalValue(event.target.value)} value={logicalValue} />
        </label>
        <label>
          <span>Direction</span>
          <select disabled={pending !== null} onChange={(event) => setDirection(event.target.value === '-1' ? -1 : 1)} value={direction}>
            <option value={1}>+1</option>
            <option value={-1}>−1</option>
          </select>
        </label>
        <label>
          <span>Multi-turn phase (when required)</span>
          <input disabled={pending !== null} inputMode="numeric" onChange={(event) => setPhase(event.target.value)} value={phase} />
        </label>
        <label>
          <span>Raw lower bound</span>
          <input disabled={pending !== null} inputMode="numeric" onChange={(event) => setRawLower(event.target.value)} value={rawLower} />
        </label>
        <label>
          <span>Raw upper bound</span>
          <input disabled={pending !== null} inputMode="numeric" onChange={(event) => setRawUpper(event.target.value)} value={rawUpper} />
        </label>
      </div>

      <button className="command-button" disabled={!canPreview || pending !== null} onClick={() => void createPreview()} type="button">
        Preview mapping
      </button>

      {preview && (
        <div className="calibration-preview">
          <h4>Selected-joint mapping preview</h4>
          <dl>
            <div><dt>Joint / Servo</dt><dd>{preview.joint_id.toUpperCase()} / {preview.servo_id}</dd></div>
            <div><dt>Raw → logical</dt><dd>{preview.observed_raw} → {preview.logical_value} {preview.unit}</dd></div>
            <div><dt>Direction / Home</dt><dd>{preview.direction > 0 ? '+1' : '−1'} / {preview.home_present_raw}</dd></div>
            <div><dt>Phase / bounds</dt><dd>{preview.phase ?? 'N/A'} / {preview.raw_bounds.join('…')}</dd></div>
            <div><dt>Round trip</dt><dd>{preview.round_trip_logical_value} {preview.unit}</dd></div>
            <div><dt>Mapping error</dt><dd>{preview.mapping_error}</dd></div>
          </dl>
          <label className="real-confirmation-field">
            <span>Type the exact joint confirmation</span>
            <code>{JOINT_CONFIRMATION}</code>
            <input
              aria-label="Type the exact joint confirmation"
              autoComplete="off"
              disabled={pending !== null}
              onChange={(event) => setJointConfirmation(event.target.value)}
              value={jointConfirmation}
            />
          </label>
          <button
            className="command-button"
            disabled={jointConfirmation !== JOINT_CONFIRMATION || pending !== null}
            onClick={() => void confirm()}
            type="button"
          >
            Confirm this joint only
          </button>
        </div>
      )}

      {selectedConfirmed && !preview && <p className="calibration-wizard__confirmed">Selected joint confirmed for this revision.</p>}

      {status.state === 'READY_TO_SAVE' && (
        <div className="calibration-save">
          <h4>Complete calibration preview</h4>
          <p>
            All {status.required_joint_ids.length} enabled joints are confirmed. Saving creates
            a new atomic revision and backs up the previous revision; no servo write occurs.
          </p>
          {status.save_preview ? (
            <>
              <div className="real-table-wrap">
                <table className="real-diagnostics-table">
                  <caption>Complete proposed calibration mapping</caption>
                  <thead>
                    <tr><th>Joint</th><th>Servo</th><th>Mode</th><th>Direction</th><th>Home</th><th>Phase</th><th>Raw bounds</th></tr>
                  </thead>
                  <tbody>
                    {status.save_preview.joints.map((joint) => (
                      <tr key={joint.joint_id}>
                        <th scope="row">{joint.joint_id.toUpperCase()}</th>
                        <td>{joint.servo_id}</td>
                        <td>{joint.operating_mode}</td>
                        <td>{joint.direction > 0 ? '+1' : '−1'}</td>
                        <td>{joint.home_present_raw}</td>
                        <td>{joint.phase ?? 'N/A'}</td>
                        <td>{joint.raw_bounds.join('…')}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <span>Proposed calibration fingerprint</span>
              <code>{status.save_preview.proposed_calibration_fingerprint}</code>
            </>
          ) : (
            <p className="real-inline-error" role="alert">
              The backend did not provide a complete save preview. Saving is blocked.
            </p>
          )}
          <label className="real-confirmation-field">
            <span>Type the exact save confirmation</span>
            <code>{SAVE_CONFIRMATION}</code>
            <input
              aria-label="Type the exact save confirmation"
              autoComplete="off"
              disabled={pending !== null}
              onChange={(event) => setSaveConfirmation(event.target.value)}
              value={saveConfirmation}
            />
          </label>
          <button
            className="command-button command-button--danger-solid"
            disabled={
              !status.save_preview ||
              saveConfirmation !== SAVE_CONFIRMATION ||
              pending !== null
            }
            onClick={() => void complete()}
            type="button"
          >
            <Save aria-hidden="true" /> Save new calibration revision
          </button>
        </div>
      )}

      <footer className="calibration-wizard__footer">
        <RotateCcw aria-hidden="true" />
        Rollback is a separate, exact-confirmation operation and always creates a forward revision.
      </footer>
    </section>
  );
}
