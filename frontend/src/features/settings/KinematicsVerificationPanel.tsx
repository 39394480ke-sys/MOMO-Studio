import { CircleAlert, Crosshair, Ruler } from 'lucide-react';
import { useEffect, useState, type FormEvent } from 'react';

import {
  addKinematicsVerificationMeasurement,
  commitKinematicsVerificationDraft,
  getKinematicsVerificationStatus,
  startKinematicsVerificationDraft,
} from '../../api/client';
import type {
  FieldAcceptanceProgress,
  KinematicsVerificationDraft,
  KinematicsVerificationStatus,
  TcpPose,
} from '../../api/types';
import { useRealSession } from '../../components/realSessionContext';
import { useRuntimeStatus } from '../../components/runtimeStatusContext';

interface MeasurementFields {
  label: string;
  frame: string;
  x: string;
  y: string;
  z: string;
  qx: string;
  qy: string;
  qz: string;
  qw: string;
}

const EMPTY_MEASUREMENT: MeasurementFields = {
  label: '',
  frame: 'base',
  x: '',
  y: '',
  z: '',
  qx: '0',
  qy: '0',
  qz: '0',
  qw: '1',
};

function message(error: unknown): string {
  return error instanceof Error ? error.message : '运动学验证请求失败。';
}

function numeric(value: string, label: string): number {
  const parsed = Number(value);
  if (!Number.isFinite(parsed)) throw new TypeError(`${label}必须是有限数值。`);
  return parsed;
}

function thresholds(position: string, orientation: string) {
  const maxPosition = numeric(position, '最大位置误差');
  const maxOrientation = numeric(orientation, '最大姿态误差');
  if (maxPosition <= 0 || maxPosition > 25) {
    throw new RangeError('最大位置误差必须大于 0 且不超过 25 mm。');
  }
  if (maxOrientation <= 0 || maxOrientation > 15) {
    throw new RangeError('最大姿态误差必须大于 0 且不超过 15°。');
  }
  return {
    max_position_error_mm: maxPosition,
    max_orientation_error_deg: maxOrientation,
  };
}

function measuredTcp(fields: MeasurementFields): TcpPose {
  const frame = fields.frame.trim();
  if (!frame || frame.length > 128) {
    throw new TypeError('实测 TCP 坐标系名称必须包含 1–128 个字符。');
  }
  const orientation = {
    x: numeric(fields.qx, '四元数 X'),
    y: numeric(fields.qy, '四元数 Y'),
    z: numeric(fields.qz, '四元数 Z'),
    w: numeric(fields.qw, '四元数 W'),
  };
  if (
    orientation.x ** 2 + orientation.y ** 2 + orientation.z ** 2 + orientation.w ** 2 <
    1e-24
  ) {
    throw new TypeError('实测 TCP 四元数不能为零。');
  }
  return {
    frame,
    position_mm: {
      x: numeric(fields.x, '实测 TCP X'),
      y: numeric(fields.y, '实测 TCP Y'),
      z: numeric(fields.z, '实测 TCP Z'),
    },
    orientation_quaternion_xyzw: orientation,
  };
}

function tcpSummary(pose: TcpPose): string {
  const { x, y, z } = pose.position_mm;
  return `${pose.frame}: ${x.toFixed(2)}, ${y.toFixed(2)}, ${z.toFixed(2)} mm`;
}

function jointStateSummary(
  point: KinematicsVerificationDraft['points'][number],
): string {
  const positions = Object.entries(point.joint_state.positions).map(([jointId, value]) => {
    const unit = point.joint_state.units?.[jointId] ?? '';
    return `${jointId}: ${value} ${unit}`.trim();
  }).join(' · ');
  return `序列 ${point.joint_state_sequence} · 采集于 ${point.joint_state_captured_at} · ${positions}`;
}

