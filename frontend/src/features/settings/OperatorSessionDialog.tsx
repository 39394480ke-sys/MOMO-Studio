import { ShieldAlert, X } from 'lucide-react';
import { useEffect, useRef, useState } from 'react';

import type { DeviceConfirmationEvidence } from '../../api/types';

interface OperatorSessionDialogProps {
  evidence: DeviceConfirmationEvidence;
  pending: boolean;
  error: string | null;
  onCancel: () => void;
  onConfirm: (
    confirmationText: string,
    physicalEstopConfirmed: boolean,
    workspaceClearConfirmed: boolean,
  ) => void;
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
  const [workspaceClearConfirmed, setWorkspaceClearConfirmed] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (evidence.session_purpose !== 'RAW_DIRECTION_TEST') inputRef.current?.focus();
  }, [evidence.session_purpose]);

  const commissioning = evidence.session_purpose === 'COMMISSIONING_READ_ONLY';
  const commissioningMotion = evidence.session_purpose === 'COMMISSIONING_MOTION_TEST';
  const rawDirection = evidence.session_purpose === 'RAW_DIRECTION_TEST';
  const canConfirm = rawDirection
    ? physicalEstopConfirmed && workspaceClearConfirmed && !pending
    : confirmationText === evidence.required_confirmation_text &&
      physicalEstopConfirmed &&
      (!evidence.workspace_clear_required || workspaceClearConfirmed) &&
      !pending;

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
            <p className="section-kicker">
              {rawDirection ? '一次确认 · 约 15 分钟连续验收' : `Short-lived authorization · ${evidence.session_purpose}`}
            </p>
            <h2 id="operator-session-title">
              {commissioning
                ? 'Open READ ONLY Commissioning Session'
                : commissioningMotion
                  ? 'Open Commissioning Motion Test Session'
                  : rawDirection
                    ? '开始六轴 Raw ± 方向验收'
                  : 'Open Real Motion Session'}
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
              : commissioningMotion
                ? 'This session permits only backend-bounded, low-speed, single-joint commissioning tests. It cannot Home, move multiple joints, run Cartesian motion, Playback, or Vision Follow.'
                : rawDirection
                  ? '确认一次后，系统会在同一会话中读取六轴零点并依次验收 J10–J15。每次只允许一个关节在零点附近小步运动，松手立即停止。'
                : 'This is software motion authorization, not a physical emergency stop. Keep the physical E-stop reachable and the robot workspace clear.'}
          </p>
        </div>

        {rawDirection ? (
          <>
            <div className="raw-session-summary" aria-label="方向验收设备摘要">
              <div><span>机械臂</span><strong>{evidence.robot_unit_id ?? '未配置'}</strong></div>
              <div><span>型号</span><strong>{evidence.variant ?? '未配置'}</strong></div>
              <div><span>舵机</span><strong>{evidence.masked_servo_ids.join(', ') || '未配置'}</strong></div>
              <div><span>协议</span><strong>{evidence.protocol ?? '未配置'}</strong></div>
            </div>
            <label className="real-estop-check real-estop-check--combined">
              <input
                checked={physicalEstopConfirmed && workspaceClearConfirmed}
                disabled={pending}
                onChange={(event) => {
                  setPhysicalEstopConfirmed(event.target.checked);
                  setWorkspaceClearConfirmed(event.target.checked);
                }}
                type="checkbox"
              />
              <span>急停已就位、空间已清空，并且当前实体姿态与 URDF 初始姿态一致。</span>
            </label>
            <details className="raw-technical-details">
              <summary>查看技术身份</summary>
              <dl className="real-evidence-grid">
                <div><dt>Profile</dt><dd><EvidenceValue value={evidence.profile_fingerprint} /></dd></div>
                <div><dt>Serial</dt><dd><EvidenceValue value={evidence.masked_serial_port} /></dd></div>
                <div><dt>Purpose</dt><dd>{evidence.session_purpose}</dd></div>
                <div><dt>Confirmation</dt><dd><code>{evidence.required_confirmation_text}</code></dd></div>
              </dl>
            </details>
          </>
        ) : (
          <>
            <dl className="real-evidence-grid">
              <div><dt>Robot</dt><dd><EvidenceValue value={evidence.robot_id} /></dd></div>
              <div><dt>Robot unit</dt><dd><EvidenceValue value={evidence.robot_unit_id ?? null} /></dd></div>
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
          </>
        )}

        {!rawDirection && evidence.workspace_clear_required && (
          <label className="real-estop-check">
            <input
              checked={workspaceClearConfirmed}
              disabled={pending}
              onChange={(event) => setWorkspaceClearConfirmed(event.target.checked)}
              type="checkbox"
            />
            <span>I confirm the robot workspace is clear and guarded for this test.</span>
          </label>
        )}

        {error && <p className="real-inline-error" role="alert">{error}</p>}

        <div className="real-dialog__actions">
          <button className="command-button" disabled={pending} onClick={onCancel} type="button">
            Cancel
          </button>
          <button
            className="command-button command-button--danger-solid"
            disabled={!canConfirm}
            onClick={() => onConfirm(
              rawDirection ? evidence.required_confirmation_text : confirmationText,
              physicalEstopConfirmed,
              workspaceClearConfirmed,
            )}
            type="button"
          >
            {pending
              ? 'Authorizing…'
              : commissioning
                ? 'Authorize READ ONLY session'
                : commissioningMotion
                  ? 'Authorize Motion Test session'
                  : rawDirection
                    ? '开始方向验收'
                  : 'Authorize Real Motion session'}
          </button>
        </div>
      </section>
    </div>
  );
}
