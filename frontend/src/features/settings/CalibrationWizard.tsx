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
  return '受保护的标定请求失败。';
}

function integerOrNull(value: string): number | null {
  if (!/^-?\d+$/.test(value.trim())) return null;
  const result = Number(value);
  return Number.isSafeInteger(result) ? result : null;
}

interface CalibrationWizardProps {
  connected: boolean;
  initiallyConfigured: boolean;
  onSessionInvalidated?: () => void;
  onStatusChange?: (status: 'NOT_CONFIGURED' | 'DRAFT' | 'CONFIGURED') => void;
}

export function CalibrationWizard({
  connected,
  initiallyConfigured,
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
    const next = await startCalibrationSession();
    setStatus(next);
    selectDraftJoint(next, next.required_joint_ids[0] ?? '');
    setPreview(null);
    setSaved(null);
    onStatusChange?.('DRAFT');
  });

  const read = () => run('read', async () => {
    if (!status || !selectedJoint) return;
    const next = await readCalibrationJoint(status.session_id, selectedJoint);
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
    const next = await previewCalibrationJoint(status.session_id, {
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
    if (status) await cancelCalibrationSession(status.session_id);
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
            <h3 id="calibration-wizard-title">标定版本已保存</h3>
            <p>版本 {saved.revision} · {saved.variant}</p>
            <p>标定已配置 · 等待现场验收 · 真机运动已阻止</p>
            <code>{saved.calibration_fingerprint}</code>
          </div>
        </div>
        <button className="command-button" onClick={() => setSaved(null)} type="button">
          关闭摘要
        </button>
      </section>
    );
  }

  if (!status) {
    return (
      <section className="calibration-wizard" aria-labelledby="calibration-wizard-title">
        <div>
          <p className="section-kicker">受保护 · 只读取所选关节</p>
          <h3 id="calibration-wizard-title">当前角度标定向导</h3>
          <strong>{initiallyConfigured ? '标定已配置' : '未配置'}</strong>
          <p>
            本向导不会移动关节、写入舵机、更改模式、扫描 ID，也不会把示例标定升级为正式数据；
            仅使用当前明确建立的设备连接。
          </p>
        </div>
        <button
          className="command-button"
          disabled={!connected || pending !== null}
          onClick={() => void start()}
          type="button"
        >
          {initiallyConfigured ? '开始受保护的重新标定' : '开始首次标定'}
        </button>
        {!connected && <small>请先明确连接设备并确认诊断结果。</small>}
        {error && <p className="real-inline-error" role="alert">{error}</p>}
      </section>
    );
  }

  return (
    <section className="calibration-wizard" aria-labelledby="calibration-wizard-title">
      <div className="settings-section__heading settings-section__heading--inline">
        <div>
          <p className="section-kicker">
            草稿 · {status.base_revision === null
              ? '首次标定 → 版本 1'
              : `版本 ${status.base_revision} → ${status.base_revision + 1}`}
          </p>
          <h3 id="calibration-wizard-title">当前角度标定向导</h3>
        </div>
        <button className="command-button" disabled={pending !== null} onClick={() => void cancel()} type="button">
          取消
        </button>
      </div>

      <div className="calibration-wizard__warning">
        <CircleAlert aria-hidden="true" />
        <p>请保持物理急停可触达。读取所选关节位置不是运动命令。</p>
      </div>

      {error && <p className="real-inline-error" role="alert">{error}</p>}

      <div className="calibration-wizard__progress" aria-label="标定关节进度">
        {status.required_joint_ids.map((jointId) => (
          <span className={status.confirmed_joint_ids.includes(jointId) ? 'is-confirmed' : ''} key={jointId}>
            {jointId.toUpperCase()}
          </span>
        ))}
      </div>

      <div className="calibration-wizard__form">
        <label>
          <span>所选关节</span>
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
          <span>当前 Raw</span>
          <strong>{status.selected_joint_id === selectedJoint && status.observed_raw !== null
            ? status.observed_raw
            : '尚未读取'}</strong>
          <button className="command-button" disabled={!selectedJoint || pending !== null} onClick={() => void read()} type="button">
            读取所选关节
          </button>
        </div>
        <label>
          <span>当前逻辑值</span>
          <input disabled={pending !== null} inputMode="decimal" onChange={(event) => setLogicalValue(event.target.value)} value={logicalValue} />
        </label>
        <label>
          <span>方向</span>
          <select disabled={pending !== null} onChange={(event) => setDirection(event.target.value === '-1' ? -1 : 1)} value={direction}>
            <option value={1}>+1</option>
            <option value={-1}>−1</option>
          </select>
        </label>
        <label>
          <span>多圈相位（需要时）</span>
          <input disabled={pending !== null} inputMode="numeric" onChange={(event) => setPhase(event.target.value)} value={phase} />
        </label>
        <label>
          <span>Raw 下限</span>
          <input disabled={pending !== null} inputMode="numeric" onChange={(event) => setRawLower(event.target.value)} value={rawLower} />
        </label>
        <label>
          <span>Raw 上限</span>
          <input disabled={pending !== null} inputMode="numeric" onChange={(event) => setRawUpper(event.target.value)} value={rawUpper} />
        </label>
      </div>

      <button className="command-button" disabled={!canPreview || pending !== null} onClick={() => void createPreview()} type="button">
        预览映射
      </button>

      {preview && (
        <div className="calibration-preview">
          <h4>所选关节映射预览</h4>
          <dl>
            <div><dt>关节 / 舵机</dt><dd>{preview.joint_id.toUpperCase()} / {preview.servo_id}</dd></div>
            <div><dt>Raw → 逻辑值</dt><dd>{preview.observed_raw} → {preview.logical_value} {preview.unit}</dd></div>
            <div><dt>方向 / 零位</dt><dd>{preview.direction > 0 ? '+1' : '−1'} / {preview.home_present_raw}</dd></div>
            <div><dt>相位 / 范围</dt><dd>{preview.phase ?? '不适用'} / {preview.raw_bounds.join('…')}</dd></div>
            <div><dt>往返换算</dt><dd>{preview.round_trip_logical_value} {preview.unit}</dd></div>
            <div><dt>映射误差</dt><dd>{preview.mapping_error}</dd></div>
          </dl>
          <label className="real-confirmation-field">
            <span>请输入完全一致的关节确认文本</span>
            <code>{JOINT_CONFIRMATION}</code>
            <input
              aria-label="输入完全一致的关节确认文本"
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
            仅确认此关节
          </button>
        </div>
      )}

      {selectedConfirmed && !preview && <p className="calibration-wizard__confirmed">所选关节已在当前版本中确认。</p>}

      {status.state === 'READY_TO_SAVE' && (
        <div className="calibration-save">
          <h4>完整标定预览</h4>
          <p>
            已确认全部 {status.required_joint_ids.length} 个启用关节。保存时会创建一个新的原子版本并备份上一版本，
            不会写入舵机。
          </p>
          {status.save_preview ? (
            <>
              <div className="real-table-wrap">
                <table className="real-diagnostics-table">
                  <caption>完整的候选标定映射</caption>
                  <thead>
                    <tr><th>关节</th><th>舵机</th><th>模式</th><th>方向</th><th>零位</th><th>相位</th><th>Raw 范围</th></tr>
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
              <span>候选标定指纹</span>
              <code>{status.save_preview.proposed_calibration_fingerprint}</code>
            </>
          ) : (
            <p className="real-inline-error" role="alert">
              后端没有提供完整的保存预览，当前无法保存。
            </p>
          )}
          <label className="real-confirmation-field">
            <span>请输入完全一致的保存确认文本</span>
            <code>{SAVE_CONFIRMATION}</code>
            <input
              aria-label="输入完全一致的保存确认文本"
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
            <Save aria-hidden="true" /> 保存新标定版本
          </button>
        </div>
      )}

      <footer className="calibration-wizard__footer">
        <RotateCcw aria-hidden="true" />
        回滚是独立的精确确认操作，并且始终会创建一个新的后续版本。
      </footer>
    </section>
  );
}
