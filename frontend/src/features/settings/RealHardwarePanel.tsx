import { CircleAlert, Gauge, Link2, Link2Off, RefreshCw, Shield, Square } from 'lucide-react';
import { useCallback, useEffect, useMemo, useState } from 'react';

import {
  ApiError,
  connectRealDevice,
  disconnectRealDevice,
  getFieldAcceptanceStatus,
  runDeviceDiagnostics,
  stopRealDevice,
} from '../../api/client';
import type {
  DeviceDiagnostics,
  DeviceStopResponse,
  FieldAcceptanceStatusResponse,
  OperatorSessionPurpose,
} from '../../api/types';
import { useRealSession } from '../../components/realSessionContext';
import { CalibrationWizard } from './CalibrationWizard';
import { CommissioningMotionPanel } from './CommissioningMotionPanel';
import { OperatorSessionDialog } from './OperatorSessionDialog';
import { RawDirectionPanel } from './RawDirectionPanel';

type PendingAction = 'connect' | 'diagnostics' | 'disconnect' | 'stop';
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

function purposeLabel(purpose: OperatorSessionPurpose): string {
  if (purpose === 'COMMISSIONING_READ_ONLY') return 'READ ONLY';
  if (purpose === 'COMMISSIONING_MOTION_TEST') return 'COMMISSIONING MOTION TEST';
  if (purpose === 'RAW_DIRECTION_TEST') return 'RAW DIRECTION TEST';
  return 'REAL MOTION';
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
  const {
    summary,
    pendingAction: sessionPending,
    authorize: authorizeSession,
    revoke: revokeSession,
    refresh: refreshSession,
  } = useRealSession();
  const readiness = summary.readiness;
  const session = summary.session;
  const [fieldAcceptance, setFieldAcceptance] = useState<FieldAcceptanceStatusResponse | null>(null);
  const [diagnostics, setDiagnostics] = useState<DeviceDiagnostics | null>(null);
  const [calibrationUiState, setCalibrationUiState] = useState<CalibrationUiState>('NOT_CONFIGURED');
  const [dialogOpen, setDialogOpen] = useState(false);
  const [selectedPurpose, setSelectedPurpose] = useState<OperatorSessionPurpose | null>(null);
  const [pending, setPending] = useState<PendingAction | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [fieldAcceptanceError, setFieldAcceptanceError] = useState<string | null>(null);
  const [dialogError, setDialogError] = useState<string | null>(null);
  const [stopResult, setStopResult] = useState<DeviceStopResponse | null>(null);

  const refresh = useCallback(async (signal?: AbortSignal) => {
    const [, acceptanceResult] = await Promise.allSettled([
      refreshSession(),
      getFieldAcceptanceStatus(signal),
    ]);
    if (signal?.aborted) return;
    if (acceptanceResult.status === 'fulfilled') {
      setFieldAcceptance(acceptanceResult.value);
      setFieldAcceptanceError(null);
    } else {
      setFieldAcceptanceError(messageFor(acceptanceResult.reason));
    }
  }, [refreshSession]);

  useEffect(() => {
    const controller = new AbortController();
    void refresh(controller.signal);
    const interval = window.setInterval(() => void refresh(controller.signal), 15_000);
    return () => {
      controller.abort();
      window.clearInterval(interval);
    };
  }, [refresh]);

  const sessionLabel = useMemo(() => {
    if (!session) return null;
    const expiry = new Date(session.expires_at);
    return Number.isNaN(expiry.valueOf()) ? session.expires_at : expiry.toLocaleTimeString();
  }, [session]);

  const runProtected = useCallback(async (
    action: Exclude<PendingAction, 'stop'>,
    request: () => Promise<DeviceDiagnostics>,
  ) => {
    setPending(action);
    setActionError(null);
    try {
      setDiagnostics(await request());
      await refresh();
    } catch (requestError) {
      const requestMessage = messageFor(requestError);
      await refresh();
      setActionError(requestMessage);
    } finally {
      setPending(null);
    }
  }, [refresh]);

  const authorize = async (
    confirmationText: string,
    physicalEstopConfirmed: boolean,
    workspaceClearConfirmed: boolean,
  ) => {
    if (!selectedPurpose) {
      setDialogError('The backend did not provide a purpose-specific authorization request.');
      return;
    }
    setDialogError(null);
    try {
      await authorizeSession(
        selectedPurpose,
        confirmationText,
        physicalEstopConfirmed,
        workspaceClearConfirmed,
      );
      setDialogOpen(false);
      setSelectedPurpose(null);
    } catch (requestError) {
      setDialogError(messageFor(requestError));
    }
  };

  const endSession = async () => {
    setActionError(null);
    try {
      await revokeSession();
      setDiagnostics(null);
    } catch (requestError) {
      setActionError(messageFor(requestError));
    }
  };

  const stop = async () => {
    setPending('stop');
    setStopResult(null);
    setActionError(null);
    try {
      setStopResult(await stopRealDevice());
      await refresh();
    } catch (requestError) {
      setActionError(messageFor(requestError));
    } finally {
      setPending(null);
    }
  };

  const blockedReasons = readiness?.blocking_reasons ?? ['Readiness has not been loaded.'];
  const hasSession = session !== null;
  const commissioningSession = session?.purpose === 'COMMISSIONING_READ_ONLY' &&
    summary.capabilityDetails.commissioning_read_only.authorized;
  const motionSession = session?.purpose === 'REAL_MOTION';
  const commissioningAvailable = summary.capabilityDetails.commissioning_read_only.ready ||
    readiness?.commissioning_session_authorizable === true;
  const commissioningMotionAvailable =
    summary.capabilityDetails.commissioning_motion_test.ready ||
    readiness?.commissioning_motion_session_authorizable === true;
  const rawDirectionAvailable = summary.capabilityDetails.raw_direction_test.ready ||
    readiness?.raw_direction_session_authorizable === true;
  const motionPrerequisitesAvailable = summary.capabilityDetails.real_joint_motion.ready ||
    readiness?.motion_session_authorizable === true;
  const accessMode = !readiness || HARDWARE_DISABLED_STATES.has(readiness.state)
    ? 'DISABLED'
    : commissioningAvailable || commissioningMotionAvailable || rawDirectionAvailable ||
        session?.purpose.startsWith('COMMISSIONING') || session?.purpose === 'RAW_DIRECTION_TEST'
      ? 'COMMISSIONING'
      : 'REAL_MOTION';
  const busy = pending !== null || sessionPending !== null;
  const commissioningControlsDisabled = !commissioningSession || busy;
  const calibrationConfigured =
    calibrationUiState === 'CONFIGURED' || readiness?.calibration_configured === true;
  const calibrationLabel = calibrationUiState === 'DRAFT'
    ? 'Draft'
    : calibrationConfigured
      ? fieldAcceptance?.effective_status === 'PASSED'
        ? 'Calibration configured'
        : 'Calibration configured · Field acceptance pending'
      : 'Not configured';
  const fieldAcceptanceStale = fieldAcceptance?.state === 'STALE' ||
    fieldAcceptance?.state === 'STALE_LEGACY_EVIDENCE';
  const fieldAcceptanceLabel = fieldAcceptanceStale
    ? 'STALE · PENDING'
    : fieldAcceptance?.effective_status ?? diagnostics?.field_acceptance ?? 'PENDING';
  const headerLabel = accessMode === 'COMMISSIONING'
    ? rawDirectionAvailable
      ? '方向验收可开始'
      : commissioningMotionAvailable
      ? '单关节验收可开始'
      : commissioningAvailable
        ? '只读连接可用'
      : '实体工作台未就绪'
    : accessMode === 'REAL_MOTION'
      ? readiness?.ready
        ? '实体运动已授权'
        : '实体运动未开放'
      : 'DRY RUN · 实体未启用';
  const selectedAuthorization = summary.authorizationOptions.find(
    (option) => option.purpose === selectedPurpose,
  ) ?? null;
  const rawAuthorization = summary.authorizationOptions.find(
    (option) => option.purpose === 'RAW_DIRECTION_TEST',
  ) ?? null;
  const displayError = actionError ?? fieldAcceptanceError ?? summary.error;

  return (
    <section className="settings-section real-hardware" aria-labelledby="real-hardware-title">
      <div className="settings-section__heading settings-section__heading--inline">
        <div>
          <p className="section-kicker">实体工作台</p>
          <h2 id="real-hardware-title">V2 连接与方向验收</h2>
        </div>
        <strong className={`real-readiness real-readiness--${accessMode === 'COMMISSIONING' ? 'readonly' : readiness?.ready ? 'ready' : 'blocked'}`}>
          {headerLabel}
        </strong>
      </div>

      <p className="real-hardware__intro">
        常规检查由系统自动完成。进入方向验收时只确认一次，之后可在同一会话中连续完成六轴。
        页面不会自动扫描、回零或移动机械臂。
      </p>

      {displayError && (
        <div className="settings-notice settings-notice--error" role="alert">
          <CircleAlert aria-hidden="true" />
          <span>{displayError}</span>
        </div>
      )}

      <div className="bench-session-strip">
        <div>
          <span>本次现场会话</span>
          <strong>{session
            ? `${purposeLabel(session.purpose)} · ${sessionLabel} 到期`
            : rawAuthorization?.authorizable
              ? '设备条件已满足，等待一次确认'
              : '尚未开始'}</strong>
          <small>只有设备条件真正变化或 Stop 失败时，系统才会中断流程。</small>
        </div>
        <div className="real-actions">
          {!session && rawAuthorization && (
            <button
              className="command-button command-button--danger-solid"
              disabled={!rawAuthorization.authorizable || busy}
              onClick={() => {
                setDialogError(null);
                setSelectedPurpose('RAW_DIRECTION_TEST');
                setDialogOpen(true);
              }}
              type="button"
            >
              一次确认，开始六轴验收
            </button>
          )}
          {session && (
            <button
              className="command-button"
              disabled={busy}
              onClick={() => void endSession()}
              type="button"
            >
              结束本次会话
            </button>
          )}
        </div>
      </div>

      <RawDirectionPanel />

      <details className="real-advanced">
        <summary>高级诊断与后续验收阶段</summary>
        <div className="real-advanced__content">

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

      {fieldAcceptanceStale && (
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
            ['Commissioning read-only', 'commissioning_read_only'],
            ['Commissioning motion test', 'commissioning_motion_test'],
            ['Raw ± direction test', 'raw_direction_test'],
            ['Joint motion', 'real_joint_motion'],
            ['Cartesian motion', 'real_cartesian_motion'],
            ['Playback', 'real_playback'],
            ['Vision Follow', 'real_vision_follow'],
          ] as const).map(([label, key]) => {
            const detail = summary.capabilityDetails[key];
            return (
            <div className="real-capability real-capability--detailed" key={label}>
              <span>{label}</span>
              <strong>{detail.ready && detail.authorized
                ? 'AUTHORIZED'
                : detail.ready
                  ? 'SESSION REQUIRED'
                  : 'BLOCKED'}</strong>
              {(detail.blocked_reasons.length > 0 || detail.required_evidence.length > 0) && (
                <ul>
                  {detail.blocked_reasons.map((reason) => <li key={reason}>{reason}</li>)}
                  {detail.required_evidence.map((evidence) => (
                    <li key={`evidence-${evidence}`}>Required evidence: {evidence}</li>
                  ))}
                </ul>
              )}
            </div>
            );
          })}
        </div>
      )}

      {readiness && (
        <dl className="real-evidence-grid real-evidence-grid--panel">
          <div><dt>Robot unit ID</dt><dd><code>{readiness.confirmation.robot_unit_id ?? 'Not configured'}</code></dd></div>
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
          <strong>{session
            ? `${purposeLabel(session.purpose)} · Expires at ${sessionLabel}`
            : 'No active cookie-backed session'}</strong>
          <small>The HttpOnly authorization cookie is never exposed to JavaScript.</small>
        </div>
        <div className="real-actions">
          {summary.authorizationOptions
            .filter((option) => option.purpose !== 'RAW_DIRECTION_TEST')
            .map((option) => (
            <button
              className={option.purpose === 'COMMISSIONING_MOTION_TEST' ||
                option.purpose === 'RAW_DIRECTION_TEST'
                ? 'command-button command-button--danger-solid'
                : 'command-button command-button--primary'}
              disabled={!option.authorizable || busy || hasSession}
              key={option.purpose}
              onClick={() => {
                setDialogError(null);
                setSelectedPurpose(option.purpose);
                setDialogOpen(true);
              }}
              type="button"
            >
              {option.purpose === 'COMMISSIONING_READ_ONLY'
                ? 'Authorize READ ONLY'
                : option.purpose === 'COMMISSIONING_MOTION_TEST'
                  ? 'Authorize Motion Test'
                  : option.purpose === 'RAW_DIRECTION_TEST'
                    ? 'Authorize Raw ± Test'
                    : 'Authorize Real Motion'}
            </button>
          ))}
          <button
            className="command-button"
            disabled={!hasSession || busy}
            onClick={() => void endSession()}
            type="button"
          >
            End session
          </button>
        </div>
      </div>

      <div className="real-actions real-actions--device">
        <button
          className="command-button"
          disabled={commissioningControlsDisabled || readiness?.connected === true}
          onClick={() => void runProtected('connect', connectRealDevice)}
          type="button"
        >
          <Link2 aria-hidden="true" /> Connect Read-Only
        </button>
        <button
          className="command-button"
          disabled={commissioningControlsDisabled || readiness?.connected !== true}
          onClick={() => void runProtected('diagnostics', runDeviceDiagnostics)}
          type="button"
        >
          <RefreshCw aria-hidden="true" /> Diagnostics
        </button>
        <button
          className="command-button"
          disabled={commissioningControlsDisabled || readiness?.connected !== true}
          onClick={() => void runProtected('disconnect', disconnectRealDevice)}
          type="button"
        >
          <Link2Off aria-hidden="true" /> Disconnect
        </button>
        <button
          className="command-button command-button--stop"
          disabled={!motionSession || busy}
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

      {commissioningSession && summary.capabilityDetails.commissioning_read_only.ready && (
        <CalibrationWizard
          connected={readiness?.connected === true}
          initiallyConfigured={calibrationConfigured}
          onStatusChange={setCalibrationUiState}
          onSessionInvalidated={() => {
            void refresh();
          }}
        />
      )}

      <CommissioningMotionPanel diagnostics={diagnostics} />
        </div>
      </details>

      {dialogOpen && selectedAuthorization && (
        <OperatorSessionDialog
          error={dialogError}
          evidence={selectedAuthorization.confirmation}
          onCancel={() => {
            if (sessionPending !== 'authorize') {
              setDialogOpen(false);
              setSelectedPurpose(null);
            }
          }}
          onConfirm={(text, estop, workspaceClear) => void authorize(
            text,
            estop,
            workspaceClear,
          )}
          pending={sessionPending === 'authorize'}
        />
      )}
    </section>
  );
}
