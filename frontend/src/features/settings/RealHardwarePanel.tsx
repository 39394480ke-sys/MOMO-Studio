import { CircleAlert, Gauge, Link2, Link2Off, RefreshCw, Shield, Square } from 'lucide-react';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';

import {
  ApiError,
  connectRealDevice,
  createOperatorSession,
  disconnectRealDevice,
  getDeviceReadiness,
  getFieldAcceptanceStatus,
  revokeOperatorSession,
  runDeviceDiagnostics,
  stopRealDevice,
} from '../../api/client';
import type {
  DeviceDiagnostics,
  DeviceReadiness,
  DeviceStopResponse,
  FieldAcceptanceStatusResponse,
  OperatorSessionPurpose,
} from '../../api/types';
import { CalibrationWizard } from './CalibrationWizard';
import { OperatorSessionDialog } from './OperatorSessionDialog';

type PendingAction = 'authorize' | 'connect' | 'diagnostics' | 'disconnect' | 'revoke' | 'stop';
type CalibrationUiState = 'NOT_CONFIGURED' | 'DRAFT' | 'CONFIGURED';

const HARDWARE_DISABLED_STATES = new Set([
  'BLOCKED_BY_STAGE_POLICY',
  'BLOCKED_BY_CONTROL_MODE',
  'BLOCKED_BY_HARDWARE_POLICY',
]);

function messageFor(error: unknown): string {
  if (error instanceof ApiError || error instanceof Error) return error.message;
  return 'The device request failed.';
}

function maskedList(values: string[]): string {
  return values.length > 0 ? values.join(', ') : 'Not configured';
}

function EvidenceStatus({ label, value }: { label: string; value: DeviceDiagnostics['profile'] }) {
  return (
    <div>
      <dt>{label}</dt>
      <dd>
        <strong>{value.ready_for_real ? 'Ready' : 'Blocked'}</strong>
        <span>{value.verification_status ?? 'Not verified'}</span>
        <code>{value.fingerprint ?? 'No fingerprint'}</code>
      </dd>
    </div>
  );
}

