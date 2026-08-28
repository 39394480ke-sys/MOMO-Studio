import {
  AlertTriangle,
  Camera,
  CameraOff,
  Crosshair,
  Radar,
  ShieldCheck,
  Square,
} from 'lucide-react';

import type { VisionFollowConfiguration, VisionProviderCapability } from '../../api/types';
import { zhBackendMessage, zhStatus } from '../../i18n/zh';
import type { VisionWorkspace } from './useVisionWorkspace';

function detectorFor(workspace: VisionWorkspace, kind: 'person' | 'face') {
  return workspace.capabilities?.detectors.find(
    (candidate) => `${candidate.provider_id} ${candidate.kind}`.toLowerCase().includes(kind),
  ) ?? null;
}

function updateNumber(
  workspace: VisionWorkspace,
  key: keyof VisionFollowConfiguration,
  value: number,
) {
  if (!Number.isFinite(value)) return;
  workspace.setConfiguration((current) => ({ ...current, [key]: value }));
}

function Capability({ capability }: { capability: VisionProviderCapability }) {
  return (
    <li className="vision-capability">
      <span
        aria-hidden="true"
        className={`vision-capability__dot${capability.available ? ' vision-capability__dot--available' : ''}`}
      />
      <div>
        <strong>{capability.provider_id}</strong>
        <span>{capability.available ? capability.active ? '当前使用' : '可用' : '不可用'}</span>
        <small>模型来源 · {capability.model_source}</small>
        <small>说明 · {zhBackendMessage(capability.notice)}</small>
        {capability.reason ? <small>{zhBackendMessage(capability.reason)}</small> : null}
      </div>
    </li>
  );
}

function NumericControl({
  label,
  value,
  min,
  max,
  step,
  unit,
  disabled = false,
  onChange,
}: {
  label: string;
  value: number;
  min: number;
  max: number;
  step: number;
  unit?: string;
  disabled?: boolean;
  onChange: (value: number) => void;
}) {
  return (
    <label className="vision-number-control">
      <span>{label}</span>
      <span className="vision-number-control__field">
        <input
          aria-label={label}
          disabled={disabled}
          max={max}
          min={min}
          onChange={(event) => onChange(event.currentTarget.valueAsNumber)}
          step={step}
          type="number"
          value={value}
        />
        {unit ? <small>{unit}</small> : null}
      </span>
    </label>
  );
}