export function KinematicsVerificationPanel({
  fieldProgress,
  onEvidenceChanged,
}: {
  fieldProgress: FieldAcceptanceProgress | null;
  onEvidenceChanged: () => Promise<unknown>;
}) {
  const runtime = useRuntimeStatus();
  const { summary, refresh: refreshSession } = useRealSession();
  const [status, setStatus] = useState<KinematicsVerificationStatus | null>(null);
  const [draft, setDraft] = useState<KinematicsVerificationDraft | null>(null);
  const [positionThreshold, setPositionThreshold] = useState('5');
  const [orientationThreshold, setOrientationThreshold] = useState('5');
  const [measurement, setMeasurement] = useState<MeasurementFields>(EMPTY_MEASUREMENT);
  const [pending, setPending] = useState<'draft' | 'measurement' | 'commit' | null>(null);
  const [error, setError] = useState<string | null>(null);

  const sessionAuthorized = summary.session?.purpose === 'REAL_MOTION' &&
    summary.session.scopes.includes('REAL_JOINT_MOTION') &&
    summary.capabilityDetails.real_joint_motion.ready &&
    summary.capabilityDetails.real_joint_motion.authorized &&
    !summary.stale;
  const jointAcceptanceComplete = fieldProgress?.joint_motion_accepted === true;

  useEffect(() => {
    if (runtime.backend !== 'connected' || runtime.controlMode !== 'REAL' || runtime.stale) {
      setStatus(null);
      return undefined;
    }
    const controller = new AbortController();
    void getKinematicsVerificationStatus(controller.signal)
      .then((next) => {
        if (!controller.signal.aborted) setStatus(next);
      })
      .catch((caught) => {
        if (!controller.signal.aborted) setError(message(caught));
      });
    return () => controller.abort();
  }, [runtime.backend, runtime.controlMode, runtime.stale]);

  useEffect(() => {
    if (draft && draft.operator_session_id !== summary.session?.session_id) {
      setDraft(null);
      setError('操作员会话已变化，请重新创建实测 TCP 草稿。');
    }
  }, [draft, summary.session?.session_id]);

  const startDraft = async () => {
    if (!sessionAuthorized || !jointAcceptanceComplete) return;
    setPending('draft');
    setError(null);
    try {
      const next = await startKinematicsVerificationDraft(
        thresholds(positionThreshold, orientationThreshold),
      );
      if (next.operator_session_id !== summary.session?.session_id) {
        throw new Error('后端返回了属于其他操作员会话的运动学草稿。');
      }
      setDraft(next);
    } catch (caught) {
      setError(message(caught));
    } finally {
      setPending(null);
    }
  };

  const addMeasurement = async (event: FormEvent) => {
    event.preventDefault();
    if (!draft || !sessionAuthorized) return;
    const label = measurement.label.trim();
    if (!label || label.length > 128) {
      setError('测量点名称必须包含 1–128 个字符。');
      return;
    }
    setPending('measurement');
    setError(null);
    try {
      const next = await addKinematicsVerificationMeasurement(draft.draft_id, {
        label,
        measured_tcp: measuredTcp(measurement),
      });
      if (next.operator_session_id !== summary.session?.session_id) {
        throw new Error('后端返回了属于其他操作员会话的测量结果。');
      }
      setDraft(next);
      setMeasurement(EMPTY_MEASUREMENT);
    } catch (caught) {
      setError(message(caught));
    } finally {
      setPending(null);
    }
  };

  const commitDraft = async () => {
    if (!draft || draft.points.length < 3 || !sessionAuthorized) return;
    setPending('commit');
    setError(null);
    try {
      const evidence = await commitKinematicsVerificationDraft(draft.draft_id);
      setStatus({
        state: 'VALID',
        stale_fields: [],
        evidence_id: evidence.id,
        point_count: evidence.test_points.length,
      });
      setDraft(null);
      await Promise.all([onEvidenceChanged(), refreshSession()]);
    } catch (caught) {
      setError(message(caught));
    } finally {
      setPending(null);
    }
  };

  const startAllowed = sessionAuthorized && jointAcceptanceComplete &&
    status !== null && status.state !== 'VALID';

  return (
    <section className="kinematics-verification" aria-labelledby="kinematics-verification-title">
      <header>
        <Crosshair aria-hidden="true" />
        <div>
          <p className="section-kicker">实测现场证据</p>
          <h4 id="kinematics-verification-title">运动学验证</h4>
          <p>在至少三个不同关节状态下，将后端预测的 TCP 位姿与独立实测的 TCP 位姿进行对比。</p>
        </div>
      </header>

      <dl className="kinematics-verification__status">
        <div><dt>已保存证据</dt><dd>{status?.state ?? '加载中'}</dd></div>
        <div><dt>已保存测量点</dt><dd>{status?.point_count ?? '—'}</dd></div>
        <div><dt>草稿测量点</dt><dd>{draft?.points.length ?? 0}</dd></div>
        <div><dt>机器人单元</dt><dd><code>{draft?.robot_unit_id ?? fieldProgress?.robot_unit_id ?? '必填'}</code></dd></div>
      </dl>

      {status?.stale_fields.length ? (
        <div className="commissioning-motion__blocked" role="status">
          <CircleAlert aria-hidden="true" />
          <div>
            <strong>已有运动学证据已过期</strong>
            <ul>{status.stale_fields.map((field) => <li key={field}>{field}</li>)}</ul>
          </div>
        </div>
      ) : null}

      {!jointAcceptanceComplete && (
        <p className="real-inline-note">开始实测 TCP 验证前，请先确认已保存的单关节运动证据。</p>
      )}
      {!sessionAuthorized && (
        <div className="commissioning-motion__blocked" role="status">
          <CircleAlert aria-hidden="true" />
          <div>
            <strong>写入实测 TCP 数据需要一个已授权 REAL_JOINT_MOTION 的有效 REAL_MOTION 会话。</strong>
            <ul>
              {summary.capabilityDetails.real_joint_motion.blocked_reasons.map((reason) => (
                <li key={reason}>{reason}</li>
              ))}
              {summary.capabilityDetails.real_joint_motion.required_evidence.map((item) => (
                <li key={item}>所需证据：{item}</li>
              ))}
            </ul>
          </div>
        </div>
      )}

      {!draft && (
        <div className="kinematics-verification__start">
          <label>
            最大位置误差（mm）
            <input
              max="25"
              min="0.001"
              onChange={(event) => setPositionThreshold(event.target.value)}
              step="0.1"
              type="number"
              value={positionThreshold}
            />
          </label>
          <label>
            最大姿态误差（deg）
            <input
              max="15"
              min="0.001"
              onChange={(event) => setOrientationThreshold(event.target.value)}
              step="0.1"
              type="number"
              value={orientationThreshold}
            />
          </label>
          <button
            className="command-button"
            disabled={!startAllowed || pending !== null}
            onClick={() => void startDraft()}
            type="button"
          >
            <Ruler aria-hidden="true" /> {pending === 'draft' ? '正在创建草稿…' : '创建实测 TCP 草稿'}
          </button>
        </div>
      )}

      {draft && (
        <>
          <div className="kinematics-verification__draft-facts">
            <strong>草稿已绑定当前操作员会话</strong>
            <span>检查表：{draft.verification_checklist_version}</span>
            <span>软件：<code>{draft.software_commit}</code></span>
            <span>设备：<code>{draft.device_fingerprint}</code></span>
            <span>位置阈值 ≤ {draft.thresholds.max_position_error_mm} mm</span>
            <span>姿态阈值 ≤ {draft.thresholds.max_orientation_error_deg}°</span>
          </div>

          <form className="kinematics-measurement" onSubmit={(event) => void addMeasurement(event)}>
            <div className="kinematics-measurement__snapshot">
              <strong>由服务器采集的关节快照</strong>
              <p>提交测量点时，后端会采集并验证最新硬件读数；浏览器中的状态不会被用作关节证据。</p>
            </div>
            <label className="kinematics-measurement__wide">
              测量点名称
              <input
                maxLength={128}
                onChange={(event) => setMeasurement((current) => ({ ...current, label: event.target.value }))}
                placeholder="例如：前侧低位测量点"
                required
                value={measurement.label}
              />
            </label>
            <label>
              坐标系
              <input
                maxLength={128}
                onChange={(event) => setMeasurement((current) => ({ ...current, frame: event.target.value }))}
                required
                value={measurement.frame}
              />
            </label>
            {(['x', 'y', 'z'] as const).map((axis) => (
              <label key={axis}>
                实测 {axis.toUpperCase()}（mm）
                <input
                  onChange={(event) => setMeasurement((current) => ({ ...current, [axis]: event.target.value }))}
                  required
                  step="any"
                  type="number"
                  value={measurement[axis]}
                />
              </label>
            ))}
            {(['qx', 'qy', 'qz', 'qw'] as const).map((axis) => (
              <label key={axis}>
                {axis.toUpperCase()}
                <input
                  onChange={(event) => setMeasurement((current) => ({ ...current, [axis]: event.target.value }))}
                  required
                  step="any"
                  type="number"
                  value={measurement[axis]}
                />
              </label>
            ))}
            <p className="kinematics-measurement__note">
              请输入独立取得的实体测量值。后端会绑定自己采集的最新关节快照；MOMO Studio 不会把模型标签当作证据。
            </p>
            <button
              className="command-button"
              disabled={!sessionAuthorized || pending !== null}
              type="submit"
            >
              {pending === 'measurement' ? '后端正在计算残差…' : '添加实测点'}
            </button>
          </form>

          {draft.points.length > 0 && (
            <div className="table-scroll">
              <table className="diagnostics-table">
                <thead>
                  <tr>
                    <th>名称</th>
                    <th>后端关节快照</th>
                    <th>预测 TCP</th>
                    <th>实测 TCP</th>
                    <th>位置误差</th>
                    <th>姿态误差</th>
                  </tr>
                </thead>
                <tbody>
                  {draft.points.map((point) => (
                    <tr key={point.point_id}>
                      <td>{point.label}</td>
                      <td title={`操作员会话 ${point.snapshot_session_id}`}>
                        {jointStateSummary(point)}
                      </td>
                      <td>{tcpSummary(point.predicted_tcp)}</td>
                      <td>{tcpSummary(point.measured_tcp)}</td>
                      <td>{point.position_error_mm.toFixed(3)} mm</td>
                      <td>{point.orientation_error_deg.toFixed(3)}°</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}

          <button
            className="command-button command-button--danger-solid"
            disabled={draft.points.length < 3 || !sessionAuthorized || pending !== null}
            onClick={() => void commitDraft()}
            type="button"
          >
            {pending === 'commit' ? '正在保存实测证据…' : '保存运动学实测证据'}
          </button>
          {draft.points.length < 3 && (
            <p className="real-inline-note">至少需要三个经后端评估的测量点；各点必须使用不同关节状态，且残差需要通过阈值检查。</p>
          )}
        </>
      )}

      {error && <p className="real-inline-error" role="alert">{error}</p>}
    </section>
  );
}