export function RealHardwarePanel() {
  const [readiness, setReadiness] = useState<DeviceReadiness | null>(null);
  const [fieldAcceptance, setFieldAcceptance] = useState<FieldAcceptanceStatusResponse | null>(null);
  const [diagnostics, setDiagnostics] = useState<DeviceDiagnostics | null>(null);
  const [sessionToken, setSessionToken] = useState<string | null>(null);
  const [sessionExpiresAt, setSessionExpiresAt] = useState<string | null>(null);
  const [sessionPurpose, setSessionPurpose] = useState<OperatorSessionPurpose | null>(null);
  const [calibrationUiState, setCalibrationUiState] = useState<CalibrationUiState>('NOT_CONFIGURED');
  const [dialogOpen, setDialogOpen] = useState(false);
  const [pending, setPending] = useState<PendingAction | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [dialogError, setDialogError] = useState<string | null>(null);
  const [stopResult, setStopResult] = useState<DeviceStopResponse | null>(null);
  const ownedSessionRef = useRef<{
    sessionId: string;
    purpose: OperatorSessionPurpose;
    scopesKey: string;
  } | null>(null);

  const clearOwnedSession = useCallback(() => {
    ownedSessionRef.current = null;
    setSessionToken(null);
    setSessionExpiresAt(null);
    setSessionPurpose(null);
    setDiagnostics(null);
  }, []);

  const refresh = useCallback(async (signal?: AbortSignal) => {
    const [readinessResult, acceptanceResult] = await Promise.allSettled([
      getDeviceReadiness(signal),
      getFieldAcceptanceStatus(signal),
    ]);
    if (signal?.aborted) return null;
    if (readinessResult.status === 'rejected') {
      clearOwnedSession();
      setError(messageFor(readinessResult.reason));
      return null;
    }
    const next = readinessResult.value;
    setReadiness(next);
    const owned = ownedSessionRef.current;
    if (owned && (
      !next.session?.active ||
      next.session.session_id !== owned.sessionId ||
      next.session.purpose !== owned.purpose ||
      [...next.session.scopes].sort().join('|') !== owned.scopesKey
    )) {
      clearOwnedSession();
    }
    if (acceptanceResult.status === 'fulfilled') {
      setFieldAcceptance(acceptanceResult.value);
      setError(null);
    } else {
      setError(messageFor(acceptanceResult.reason));
    }
    return next;
  }, [clearOwnedSession]);

  useEffect(() => {
    const controller = new AbortController();
    void refresh(controller.signal);
    const interval = window.setInterval(() => void refresh(controller.signal), 15_000);
    return () => {
      controller.abort();
      window.clearInterval(interval);
    };
  }, [refresh]);

  useEffect(() => {
    if (!sessionExpiresAt) return;
    let timeout: number | undefined;
    const expireSession = () => {
      clearOwnedSession();
      void refresh().finally(() => {
        setError('Operator Session expired. Authorize again before any device access.');
      });
    };
    const scheduleExpiryCheck = () => {
      const remaining = Date.parse(sessionExpiresAt) - Date.now();
      if (remaining <= 0) {
        expireSession();
        return;
      }
      // Browsers clamp timers to a signed 32-bit delay. Re-check long-lived test
      // fixtures without letting an overflow expire a valid in-memory token.
      timeout = window.setTimeout(scheduleExpiryCheck, Math.min(remaining, 2_147_000_000));
    };
    scheduleExpiryCheck();
    return () => {
      if (timeout !== undefined) window.clearTimeout(timeout);
    };
  }, [clearOwnedSession, refresh, sessionExpiresAt]);

  const sessionLabel = useMemo(() => {
    if (!sessionExpiresAt) return null;
    const expiry = new Date(sessionExpiresAt);
    return Number.isNaN(expiry.valueOf()) ? sessionExpiresAt : expiry.toLocaleTimeString();
  }, [sessionExpiresAt]);

  const runWithToken = useCallback(async (
    action: Exclude<PendingAction, 'authorize' | 'stop'>,
    request: (token: string) => Promise<DeviceDiagnostics | void>,
  ) => {
    if (!sessionToken) {
      setError('A current in-memory Operator Session token is required.');
      return;
    }
    setPending(action);
    setError(null);
    try {
      const result = await request(sessionToken);
      if (result) setDiagnostics(result);
      await refresh();
      if (action === 'revoke' || action === 'disconnect') {
        clearOwnedSession();
      }
    } catch (requestError) {
      const message = messageFor(requestError);
      setError(message);
      if (requestError instanceof ApiError && requestError.status === 401) {
        clearOwnedSession();
      }
      await refresh();
    } finally {
      setPending(null);
    }
  }, [clearOwnedSession, refresh, sessionToken]);

  const authorize = async (confirmationText: string, physicalEstopConfirmed: boolean) => {
    const purpose = readiness?.confirmation.session_purpose;
    if (!purpose) {
      setDialogError('The backend did not provide a purpose-specific authorization request.');
      return;
    }
    setPending('authorize');
    setDialogError(null);
    try {
      const session = await createOperatorSession(
        purpose,
        confirmationText,
        physicalEstopConfirmed,
      );
      ownedSessionRef.current = {
        sessionId: session.session_id,
        purpose: session.purpose,
        scopesKey: [...session.scopes].sort().join('|'),
      };
      setSessionToken(session.session_token);
      setSessionExpiresAt(session.expires_at);
      setSessionPurpose(session.purpose);
      setDialogOpen(false);
      await refresh();
    } catch (requestError) {
      setDialogError(messageFor(requestError));
    } finally {
      setPending(null);
    }
  };

  const stop = async () => {
    setPending('stop');
    setStopResult(null);
    setError(null);
    try {
      setStopResult(await stopRealDevice());
      await refresh();
    } catch (requestError) {
      setError(messageFor(requestError));
    } finally {
      setPending(null);
    }
  };

  const blockedReasons = readiness?.blocking_reasons ?? ['Readiness has not been loaded.'];
  const hasOwnedSession = Boolean(sessionToken && sessionExpiresAt);
  const commissioningSession = hasOwnedSession && sessionPurpose === 'COMMISSIONING_READ_ONLY';
  const motionSession = hasOwnedSession && sessionPurpose === 'REAL_MOTION';
  const commissioningAvailable = Boolean(
    readiness?.capabilities.commissioning_diagnostics_ready &&
    readiness.capabilities.calibration_capture_ready,
  );
  const motionPrerequisitesAvailable = Boolean(
    readiness?.motion_session_authorizable || readiness?.capabilities.real_joint_motion_ready,
  );
  const accessMode = !readiness || HARDWARE_DISABLED_STATES.has(readiness.state)
    ? 'DISABLED'
    : readiness.confirmation.session_purpose === 'COMMISSIONING_READ_ONLY'
      ? 'COMMISSIONING'
      : 'REAL_MOTION';
  const commissioningControlsDisabled = !commissioningSession || pending !== null;
  const calibrationConfigured =
    calibrationUiState === 'CONFIGURED' || readiness?.calibration_configured === true;
  const calibrationLabel = calibrationUiState === 'DRAFT'
    ? 'Draft'
    : calibrationConfigured
      ? fieldAcceptance?.effective_status === 'PASSED'
        ? 'Calibration configured'
        : 'Calibration configured · Field acceptance pending'
      : 'Not configured';
  const fieldAcceptanceLabel = fieldAcceptance?.state === 'STALE'
    ? 'STALE · PENDING'
    : fieldAcceptance?.effective_status ?? diagnostics?.field_acceptance ?? 'PENDING';
  const headerLabel = accessMode === 'COMMISSIONING'
    ? commissioningAvailable
      ? 'Commissioning available · READ ONLY'
      : 'Commissioning blocked · READ ONLY'
    : accessMode === 'REAL_MOTION'
      ? readiness?.ready
        ? 'Real Motion authorized'
        : 'Real Motion blocked'
      : 'Hardware access disabled';

  return (
    <section className="settings-section real-hardware" aria-labelledby="real-hardware-title">
      <div className="settings-section__heading settings-section__heading--inline">
        <div>
          <p className="section-kicker">Stage 8 · Field gated</p>
          <h2 id="real-hardware-title">Real Hardware Boundary</h2>
        </div>
        <strong className={`real-readiness real-readiness--${accessMode === 'COMMISSIONING' ? 'readonly' : readiness?.ready ? 'ready' : 'blocked'}`}>
          {headerLabel}
        </strong>
      </div>

      <p className="real-hardware__intro">
        Nothing on this page scans, homes, calibrates, or moves a robot automatically.
        Device access requires every backend gate and a short-lived, memory-only Operator Session.
      </p>

      {accessMode === 'COMMISSIONING' && (
        <div className="commissioning-banner" role="status">
          <div>
            <strong>Commissioning mode</strong>
            <span className="commissioning-badge">READ ONLY</span>
          </div>
          <p>No motion commands are permitted. 仅允许明确设备的诊断读取与标定采集。</p>
        </div>
      )}

      {error && (
        <div className="settings-notice settings-notice--error" role="alert">
          <CircleAlert aria-hidden="true" />
          <span>{error}</span>
        </div>
      )}

      <div className="real-gate-grid">
        <div className="real-gate-card">
          <Shield aria-hidden="true" />
          <div>
            <span>Hardware Disabled</span>
            <strong>{accessMode === 'DISABLED' ? 'ACTIVE' : 'INACTIVE'}</strong>
          </div>
        </div>
        <div className="real-gate-card">
          <Gauge aria-hidden="true" />
          <div>
            <span>Commissioning / Read-only</span>
            <strong>{commissioningAvailable
              ? 'AVAILABLE'
              : accessMode === 'COMMISSIONING'
                ? 'BLOCKED'
                : 'UNAVAILABLE'}</strong>
          </div>
        </div>
        <div className="real-gate-card">
          <Shield aria-hidden="true" />
          <div>
            <span>Real Motion</span>
            <strong>{readiness?.ready ? 'AUTHORIZED' : motionPrerequisitesAvailable ? 'SESSION REQUIRED' : 'BLOCKED'}</strong>
          </div>
        </div>
      </div>

      <div className="real-gate-grid">
        <div className="real-gate-card">
          {readiness?.connected ? <Link2 aria-hidden="true" /> : <Link2Off aria-hidden="true" />}
          <div><span>Connection</span><strong>{readiness?.connected ? 'CONNECTED' : 'DISCONNECTED'}</strong></div>
        </div>
        <div className="real-gate-card">
          <Gauge aria-hidden="true" />
          <div><span>Calibration</span><strong>{calibrationLabel}</strong></div>
        </div>
        <div className="real-gate-card">
          <Shield aria-hidden="true" />
          <div><span>Field acceptance</span><strong>{fieldAcceptanceLabel}</strong></div>
        </div>
      </div>

      {fieldAcceptance?.state === 'STALE' && (
        <div className="readiness-block real-blockers" role="status">
          <CircleAlert aria-hidden="true" />
          <div>
            <strong>Field Acceptance evidence is stale · Real Motion blocked</strong>
            <ul>{fieldAcceptance.stale_fields.map((field) => <li key={field}>{field}</li>)}</ul>
          </div>
        </div>
      )}

      {!readiness?.ready && (
        <div className="readiness-block real-blockers">
          <Shield aria-hidden="true" />
          <div>
            <strong>{commissioningAvailable
              ? 'Real motion remains blocked; read-only commissioning is available'
              : 'Real hardware access remains blocked'}</strong>
            <ul>{blockedReasons.map((reason) => <li key={reason}>{reason}</li>)}</ul>
          </div>
        </div>
      )}

      {readiness && (
        <div className="real-capabilities" aria-label="Real capability readiness">
          {([
            ['Commissioning diagnostics', readiness.capabilities.commissioning_diagnostics_ready],
            ['Calibration capture', readiness.capabilities.calibration_capture_ready],
            ['Joint motion', readiness.capabilities.real_joint_motion_ready],
            ['Cartesian motion', readiness.capabilities.real_cartesian_motion_ready],
            ['Playback', readiness.capabilities.real_playback_ready],
            ['Vision Follow', readiness.capabilities.real_vision_follow_ready],
          ] as const).map(([label, ready]) => (
            <div className="real-capability" key={label}>
              <span>{label}</span>
              <strong>{ready ? 'READY' : 'BLOCKED'}</strong>
            </div>
          ))}
        </div>
      )}

      {readiness && (
        <dl className="real-evidence-grid real-evidence-grid--panel">
          <div><dt>Variant</dt><dd>{readiness.confirmation.variant ?? 'Not configured'}</dd></div>
          <div><dt>Serial</dt><dd><code>{readiness.confirmation.masked_serial_port ?? 'Not configured'}</code></dd></div>
          <div><dt>Servo IDs</dt><dd>{maskedList(readiness.confirmation.masked_servo_ids)}</dd></div>
          <div><dt>Protocol</dt><dd>{readiness.confirmation.protocol ?? 'Not configured'}</dd></div>
          <div><dt>Profile fingerprint</dt><dd><code>{readiness.confirmation.profile_fingerprint ?? 'Not configured'}</code></dd></div>
          <div><dt>Calibration fingerprint</dt><dd><code>{readiness.confirmation.calibration_fingerprint ?? 'Not configured'}</code></dd></div>
        </dl>
      )}

      <div className="real-session-bar">
        <div>
          <span>Operator Session</span>
          <strong>{hasOwnedSession
            ? `${sessionPurpose === 'COMMISSIONING_READ_ONLY' ? 'READ ONLY' : 'REAL MOTION'} · Expires at ${sessionLabel}`
            : 'No token held by this page'}</strong>
          <small>Tokens are never persisted or remembered.</small>
        </div>
        <div className="real-actions">
          <button
            className="command-button command-button--primary"
            disabled={!readiness?.session_authorizable || pending !== null || hasOwnedSession}
            onClick={() => { setDialogError(null); setDialogOpen(true); }}
            type="button"
          >
            {readiness?.confirmation.session_purpose === 'COMMISSIONING_READ_ONLY'
              ? 'Authorize READ ONLY'
              : 'Authorize Real Motion'}
          </button>
          <button
            className="command-button"
            disabled={!hasOwnedSession || pending !== null}
            onClick={() => void runWithToken('revoke', revokeOperatorSession)}
            type="button"
          >
            End session
          </button>
        </div>
      </div>

      {readiness?.session?.active && !hasOwnedSession && (
        <p className="real-session-warning" role="status">
          A backend session is active, but its token is not held by this page. No device controls are available here.
        </p>
      )}

      <div className="real-actions real-actions--device">
        <button
          className="command-button"
          disabled={commissioningControlsDisabled || readiness?.connected === true}
          onClick={() => void runWithToken('connect', connectRealDevice)}
          type="button"
        >
          <Link2 aria-hidden="true" /> Connect Read-Only
        </button>
        <button
          className="command-button"
          disabled={commissioningControlsDisabled || readiness?.connected !== true}
          onClick={() => void runWithToken('diagnostics', runDeviceDiagnostics)}
          type="button"
        >
          <RefreshCw aria-hidden="true" /> Diagnostics
        </button>
        <button
          className="command-button"
          disabled={commissioningControlsDisabled || readiness?.connected !== true}
          onClick={() => void runWithToken('disconnect', disconnectRealDevice)}
          type="button"
        >
          <Link2Off aria-hidden="true" /> Disconnect
        </button>
        <button
          className="command-button command-button--stop"
          disabled={!motionSession || pending !== null}
          onClick={() => void stop()}
          type="button"
        >
          <Square aria-hidden="true" /> Real Motion software Stop
        </button>
      </div>

      {stopResult && (
        <div className="real-stop-result" role="status">
          <strong>{stopResult.result}</strong>
          <span>{stopResult.detail}</span>
          {stopResult.physical_estop_required && <b>Use the physical E-stop.</b>}
        </div>
      )}

      {diagnostics && (
        <div className="real-diagnostics">
          <div className="settings-section__heading settings-section__heading--inline">
            <div>
              <p className="section-kicker">Explicit read only</p>
              <h3>Device Diagnostics</h3>
            </div>
            <span>{diagnostics.captured_at}</span>
          </div>
          <dl className="real-evidence-grid real-evidence-grid--panel">
            <div><dt>Dependency</dt><dd>{diagnostics.dependency.state}<small>{diagnostics.dependency.notice}</small></dd></div>
            <div><dt>Hardware policy</dt><dd>{diagnostics.hardware_policy}</dd></div>
            <div><dt>Readiness</dt><dd>{diagnostics.readiness}</dd></div>
            <EvidenceStatus label="Profile" value={diagnostics.profile} />
            <EvidenceStatus label="Calibration" value={diagnostics.calibration} />
            <EvidenceStatus label="Kinematics" value={diagnostics.kinematics} />
          </dl>
          {diagnostics.last_error && <p className="real-inline-error">{diagnostics.last_error}</p>}
          <div className="real-table-wrap">
            <table className="real-diagnostics-table">
              <caption>Explicit configured Servo diagnostics</caption>
              <thead><tr><th>Joint</th><th>Servo</th><th>Ping</th><th>Mode</th><th>Present raw</th><th>Logical</th><th>Raw bounds</th><th>Torque</th></tr></thead>
              <tbody>
                {diagnostics.records.map((record) => (
                  <tr key={record.joint_id}>
                    <th scope="row">{record.joint_id.toUpperCase()}</th>
                    <td>{record.masked_servo_id}</td>
                    <td>{record.ping_responded ? 'Yes' : 'No'}</td>
                    <td>{record.operating_mode ?? 'Unknown'}</td>
                    <td>{record.present_raw ?? '—'}</td>
                    <td>{record.logical_value ?? '—'}</td>
                    <td>{record.raw_bounds?.join('…') ?? '—'}</td>
                    <td>{record.torque_enabled === null ? 'Unknown' : record.torque_enabled ? 'On' : 'Off'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {commissioningSession && sessionToken && readiness?.capabilities.calibration_capture_ready && (
        <CalibrationWizard
          connected={readiness?.connected === true}
          initiallyConfigured={calibrationConfigured}
          onStatusChange={setCalibrationUiState}
          onSessionInvalidated={() => {
            clearOwnedSession();
            void refresh();
          }}
          operatorToken={sessionToken}
        />
      )}

      {dialogOpen && readiness && (
        <OperatorSessionDialog
          error={dialogError}
          evidence={readiness.confirmation}
          onCancel={() => { if (pending !== 'authorize') setDialogOpen(false); }}
          onConfirm={(text, estop) => void authorize(text, estop)}
          pending={pending === 'authorize'}
        />
      )}
    </section>
  );
}