export function VisionControls({ workspace }: { workspace: VisionWorkspace }) {
  const person = detectorFor(workspace, 'person');
  const face = detectorFor(workspace, 'face');
  const follow = workspace.status?.follow;
  const tracking = workspace.status?.tracking;
  const targetLocked = tracking?.status === 'LOCKED';
  const robotConnected = workspace.status?.robot_state === 'CONNECTED';
  const sourceOperational = workspace.status?.source_state === 'READY'
    || workspace.status?.source_state === 'STREAMING';
  const liveCameraOpen = workspace.readOnlyLiveCamera && sourceOperational;
  const latestFrame = workspace.status?.latest_frame ?? null;
  const frameFresh = latestFrame !== null
    && latestFrame.age_ms <= workspace.configuration.frame_freshness_limit_s * 1000;
  const sourceAvailable = workspace.capabilities?.camera_access_policy !== 'DISABLED'
    && workspace.capabilities?.source.available === true
    && workspace.capabilities.stream.available;
  let detectionBlockReason: string | null = null;
  if (!workspace.online) detectionBlockReason = '后端不可用';
  else if (!workspace.statusReachable) detectionBlockReason = '视觉状态不可用';
  else if (!sourceAvailable) detectionBlockReason = '视觉图像源不可用';
  else if (workspace.streamFailed) detectionBlockReason = '视觉视频流已断开';
  else if (!sourceOperational) detectionBlockReason = '视觉图像源尚未运行';
  else if (!frameFresh) detectionBlockReason = '请等待最新画面';

  let startReason: string | null = null;
  if (!workspace.followAllowed) {
    startReason = workspace.followBlockedReason ?? '后端尚未授权对应能力';
  } else if (!workspace.online) startReason = '后端不可用';
  else if (!workspace.statusReachable) startReason = '视觉状态不可用';
  else if (!workspace.capabilities) startReason = '正在加载视觉能力';
  else if (
    workspace.runtimeMode === 'REAL' &&
    !workspace.capabilities.real_follow_allowed
  ) {
    startReason = workspace.capabilities.real_follow_blocked_reason;
  } else if (!sourceAvailable) startReason = '视觉图像源或受限视频流不可用';
  else if (workspace.streamFailed) startReason = '视觉视频流已断开';
  else if (!workspace.mapping) startReason = '当前配置没有经过验证的水平/俯仰关节映射';
  else if (!robotConnected) {
    startReason = workspace.runtimeMode === 'REAL'
      ? '后端报告真机机械臂未连接'
      : '请连接仿真机械臂';
  } else if (!sourceOperational) {
    startReason = `视觉图像源状态：${zhStatus(workspace.status?.source_state, '未就绪')}`;
  } else if (!frameFresh) startReason = '请等待最新画面';
  else if (!targetLocked) startReason = '请选择并锁定一个最新目标';
  else if (follow?.active) startReason = '视觉跟随已经启动';

  const startDisabled = startReason !== null || workspace.busy !== null;
  const stopAvailable = follow?.active || workspace.busy === 'start-follow';
  const tuningDisabled = workspace.readOnlyLiveCamera
    || follow?.active === true
    || workspace.busy === 'start-follow';
  const targetLabel = workspace.status?.selection
    ? tracking ? '已跟踪区域' : '手动区域'
    : '未选择';

  return (
    <aside className="vision-controls" aria-label="视觉控制">
      <section className="vision-control-card vision-control-card--primary">
        <div className="vision-primary-heading">
          <div>
            <p className="eyebrow">目标状态</p>
            <h2>跟踪</h2>
          </div>
          <div className="vision-tracking-badges">
            <span className={`vision-tracking-state${targetLocked ? ' vision-tracking-state--locked' : ''}`}>
              {zhStatus(tracking?.status, workspace.status?.selection ? '已选择' : '无目标')}
            </span>
            <span>置信度 {tracking ? tracking.confidence.toFixed(2) : '—'}</span>
          </div>
        </div>

        <dl className="vision-tracking-list" aria-label="目标跟踪状态">
          <div><dt>目标</dt><dd>{targetLabel}</dd></div>
          <div><dt>误差 X</dt><dd>{follow?.error_x?.toFixed(3) ?? '—'}</dd></div>
          <div><dt>误差 Y</dt><dd>{follow?.error_y?.toFixed(3) ?? '—'}</dd></div>
          <div><dt>EMA X</dt><dd>{follow?.ema_error_x?.toFixed(3) ?? '—'}</dd></div>
          <div><dt>EMA Y</dt><dd>{follow?.ema_error_y?.toFixed(3) ?? '—'}</dd></div>
          <div><dt>画面延迟</dt><dd>{latestFrame ? `${Math.round(latestFrame.age_ms)} ms` : '—'}</dd></div>
        </dl>

        <div className="vision-target-actions">
          <button
            className="command-button"
            disabled={workspace.readOnlyLiveCamera || !workspace.status?.selection || workspace.busy !== null}
            onClick={() => void workspace.clearTarget()}
            type="button"
          >清除选择</button>
          <button
            className="command-button"
            disabled={workspace.readOnlyLiveCamera || !workspace.status?.selection || workspace.busy !== null}
            onClick={() => void workspace.resetTracking()}
            type="button"
          >重置跟踪器</button>
        </div>

        <div className="vision-card-divider" />

        <div className="vision-follow-heading">
          <div>
            <p className="eyebrow">{workspace.runtimeMode === 'REAL' ? '真机能力控制器' : '仿真控制器'}</p>
            <h2>跟随</h2>
          </div>
          <span>{follow?.active ? '跟随运行' : '跟随已停止'}</span>
        </div>
        <div className="vision-follow-grid">
          <NumericControl disabled={tuningDisabled} label="X 轴死区" min={0} max={0.4} step={0.01} value={workspace.configuration.dead_zone_x} onChange={(value) => updateNumber(workspace, 'dead_zone_x', value)} />
          <NumericControl disabled={tuningDisabled} label="Y 轴死区" min={0} max={0.4} step={0.01} value={workspace.configuration.dead_zone_y} onChange={(value) => updateNumber(workspace, 'dead_zone_y', value)} />
          <NumericControl disabled={tuningDisabled} label="EMA 平滑系数" min={0.05} max={1} step={0.05} value={workspace.configuration.ema_alpha} onChange={(value) => updateNumber(workspace, 'ema_alpha', value)} />
          <NumericControl disabled={tuningDisabled} label="跟随增益" min={0.05} max={2} step={0.05} value={workspace.configuration.gain} onChange={(value) => updateNumber(workspace, 'gain', value)} />
          <NumericControl disabled={tuningDisabled} label="最大单步" min={0.1} max={10} step={0.1} unit="°" value={workspace.configuration.max_step} onChange={(value) => updateNumber(workspace, 'max_step', value)} />
          <NumericControl disabled={tuningDisabled} label="目标丢失超时" min={0.1} max={10} step={0.1} unit="s" value={workspace.configuration.target_lost_limit_s} onChange={(value) => updateNumber(workspace, 'target_lost_limit_s', value)} />
        </div>
        {tuningDisabled ? <p className="vision-provider-note">当前跟随会话期间不能修改参数。</p> : null}
        <dl className="vision-error-readout" aria-label="跟随误差读数">
          <div><dt>误差 X / Y</dt><dd>{follow?.error_x?.toFixed(3) ?? '—'} / {follow?.error_y?.toFixed(3) ?? '—'}</dd></div>
          <div><dt>EMA X / Y</dt><dd>{follow?.ema_error_x?.toFixed(3) ?? '—'} / {follow?.ema_error_y?.toFixed(3) ?? '—'}</dd></div>
          <div><dt>关节映射</dt><dd>{workspace.mapping ? `${workspace.mapping.pan_joint} / ${workspace.mapping.tilt_joint}` : '不可用'}</dd></div>
          <div><dt>映射状态</dt><dd>{zhStatus(workspace.mapping?.verification_status, '不可用')}</dd></div>
        </dl>
        <div className="vision-follow-actions">
          <button
            className="command-button command-button--primary"
            disabled={startDisabled}
            onClick={() => void workspace.startFollow()}
            title={startReason ?? `启动受会话租约约束的${workspace.runtimeMode === 'REAL' ? '真机' : '仿真'}跟随`}
            type="button"
          >启动{workspace.runtimeMode === 'REAL' ? '真机' : '仿真'}跟随</button>
          <button
            className="command-button command-button--stop"
            disabled={!stopAvailable || workspace.busy === 'stop-follow'}
            onClick={() => void workspace.stopFollow()}
            type="button"
          ><Square aria-hidden="true" /> 停止跟随</button>
        </div>
        {startReason && !follow?.active ? <p className="vision-disabled-reason">暂时无法跟随 · {startReason}</p> : null}
        {follow?.stop_reason ? <p className="vision-stop-reason">上次停止原因 · {follow.stop_reason}</p> : null}
        <p className="vision-blocked-reason">
          {workspace.capabilities?.real_follow_blocked_reason
            ?? workspace.status?.real_follow_blocked_reason
            ?? '现场验收完成前，真机视觉跟随保持禁用。'}
        </p>
      </section>

      <section className="vision-control-card vision-control-card--source">
        <div className="vision-control-card__heading">
          <ShieldCheck aria-hidden="true" />
          <div><p className="eyebrow">安全边界</p><h2>图像源与策略</h2></div>
        </div>
        <dl className="vision-definition-list">
          <div><dt>图像源</dt><dd>{workspace.capabilities?.source.provider_id ?? '等待中'}</dd></div>
          <div><dt>相机策略</dt><dd>{workspace.capabilities?.camera_access_policy ?? '不可用'}</dd></div>
          <div><dt>图像源状态</dt><dd>{zhStatus(workspace.status?.source_state, workspace.online ? '等待中' : '离线')}</dd></div>
          <div><dt>运行模式</dt><dd>{workspace.runtimeMode === 'REAL' ? '真机' : '仿真'}</dd></div>
          <div>
            <dt>实时相机</dt>
            <dd>{workspace.readOnlyLiveCamera ? liveCameraOpen ? '已打开 · 只读' : '已关闭' : '未配置'}</dd>
          </div>
        </dl>
        {workspace.readOnlyLiveCamera ? (
          <>
            <div className="vision-follow-actions">
              <button
                className="command-button command-button--primary"
                disabled={!workspace.online || liveCameraOpen || workspace.busy !== null}
                onClick={() => void workspace.openCamera()}
                type="button"
              >
                <Camera aria-hidden="true" />
                {workspace.busy === 'open-camera' ? '正在打开…' : '打开实时相机'}
              </button>
              <button
                className="command-button"
                disabled={!liveCameraOpen || workspace.busy !== null}
                onClick={() => void workspace.closeCamera()}
                type="button"
              >
                <CameraOff aria-hidden="true" />
                {workspace.busy === 'close-camera' ? '正在关闭…' : '关闭实时相机'}
              </button>
            </div>
            <p className="vision-provider-note">
              当前仅提供只读预览；目标选择、检测、跟踪、录像和跟随都保持禁用。
            </p>
          </>
        ) : null}
      </section>

      <section className="vision-control-card vision-control-card--detectors">
        <div className="vision-control-card__heading">
          <Radar aria-hidden="true" />
          <div><p className="eyebrow">目标工具</p><h2>本地检测</h2></div>
        </div>
        <div className="vision-button-grid">
          <button
            className="command-button"
            disabled={workspace.readOnlyLiveCamera || !person?.available || detectionBlockReason !== null || workspace.busy !== null}
            onClick={() => void workspace.detect('person')}
            title={!person?.available
              ? person?.reason ?? '人体检测器不可用'
              : detectionBlockReason ?? '在当前精确画面中检测人体'}
            type="button"
          ><Crosshair aria-hidden="true" /> 检测人体</button>
          <button
            className="command-button"
            disabled={workspace.readOnlyLiveCamera || !face?.available || detectionBlockReason !== null || workspace.busy !== null}
            onClick={() => void workspace.detect('face')}
            title={!face?.available
              ? face?.reason ?? '人脸检测器不可用'
              : detectionBlockReason ?? '在当前精确画面中检测人脸'}
            type="button"
          ><Crosshair aria-hidden="true" /> 检测人脸</button>
        </div>
        {!person?.available || !face?.available ? (
          <p className="vision-provider-note">不可用的检测器会保持禁用；系统不会自动下载模型。</p>
        ) : null}
        <ul className="vision-capabilities">
          {workspace.capabilities ? (
            [workspace.capabilities.source, workspace.capabilities.stream, ...workspace.capabilities.trackers, ...workspace.capabilities.detectors]
              .map((capability) => <Capability capability={capability} key={`${capability.kind}-${capability.provider_id}`} />)
          ) : <li className="vision-capability vision-capability--empty">正在发现可用能力</li>}
        </ul>
      </section>

      {workspace.error ? (
        <div className="vision-error" role="alert">
          <AlertTriangle aria-hidden="true" />
          <span>{workspace.error}</span>
          <button aria-label="关闭视觉错误" onClick={workspace.clearError} type="button">×</button>
        </div>
      ) : null}
    </aside>
  );
}
