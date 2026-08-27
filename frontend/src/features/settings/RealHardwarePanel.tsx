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
import { zhBackendMessage, zhStatus } from '../../i18n/zh';
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
  return '设备请求失败。';
}

function maskedList(values: string[]): string {
  return values.length > 0 ? values.join(', ') : '未配置';
}

function purposeLabel(purpose: OperatorSessionPurpose): string {
  if (purpose === 'COMMISSIONING_READ_ONLY') return '只读验收';
  if (purpose === 'COMMISSIONING_MOTION_TEST') return '现场运动测试';
  if (purpose === 'RAW_DIRECTION_TEST') return 'Raw 方向测试';
  return '真机运动';
}

function EvidenceStatus({ label, value }: { label: string; value: DeviceDiagnostics['profile'] }) {
  return (
    <div>
      <dt>{label}</dt>
      <dd>
        <strong>{value.ready_for_real ? '已就绪' : '已阻止'}</strong>
        <span>{zhStatus(value.verification_status, '未验证')}</span>
        <code>{value.fingerprint ?? '无指纹'}</code>
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
    return Number.isNaN(expiry.valueOf()) ? session.expires_at : expiry.toLocaleTimeString('zh-CN');
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
      setDialogError('后端没有提供与当前用途匹配的授权请求。');
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

  const blockedReasons = readiness?.blocking_reasons ?? ['尚未加载就绪状态。'];
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
    ? '草稿'
    : calibrationConfigured
      ? fieldAcceptance?.effective_status === 'PASSED'
        ? '标定已配置'
        : '标定已配置 · 等待现场验收'
      : '未配置';
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
      : '仿真运行 · 实体未启用';
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
            <span>硬件已禁用</span>
            <strong>{accessMode === 'DISABLED' ? '当前生效' : '未生效'}</strong>
          </div>
        </div>
        <div className="real-gate-card">
          <Gauge aria-hidden="true" />
          <div>
            <span>现场验收 / 只读</span>
            <strong>{commissioningAvailable
              ? '可用'
              : accessMode === 'COMMISSIONING'
                ? '已阻止'
                : '不可用'}</strong>
          </div>
        </div>
        <div className="real-gate-card">
          <Shield aria-hidden="true" />
          <div>
            <span>真机运动</span>
            <strong>{readiness?.ready ? '已授权' : motionPrerequisitesAvailable ? '需要会话' : '已阻止'}</strong>
          </div>
        </div>
      </div>

      <div className="real-gate-grid">
        <div className="real-gate-card">
          {readiness?.connected ? <Link2 aria-hidden="true" /> : <Link2Off aria-hidden="true" />}
          <div><span>连接</span><strong>{readiness?.connected ? '已连接' : '未连接'}</strong></div>
        </div>
        <div className="real-gate-card">
          <Gauge aria-hidden="true" />
          <div><span>标定</span><strong>{calibrationLabel}</strong></div>
        </div>
        <div className="real-gate-card">
          <Shield aria-hidden="true" />
          <div><span>现场验收</span><strong>{zhStatus(fieldAcceptanceLabel)}</strong></div>
        </div>
      </div>

      {fieldAcceptanceStale && (
        <div className="readiness-block real-blockers" role="status">
          <CircleAlert aria-hidden="true" />
          <div>
            <strong>现场验收证据已经过期 · 真机运动已阻止</strong>
            <ul>{fieldAcceptance.stale_fields.map((field) => <li key={field}>{field}</li>)}</ul>
          </div>
        </div>
      )}

      {!readiness?.ready && (
        <div className="readiness-block real-blockers">
          <Shield aria-hidden="true" />
          <div>
            <strong>{commissioningAvailable
              ? '真机运动保持禁用；只读现场验收可用'
              : '真实硬件访问保持禁用'}</strong>
            <ul>{blockedReasons.map((reason) => <li key={reason}>{zhBackendMessage(reason)}</li>)}</ul>
          </div>
        </div>
      )}

      {readiness && (
        <div className="real-capabilities" aria-label="真机能力就绪状态">
          {([
            ['只读现场验收', 'commissioning_read_only'],
            ['现场运动测试', 'commissioning_motion_test'],
            ['Raw ± 方向测试', 'raw_direction_test'],
            ['关节运动', 'real_joint_motion'],
            ['笛卡尔运动', 'real_cartesian_motion'],
            ['运动播放', 'real_playback'],
            ['视觉跟随', 'real_vision_follow'],
          ] as const).map(([label, key]) => {
            const detail = summary.capabilityDetails[key];
            return (
            <div className="real-capability real-capability--detailed" key={label}>
              <span>{label}</span>
              <strong>{detail.ready && detail.authorized
                ? '已授权'
                : detail.ready
                  ? '需要会话'
                  : '已阻止'}</strong>
              {(detail.blocked_reasons.length > 0 || detail.required_evidence.length > 0) && (
                <ul>
                  {detail.blocked_reasons.map((reason) => <li key={reason}>{zhBackendMessage(reason)}</li>)}
                  {detail.required_evidence.map((evidence) => (
                    <li key={`evidence-${evidence}`}>需要验收证据：{evidence}</li>
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
          <div><dt>机械臂单元 ID</dt><dd><code>{readiness.confirmation.robot_unit_id ?? '未配置'}</code></dd></div>
          <div><dt>型号</dt><dd>{readiness.confirmation.variant ?? '未配置'}</dd></div>
          <div><dt>串口</dt><dd><code>{readiness.confirmation.masked_serial_port ?? '未配置'}</code></dd></div>
          <div><dt>舵机 ID</dt><dd>{maskedList(readiness.confirmation.masked_servo_ids)}</dd></div>
          <div><dt>协议</dt><dd>{readiness.confirmation.protocol ?? '未配置'}</dd></div>
          <div><dt>配置指纹</dt><dd><code>{readiness.confirmation.profile_fingerprint ?? '未配置'}</code></dd></div>
          <div><dt>标定指纹</dt><dd><code>{readiness.confirmation.calibration_fingerprint ?? '未配置'}</code></dd></div>
        </dl>
      )}

      <div className="real-session-bar">
        <div>
          <span>操作员会话</span>
          <strong>{session
            ? `${purposeLabel(session.purpose)} · ${sessionLabel} 到期`
            : '当前没有有效的 Cookie 授权会话'}</strong>
          <small>JavaScript 永远无法读取 HttpOnly 授权 Cookie。</small>
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
                ? '授权只读验收'
                : option.purpose === 'COMMISSIONING_MOTION_TEST'
                  ? '授权运动测试'
                  : option.purpose === 'RAW_DIRECTION_TEST'
                    ? '授权 Raw ± 测试'
                    : '授权真机运动'}
            </button>
          ))}
          <button
            className="command-button"
            disabled={!hasSession || busy}
            onClick={() => void endSession()}
            type="button"
          >
            结束会话
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
          <Link2 aria-hidden="true" /> 只读连接
        </button>
        <button
          className="command-button"
          disabled={commissioningControlsDisabled || readiness?.connected !== true}
          onClick={() => void runProtected('diagnostics', runDeviceDiagnostics)}
          type="button"
        >
          <RefreshCw aria-hidden="true" /> 运行诊断
        </button>
        <button
          className="command-button"
          disabled={commissioningControlsDisabled || readiness?.connected !== true}
          onClick={() => void runProtected('disconnect', disconnectRealDevice)}
          type="button"
        >
          <Link2Off aria-hidden="true" /> 断开连接
        </button>
        <button
          className="command-button command-button--stop"
          disabled={!motionSession || busy}
          onClick={() => void stop()}
          type="button"
        >
          <Square aria-hidden="true" /> 真机运动软件停止
        </button>
      </div>

      {stopResult && (
        <div className="real-stop-result" role="status">
          <strong>{stopResult.result}</strong>
          <span>{stopResult.detail}</span>
          {stopResult.physical_estop_required && <b>请使用物理急停。</b>}
        </div>
      )}

      {diagnostics && (
        <div className="real-diagnostics">
          <div className="settings-section__heading settings-section__heading--inline">
            <div>
              <p className="section-kicker">明确只读</p>
              <h3>设备诊断</h3>
            </div>
            <span>{diagnostics.captured_at}</span>
          </div>
          <dl className="real-evidence-grid real-evidence-grid--panel">
            <div><dt>依赖</dt><dd>{zhStatus(diagnostics.dependency.state)}<small>{zhBackendMessage(diagnostics.dependency.notice)}</small></dd></div>
            <div><dt>硬件策略</dt><dd>{zhStatus(diagnostics.hardware_policy)}</dd></div>
            <div><dt>就绪状态</dt><dd>{zhStatus(diagnostics.readiness)}</dd></div>
            <EvidenceStatus label="机械臂配置" value={diagnostics.profile} />
            <EvidenceStatus label="标定" value={diagnostics.calibration} />
            <EvidenceStatus label="运动学" value={diagnostics.kinematics} />
          </dl>
          {diagnostics.last_error && <p className="real-inline-error">{diagnostics.last_error}</p>}
          <div className="real-table-wrap">
            <table className="real-diagnostics-table">
              <caption>已明确配置的舵机诊断</caption>
              <thead><tr><th>关节</th><th>舵机</th><th>通信</th><th>模式</th><th>当前 Raw</th><th>逻辑值</th><th>Raw 范围</th><th>扭矩</th></tr></thead>
              <tbody>
                {diagnostics.records.map((record) => (
                  <tr key={record.joint_id}>
                    <th scope="row">{record.joint_id.toUpperCase()}</th>
                    <td>{record.masked_servo_id}</td>
                    <td>{record.ping_responded ? '正常' : '失败'}</td>
                    <td>{record.operating_mode ?? '未知'}</td>
                    <td>{record.present_raw ?? '—'}</td>
                    <td>{record.logical_value ?? '—'}</td>
                    <td>{record.raw_bounds?.join('…') ?? '—'}</td>
                    <td>{record.torque_enabled === null ? '未知' : record.torque_enabled ? '开启' : '关闭'}</td>
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
