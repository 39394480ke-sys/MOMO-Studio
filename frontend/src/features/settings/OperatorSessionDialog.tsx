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
  return <code>{value ?? '未配置'}</code>;
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
              {rawDirection ? '一次确认 · 约 15 分钟连续验收' : `短期授权 · ${evidence.session_purpose}`}
            </p>
            <h2 id="operator-session-title">
              {commissioning
                ? '开启只读现场验收会话'
                : commissioningMotion
                  ? '开启现场运动测试会话'
                  : rawDirection
                    ? '开始六轴 Raw ± 方向验收'
                  : '开启真机运动会话'}
            </h2>
          </div>
          <button
            aria-label="关闭操作员会话对话框"
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
              ? '此会话只能读取已配置的舵机 ID，用于诊断和标定；不能运动、回零、扫描、修改扭矩或写寄存器。'
              : commissioningMotion
                ? '此会话只允许执行由后端限制的低速单关节现场测试；不能回零、多关节运动、笛卡尔运动、播放或视觉跟随。'
                : rawDirection
                  ? '确认一次后，系统会在同一会话中读取六轴零点并依次验收 J10–J15。每次只允许一个关节在零点附近小步运动，松手立即停止。'
                : '这是软件运动授权，不能替代物理急停。请确保急停可触达，并清空机械臂工作空间。'}
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
                <div><dt>配置指纹</dt><dd><EvidenceValue value={evidence.profile_fingerprint} /></dd></div>
                <div><dt>串口</dt><dd><EvidenceValue value={evidence.masked_serial_port} /></dd></div>
                <div><dt>用途</dt><dd>{evidence.session_purpose}</dd></div>
                <div><dt>确认文本</dt><dd><code>{evidence.required_confirmation_text}</code></dd></div>
              </dl>
            </details>
          </>
        ) : (
          <>
            <dl className="real-evidence-grid">
              <div><dt>机械臂</dt><dd><EvidenceValue value={evidence.robot_id} /></dd></div>
              <div><dt>机械臂单元</dt><dd><EvidenceValue value={evidence.robot_unit_id ?? null} /></dd></div>
              <div><dt>用途</dt><dd>{evidence.session_purpose}</dd></div>
              <div><dt>型号</dt><dd>{evidence.variant ?? '未配置'}</dd></div>
              <div><dt>配置指纹</dt><dd><EvidenceValue value={evidence.profile_fingerprint} /></dd></div>
              <div><dt>标定指纹</dt><dd><EvidenceValue value={evidence.calibration_fingerprint} /></dd></div>
              <div><dt>运动学指纹</dt><dd><EvidenceValue value={evidence.kinematics_fingerprint} /></dd></div>
              <div><dt>串口</dt><dd><EvidenceValue value={evidence.masked_serial_port} /></dd></div>
              <div><dt>舵机 ID</dt><dd>{evidence.masked_servo_ids.join(', ') || '未配置'}</dd></div>
              <div><dt>协议</dt><dd><EvidenceValue value={evidence.protocol} /></dd></div>
            </dl>
            <label className="real-confirmation-field">
              <span>请输入完全一致的确认文本</span>
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
              <span>我确认已经测试过的物理急停存在且可以触达。</span>
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
            <span>我确认机械臂工作空间已清空，并已为本次测试做好防护。</span>
          </label>
        )}

        {error && <p className="real-inline-error" role="alert">{error}</p>}

        <div className="real-dialog__actions">
          <button className="command-button" disabled={pending} onClick={onCancel} type="button">
            取消
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
              ? '正在授权…'
              : commissioning
                ? '授权只读会话'
                : commissioningMotion
                  ? '授权运动测试会话'
                  : rawDirection
                    ? '开始方向验收'
                  : '授权真机运动会话'}
          </button>
        </div>
      </section>
    </div>
  );
}
