import { CircleAlert, Crosshair, Square } from 'lucide-react';
import { useEffect, useState } from 'react';

import {
  ApiError,
  armRawDirectionJoint,
  confirmRawDirectionDraft,
  getRawDirectionStatus,
  heartbeatRawDirectionTest,
  recordRawDirectionAlignment,
  startRawDirectionSession,
  stepRawDirectionJoint,
  stopRawDirectionTest,
} from '../../api/client';
import type { RawDirection, RawDirectionStatus } from '../../api/types';
import { useRealSession } from '../../components/realSessionContext';

function errorMessage(error: unknown): string {
  if (error instanceof ApiError || error instanceof Error) return error.message;
  return 'Raw 方向请求失败。';
}

function errorDetails(error: ApiError): Record<string, unknown> {
  return typeof error.details === 'object' && error.details !== null
    ? error.details as Record<string, unknown>
    : {};
}

export function RawDirectionPanel() {
  const { summary } = useRealSession();
  const [status, setStatus] = useState<RawDirectionStatus | null>(null);
  const [busy, setBusy] = useState(false);
  const [held, setHeld] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const capability = summary.capabilityDetails.raw_direction_test;
  const rawSession = summary.session?.purpose === 'RAW_DIRECTION_TEST' && capability.authorized;

  useEffect(() => {
    if (!rawSession) {
      setStatus(null);
      setHeld(null);
      return;
    }
    const controller = new AbortController();
    void getRawDirectionStatus(controller.signal)
      .then((nextStatus) => {
        // Raw-direction runtime state is process-local. An operator can start a
        // new authorization session while an older runtime snapshot is still
        // present (for example after expiry or a backend restart). Never show
        // controls backed by a different session ID.
        if (nextStatus.session_id !== summary.session?.session_id) {
          setStatus(null);
          return;
        }
        if (nextStatus.state === 'FAILED' || nextStatus.state === 'EXPIRED') {
          setStatus(null);
          setError('上一次方向测试未完整结束。请重新读取当前六轴零点后再测试。');
          return;
        }
        setStatus(nextStatus);
      })
      .catch((requestError) => {
        if (!controller.signal.aborted) setError(errorMessage(requestError));
      });
    return () => controller.abort();
  }, [rawSession, summary.session?.session_id]);

  const handleRequestError = (requestError: unknown) => {
    const message = errorMessage(requestError);
    if (requestError instanceof ApiError && requestError.code === 'RAW_DIRECTION_EXECUTION_FAILED') {
      const details = errorDetails(requestError);
      const target = typeof details.target_raw === 'number' ? details.target_raw : null;
      const observed = typeof details.observed_raw === 'number' ? details.observed_raw : null;
      const rawDetail = target !== null && observed !== null
        ? `（目标 Raw ${target}，最后 Raw ${observed}）`
        : '';
      setStatus(null);
      setHeld(null);
      setError(`小步未完成，系统已请求保持${rawDetail}。请重新读取当前六轴零点后再测试。`);
      return;
    }
    if (requestError instanceof ApiError &&
      ['RAW_DIRECTION_CONFLICT', 'RAW_DIRECTION_ENVELOPE_EXCEEDED'].includes(requestError.code) &&
      errorDetails(requestError).reason === 'ZERO_RECAPTURE_REQUIRED') {
      setStatus(null);
      setHeld(null);
      setError('上一次小步没有完整验收，已禁止继续累积目标。请重新读取当前六轴零点。');
      return;
    }
    if (message.includes('session is not bound') || message.includes('session expired')) {
      setStatus(null);
      setHeld(null);
      setError('方向测试会话已失效。请重新读取当前六轴零点后再进行小步测试。');
      return;
    }
    setError(message);
  };

  const captureZero = async () => {
    setBusy(true);
    setError(null);
    try {
      setStatus(await startRawDirectionSession());
    } catch (requestError) {
      handleRequestError(requestError);
    } finally {
      setBusy(false);
    }
  };

  const startStep = async (jointId: string, direction: RawDirection) => {
    if (busy || held) return;
    const key = `${jointId}:${direction}`;
    setBusy(true);
    setHeld(key);
    setError(null);
    let heartbeat: number | undefined;
    try {
      await armRawDirectionJoint(jointId);
      heartbeat = window.setInterval(() => {
        void heartbeatRawDirectionTest().catch(() => {
          // The command response or backend watchdog remains authoritative.
        });
      }, 150);
      setStatus(await stepRawDirectionJoint(jointId, direction));
    } catch (requestError) {
      handleRequestError(requestError);
    } finally {
      if (heartbeat !== undefined) window.clearInterval(heartbeat);
      setHeld(null);
      setBusy(false);
    }
  };

  const stop = async () => {
    setHeld(null);
    try {
      setStatus(await stopRawDirectionTest());
    } catch (requestError) {
      handleRequestError(requestError);
    }
  };

  const confirmDraft = async () => {
    setBusy(true);
    setError(null);
    try {
      setStatus(await confirmRawDirectionDraft());
    } catch (requestError) {
      handleRequestError(requestError);
    } finally {
      setBusy(false);
    }
  };

  const recordAlignment = async (jointId: string, matchesUrdf: boolean) => {
    setBusy(true);
    setError(null);
    try {
      setStatus(await recordRawDirectionAlignment(jointId, matchesUrdf));
    } catch (requestError) {
      handleRequestError(requestError);
    } finally {
      setBusy(false);
    }
  };

  const joints = status?.zero_snapshot
    ? Object.entries(status.zero_snapshot.raw_by_joint)
    : [];
  const resolvedCount = status?.calibration_draft?.joints
    .filter((joint) => joint.matches_urdf !== null).length ?? 0;
  const currentEntry = joints.find(([jointId]) => {
    const draft = status?.calibration_draft?.joints.find((joint) => joint.joint_id === jointId);
    return draft?.matches_urdf === null || draft?.matches_urdf === undefined;
  }) ?? null;
  const currentJointId = currentEntry?.[0] ?? null;
  const currentZeroRaw = currentEntry?.[1] ?? null;
  const currentStepLabel = currentJointId === 'j10' ? '1 mm' : '1°';
  const currentObservations = currentJointId
    ? status?.observations.filter((item) => item.joint_id === currentJointId) ?? []
    : [];
  const currentTestedDirections = new Set(currentObservations.map((item) => item.direction));
  const currentObservation = currentObservations.at(-1) ?? null;
  const bothCurrentDirectionsTested = currentTestedDirections.has('RAW_MINUS') &&
    currentTestedDirections.has('RAW_PLUS');
  const rawAuthorizable = summary.readiness?.raw_direction_session_authorizable === true;
  const primaryBlocker = capability.blocked_reasons.find(
    (reason) => reason !== 'RAW_DIRECTION_SESSION_REQUIRED',
  );

  const blockerMessage = primaryBlocker === 'RAW_DIRECTION_ADAPTER_UNAVAILABLE'
    ? '真实舵机写入适配器尚未启用。软件流程已就绪，当前不会驱动机械臂。'
    : primaryBlocker === 'REAL_CONTROL_MODE_REQUIRED'
      ? '当前处于 DRY RUN。切换到经过确认的实体工作台配置后才能开始。'
      : primaryBlocker === 'RAW_DIRECTION_TEST_NOT_ENABLED'
        ? '实体方向验收开关尚未在本机配置中启用。'
        : primaryBlocker
          ? '设备条件发生变化，方向验收暂时不可开始。请展开高级诊断查看原因。'
          : '一次确认后即可连续完成 J10–J15，无需逐轴重新授权。';

  return (
    <section className="raw-workbench" aria-labelledby="raw-direction-title">
      <div className="raw-workbench__header">
        <Crosshair aria-hidden="true" />
        <div>
          <p className="section-kicker">V2 现场工作台</p>
          <h3 id="raw-direction-title">六轴关节方向对照</h3>
          <p>
            当前姿态作为零位，依次用 1 mm / 1° 低速小步运动 J10–J15。你只需要
            对照仿真方向并回答“一致”或“相反”。
          </p>
        </div>
      </div>

      {!rawSession && (
        <div className={`raw-workbench__state${rawAuthorizable ? ' raw-workbench__state--ready' : ''}`} role="status">
          <CircleAlert aria-hidden="true" />
          <div>
            <strong>{rawAuthorizable ? '可以开始一次方向验收会话' : '当前保持安全阻断'}</strong>
            <p>{blockerMessage}</p>
          </div>
        </div>
      )}

      {rawSession && !status?.zero_snapshot && (
        <div className="raw-workbench__start">
          <div>
            <strong>会话已开始</strong>
            <p>下一步会一次读取 J10–J15 当前 Raw 值，作为这台机械臂的零点草稿。</p>
          </div>
          <button
            className="command-button command-button--danger-solid"
            disabled={busy}
            onClick={() => void captureZero()}
            type="button"
          >
            读取六轴零点并开始
          </button>
        </div>
      )}

      {status?.zero_snapshot && (
        <>
          <div className="raw-progress" aria-label="六轴验收进度">
            <div>
              <strong>{resolvedCount} / {joints.length}</strong>
              <span>关节已确认</span>
            </div>
            <ol>
              {joints.map(([jointId]) => {
                const draft = status.calibration_draft?.joints
                  .find((joint) => joint.joint_id === jointId);
                const active = jointId === currentJointId;
                const complete = draft?.matches_urdf !== null &&
                  draft?.matches_urdf !== undefined;
                return (
                  <li
                    className={`${complete ? 'is-complete' : ''}${active ? ' is-active' : ''}`}
                    key={jointId}
                  >
                    <span>{jointId.toUpperCase()}</span>
                    <b>{complete ? '✓' : active ? '当前' : '待测'}</b>
                  </li>
                );
              })}
            </ol>
          </div>

          {currentJointId && currentZeroRaw !== null && (
            <article className="raw-current-joint">
              <header>
                <div>
                  <span>当前关节</span>
                  <strong>{currentJointId.toUpperCase()}</strong>
                </div>
                <div>
                  <span>零点 Raw</span>
                  <strong>{currentZeroRaw}</strong>
                </div>
              </header>
              <p>
                分别点击 −{currentStepLabel} 和 +{currentStepLabel}，观察实体运动；
                每次完成后系统立即请求保持当前位置。
              </p>
              <div className="raw-direction-buttons">
                {(['RAW_MINUS', 'RAW_PLUS'] as const).map((direction) => {
                  const key = `${currentJointId}:${direction}`;
                  const tested = currentTestedDirections.has(direction);
                  return (
                    <button
                      aria-label={`测试 ${currentJointId.toUpperCase()} ${direction === 'RAW_MINUS' ? '负方向' : '正方向'}`}
                      className={`raw-direction-button${held === key ? ' is-held' : ''}${tested ? ' is-tested' : ''}`}
                      disabled={busy}
                      key={direction}
                      onClick={() => void startStep(currentJointId, direction)}
                      type="button"
                    >
                      <span>
                        {direction === 'RAW_MINUS' ? '−' : '+'}{currentStepLabel}
                      </span>
                      <small>{tested ? '已测试 ✓' : '小步测试'}</small>
                    </button>
                  );
                })}
              </div>
              <div className="raw-current-joint__readback">
                <span>最近读数 <strong>{currentObservation?.final_raw ?? '—'}</strong></span>
                <span>命令 {status.command_count} / 24</span>
              </div>
              {bothCurrentDirectionsTested ? (
                <div className="raw-observation">
                  <strong>实体方向是否与 URDF 动画一致？</strong>
                  <div>
                    <button
                      className="command-button command-button--primary"
                      disabled={busy}
                      onClick={() => void recordAlignment(currentJointId, true)}
                      type="button"
                    >
                      一致，继续下一轴
                    </button>
                    <button
                      className="command-button"
                      disabled={busy}
                      onClick={() => void recordAlignment(currentJointId, false)}
                      type="button"
                    >
                      相反，记录并继续
                    </button>
                  </div>
                </div>
              ) : (
                <small className="raw-current-joint__hint">完成两个方向后，系统才会询问方向判断。</small>
              )}
            </article>
          )}

          <button className="command-button command-button--stop raw-stop" onClick={() => void stop()} type="button">
            <Square aria-hidden="true" /> 立即停止 / 保持
          </button>

          {status.calibration_draft?.complete_for_review && (
            <div className="raw-draft-review" role="status">
              <div>
                <strong>六轴方向已完成</strong>
                <p>
                  系统已生成这台 V2 的零点与方向草稿。确认后仍不会自动运行机械臂。
                </p>
                {status.calibration_draft.complete_for_review &&
                  !status.calibration_draft.confirmed_for_review && (
                    <button
                      className="command-button command-button--danger-solid"
                      disabled={busy}
                      onClick={() => void confirmDraft()}
                      type="button"
                    >
                      统一确认本次标定草稿
                    </button>
                  )}
                {status.calibration_draft.confirmed_for_review && (
                  <p className="raw-draft-review__done">已统一确认于 {status.calibration_draft.confirmed_at}</p>
                )}
                <details className="raw-technical-details">
                  <summary>查看候选数据来源</summary>
                  <p>
                    {status.calibration_draft.source} @ {status.calibration_draft.source_revision}；
                    phase 候选 28，Raw 范围沿用 Profile，零点来自本次会话。
                  </p>
                </details>
              </div>
            </div>
          )}
        </>
      )}

      {error && <p className="real-inline-error" role="alert">{error}</p>}
    </section>
  );
}
