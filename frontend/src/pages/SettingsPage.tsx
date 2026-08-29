import { useEffect, useState } from 'react';
import {
  Camera,
  Check,
  ChevronRight,
  CircleAlert,
  Cpu,
  Gauge,
  Minus,
  Network,
  ShieldCheck,
  SlidersHorizontal,
  Wrench,
  X,
} from 'lucide-react';
import { Link } from 'react-router-dom';

import { getVisionCapabilities, getVisionStatus } from '../api/client';
import { API_BASE_URL } from '../api/config';
import type { VisionCapabilities, VisionStatus } from '../api/types';
import { PageIntro } from '../components/PageIntro';
import { useRuntimeStatus } from '../components/runtimeStatusContext';
import { LanSecuritySessionPanel } from '../features/settings/LanSecuritySessionPanel';
import { RuntimeModeSwitch } from '../features/settings/RuntimeModeSwitch';
import { zhBackendMessage, zhBoolean, zhStatus } from '../i18n/zh';

function MatchValue({ value }: { value: boolean | null | undefined }) {
  if (value === true) {
    return (
      <span className="match-value match-value--yes">
        <Check aria-hidden="true" /> 是
      </span>
    );
  }
  if (value === false) {
    return (
      <span className="match-value match-value--no">
        <X aria-hidden="true" /> 否
      </span>
    );
  }
  return (
    <span className="match-value match-value--unknown">
      <Minus aria-hidden="true" /> 未配置
    </span>
  );
}

function StatusBadge({ tone = 'neutral', children }: {
  tone?: 'danger' | 'neutral' | 'ready' | 'warning';
  children: string;
}) {
  return (
    <span className={`settings-badge settings-badge--${tone}`}>
      <span aria-hidden="true" />
      {children}
    </span>
  );
}

function unavailable(value: string | null | undefined): string {
  return value && value.trim() ? value : '未配置';
}

export function SettingsPage() {
  const {
    backend,
    stale,
    robot,
    profile,
    calibration,
    controlMode,
    diagnostics,
    error,
    hardwareAccessPolicy,
    realMotionEnabled,
    pendingAction,
    switchVariant,
  } = useRuntimeStatus();
  const [vision, setVision] = useState<{
    capabilities: VisionCapabilities;
    status: VisionStatus;
  } | null>(null);
  const [visionUnavailable, setVisionUnavailable] = useState(false);
  const [advancedOpen, setAdvancedOpen] = useState(false);
  const switchingDisabled =
    backend !== 'connected' || robot?.connected === true || pendingAction !== null ||
    controlMode !== 'DRY RUN' || hardwareAccessPolicy !== 'DISABLED';
  const activeVariant = robot?.variant ?? profile?.profile.variant ?? 'V2';
  const definitions = profile?.profile.joint_definitions ?? [];
  const enabledJoints = profile?.profile.enabled_joints ?? [];
  const configuredDirections = definitions.filter(
    (definition) => enabledJoints.includes(definition.joint_id) &&
      (definition.direction === 1 || definition.direction === -1),
  ).length;
  const sourceReady = vision?.status.source_state === 'READY' ||
    vision?.status.source_state === 'STREAMING';
  const backendReady = backend === 'connected' && !stale;
  const robotConnected = robot?.connected === true && robot.stale === false;

  useEffect(() => {
    if (backend !== 'connected') {
      setVision(null);
      setVisionUnavailable(false);
      return;
    }
    const controller = new AbortController();
    void Promise.all([
      getVisionCapabilities(controller.signal),
      getVisionStatus(controller.signal),
    ]).then(([capabilities, status]) => {
      if (controller.signal.aborted) return;
      setVision({ capabilities, status });
      setVisionUnavailable(false);
    }).catch(() => {
      if (controller.signal.aborted) return;
      setVision(null);
      setVisionUnavailable(true);
    });
    return () => controller.abort();
  }, [backend]);

  const revealAdvanced = () => {
    setAdvancedOpen(true);
    window.setTimeout(() => {
      document.getElementById('settings-advanced-tools')?.scrollIntoView?.({
        behavior: 'smooth',
        block: 'start',
      });
    }, 0);
  };

  return (
    <div className="page settings-page">
      <PageIntro
        title="设置"
        description="设备、运动、标定、相机、网络与安全"
        detail="未由后端提供的数据会明确标记为未配置或暂不支持。页面不会自动扫描、连接、回零或移动硬件。"
      />

      {(backend === 'unavailable' || error) && (
        <div className="settings-notice" role="status">
          <CircleAlert aria-hidden="true" />
          <span>
            {stale ? '后端不可用，当前设置可能已经过期' : zhBackendMessage(error, '后端不可用')}
          </span>
        </div>
      )}

      <RuntimeModeSwitch />

      <div className="settings-card-grid">
        <section className="settings-product-card settings-product-card--device" aria-labelledby="device-settings-title">
          <header className="settings-product-card__header">
            <div className="settings-product-card__title">
              <Cpu aria-hidden="true" />
              <h2 id="device-settings-title">设备</h2>
            </div>
            <StatusBadge tone={robotConnected ? 'ready' : backendReady ? 'warning' : 'neutral'}>
              {robotConnected ? '已连接' : backendReady ? '未连接' : '不可用'}
            </StatusBadge>
          </header>

          <div className="settings-device-layout">
            <div className="settings-variant-block">
              <fieldset className="variant-selector" disabled={switchingDisabled}>
                <legend>机械臂型号</legend>
                {(['V1', 'V2'] as const).map((variant) => (
                  <button
                    aria-pressed={activeVariant === variant}
                    className={activeVariant === variant ? 'variant-selector__active' : ''}
                    key={variant}
                    onClick={() => void switchVariant(variant)}
                    type="button"
                  >
                    {variant}
                  </button>
                ))}
              </fieldset>
              <p>
                {activeVariant === 'V1'
                  ? '五个旋转关节 · 无直线导轨'
                  : '一条直线导轨 + 五个旋转关节'}
              </p>
            </div>
            <dl className="settings-data-list settings-data-list--two-column">
              <div><dt>设备名称</dt><dd>{unavailable(profile?.profile.display_name)}</dd></div>
              <div><dt>设备编号</dt><dd>{unavailable(robot?.robot_id)}</dd></div>
              <div><dt>连接方式</dt><dd>{hardwareAccessPolicy === 'DISABLED' ? '仿真后端' : '未配置'}</dd></div>
              <div><dt>串口</dt><dd>未配置</dd></div>
              <div><dt>通信协议</dt><dd>未配置</dd></div>
              <div><dt>自动连接</dt><dd>当前版本暂不支持</dd></div>
            </dl>
          </div>
        </section>

        <section className="settings-product-card" aria-labelledby="joint-settings-title">
          <header className="settings-product-card__header">
            <div className="settings-product-card__title">
              <SlidersHorizontal aria-hidden="true" />
              <h2 id="joint-settings-title">关节与运动</h2>
            </div>
          </header>
          <div className="settings-joint-summary" aria-label="启用关节与运动范围">
            {definitions
              .filter((definition) => enabledJoints.includes(definition.joint_id))
              .map((definition) => (
                <div key={definition.joint_id}>
                  <strong>{definition.joint_id.toUpperCase()}</strong>
                  <span>{definition.joint_type === 'PRISMATIC' ? '直线导轨' : '旋转关节'}</span>
                  <small>{definition.minimum}–{definition.maximum} {definition.domain_unit}</small>
                </div>
              ))}
          </div>
          {definitions.length === 0 ? <p className="settings-empty-copy">关节配置不可用</p> : null}
          <dl className="settings-data-list">
            <div><dt>运动范围</dt><dd>{definitions.length > 0 ? '已从当前 Profile 加载' : '未配置'}</dd></div>
            <div><dt>默认控制</dt><dd>步进 / 连续</dd></div>
          </dl>
          <button className="settings-text-action" disabled title="当前版本没有安全的关节配置写入接口" type="button">
            打开关节设置 <ChevronRight aria-hidden="true" />
          </button>
        </section>

        <section className="settings-product-card" aria-labelledby="calibration-settings-title">
          <header className="settings-product-card__header">
            <div className="settings-product-card__title">
              <Gauge aria-hidden="true" />
              <h2 id="calibration-settings-title">标定</h2>
            </div>
            <StatusBadge tone={calibration?.calibration_valid ? 'ready' : calibration?.configured ? 'warning' : 'neutral'}>
              {zhStatus(calibration?.status, '未配置')}
            </StatusBadge>
          </header>
          <dl className="settings-data-list">
            <div><dt>当前版本</dt><dd>{calibration?.configured ? '已配置 · 版本号不可用' : '未配置'}</dd></div>
            <div><dt>零点</dt><dd>{calibration?.configured ? '已配置 · 数量不可用' : '未配置'}</dd></div>
            <div><dt>关节映射</dt><dd><MatchValue value={calibration?.mapping_match} /></dd></div>
            <div><dt>运动方向</dt><dd>{enabledJoints.length > 0 ? `${configuredDirections} / ${enabledJoints.length} 已配置` : '未配置'}</dd></div>
          </dl>
          <div className="settings-card-actions">
            <button className="command-button" disabled title="当前后端没有独立且安全的快速零点标定接口" type="button">
              零点快速标定
            </button>
            <button className="command-button" onClick={revealAdvanced} type="button">完整标定</button>
          </div>
        </section>

        <section className="settings-product-card" aria-labelledby="camera-settings-title">
          <header className="settings-product-card__header">
            <div className="settings-product-card__title">
              <Camera aria-hidden="true" />
              <h2 id="camera-settings-title">相机</h2>
            </div>
            <StatusBadge tone={sourceReady ? 'ready' : visionUnavailable ? 'warning' : 'neutral'}>
              {sourceReady ? '画面可用' : visionUnavailable ? '状态不可用' : '未运行'}
            </StatusBadge>
          </header>
          <dl className="settings-data-list">
            <div><dt>相机来源</dt><dd>{unavailable(vision?.capabilities.source.provider_id)}</dd></div>
            <div>
              <dt>分辨率</dt>
              <dd>{vision?.status.latest_frame
                ? `${vision.status.latest_frame.width_px} × ${vision.status.latest_frame.height_px}`
                : '不可用'}</dd>
            </div>
            <div><dt>访问策略</dt><dd>{vision?.capabilities.camera_access_policy ?? '不可用'}</dd></div>
            <div><dt>画面旋转</dt><dd>当前版本暂不支持</dd></div>
            <div><dt>镜像</dt><dd>当前版本暂不支持</dd></div>
          </dl>
          <div className="settings-card-actions">
            <Link className="command-button" to="/vision">相机设置</Link>
            <Link className="command-button" to="/vision">测试画面</Link>
          </div>
          <p className="settings-safe-note">
            {vision?.capabilities.camera_access_policy === 'SYNTHETIC_ONLY'
              ? '当前会话仅使用内存合成画面；不会枚举、打开或录制本机摄像头。'
              : vision?.capabilities.camera_access_policy === 'DISABLED'
                ? '当前会话已禁用所有图像源与本机摄像头访问。'
                : vision?.capabilities.camera_access_policy === 'LIVE_CAMERA_ALLOWED'
                  ? '进入视觉页后仍需由用户主动打开明确配置的实时相机。'
                  : '相机访问策略尚未由后端确认；不会自动打开本机摄像头。'}
          </p>
        </section>

        <section className="settings-product-card" aria-labelledby="network-settings-title">
          <header className="settings-product-card__header">
            <div className="settings-product-card__title">
              <Network aria-hidden="true" />
              <h2 id="network-settings-title">网络与服务</h2>
            </div>
            <StatusBadge tone={backendReady ? 'ready' : 'neutral'}>{backendReady ? '运行中' : '不可用'}</StatusBadge>
          </header>
          <dl className="settings-data-list">
            <div><dt>后端服务</dt><dd>{backendReady ? 'MOMO Backend' : '不可用'}</dd></div>
            <div><dt>服务地址</dt><dd><code>{API_BASE_URL}</code></dd></div>
            <div><dt>局域网访问</dt><dd>未配置</dd></div>
            <div><dt>自动启动</dt><dd>当前版本暂不支持</dd></div>
          </dl>
          <div className="settings-card-actions">
            <button className="command-button" onClick={() => document.getElementById('lan-security-tools')?.scrollIntoView?.({ behavior: 'smooth' })} type="button">网络设置</button>
            <button className="command-button" disabled title="当前后端没有安全的服务重启接口" type="button">重启服务</button>
          </div>
        </section>

        <section className="settings-product-card" aria-labelledby="safety-settings-title">
          <header className="settings-product-card__header">
            <div className="settings-product-card__title">
              <ShieldCheck aria-hidden="true" />
              <h2 id="safety-settings-title">安全</h2>
            </div>
          </header>
          <dl className="settings-data-list">
            <div><dt>默认启动</dt><dd>{controlMode}</dd></div>
            <div><dt>失联自动停止</dt><dd>由安全租约强制执行</dd></div>
            <div><dt>Home 前确认</dt><dd>已启用</dd></div>
            <div><dt>高速运动确认</dt><dd>当前版本暂不支持</dd></div>
          </dl>
          <div className="settings-safety-state">
            <ShieldCheck aria-hidden="true" />
            <div>
              <strong>真实运动安全状态</strong>
              <span>{controlMode === 'REAL'
                ? realMotionEnabled
                  ? zhStatus(calibration?.real_readiness, '等待安全状态')
                  : '真机运动已阻止'
                : 'DRY RUN · 实体运动保持禁用'}</span>
            </div>
          </div>
        </section>

        <section className="settings-product-card" aria-labelledby="advanced-settings-title">
          <header className="settings-product-card__header">
            <div className="settings-product-card__title">
              <Wrench aria-hidden="true" />
              <h2 id="advanced-settings-title">高级</h2>
            </div>
          </header>
          <p className="settings-advanced-copy">Profile、Servo ID、Raw、指纹、运行策略、日志与版本信息</p>
          <dl className="settings-data-list">
            <div><dt>Profile</dt><dd>{unavailable(profile?.profile.source)}</dd></div>
            <div><dt>Servo ID</dt><dd>{definitions.length > 0
              ? definitions.map((definition) => `${definition.joint_id.toUpperCase()}:${definition.servo_id ?? '—'}`).join(' · ')
              : '未配置'}</dd></div>
            <div><dt>Raw</dt><dd>{robot?.raw_positions ? '后端已提供' : '不可用'}</dd></div>
            <div><dt>版本</dt><dd>{unavailable(diagnostics?.backend_version ?? undefined)}</dd></div>
          </dl>
          <button className="settings-text-action" onClick={revealAdvanced} type="button">
            打开高级设置 <ChevronRight aria-hidden="true" />
          </button>
        </section>
      </div>

      <details className="settings-tools-disclosure" id="lan-security-tools">
        <summary>网络与浏览器安全会话</summary>
        <LanSecuritySessionPanel />
      </details>

      <details
        className="settings-tools-disclosure settings-tools-disclosure--hardware"
        id="settings-advanced-tools"
        onToggle={(event) => setAdvancedOpen(event.currentTarget.open)}
        open={advancedOpen}
      >
        <summary>高级 · 配置与标定兼容性</summary>
        <p className="settings-tools-disclosure__warning">
          此区域只展示配置与兼容性信息，不提供第二套设备连接或运动入口。
        </p>
        <dl className="settings-advanced-facts">
          <div><dt>配置指纹</dt><dd><code>{unavailable(profile?.fingerprint)}</code></dd></div>
          <div><dt>运动学指纹</dt><dd><code>{unavailable(profile?.kinematics_fingerprint)}</code></dd></div>
          <div><dt>运行策略</dt><dd>{unavailable(diagnostics?.stage_policy)}</dd></div>
          <div><dt>Legacy 来源</dt><dd><code>{unavailable(diagnostics?.legacy_source_commit)}</code></dd></div>
          <div><dt>运行状态文件</dt><dd><code>{unavailable(diagnostics?.runtime_state_path)}</code></dd></div>
          <div><dt>运行状态有效</dt><dd>{diagnostics ? zhBoolean(diagnostics.runtime_state_valid) : '未配置'}</dd></div>
        </dl>
        <div className="settings-compatibility-panel">
          <h3>标定兼容性</h3>
          <dl className="compatibility-grid">
            <div><dt>已配置</dt><dd><MatchValue value={calibration?.configured} /></dd></div>
            <div><dt>模板标定</dt><dd><MatchValue value={calibration?.template} /></dd></div>
            <div><dt>型号匹配</dt><dd><MatchValue value={calibration?.variant_match} /></dd></div>
            <div><dt>配置匹配</dt><dd><MatchValue value={calibration?.profile_match} /></dd></div>
            <div><dt>关节集合匹配</dt><dd><MatchValue value={calibration?.joint_set_match} /></dd></div>
            <div><dt>硬件映射</dt><dd><MatchValue value={calibration?.mapping_match} /></dd></div>
            <div><dt>数据完整</dt><dd><MatchValue value={calibration?.complete} /></dd></div>
          </dl>
          <div className="readiness-block">
            <ShieldCheck aria-hidden="true" />
            <div>
              <strong>真机就绪状态：{zhStatus(calibration?.real_readiness)}</strong>
              <ul>
                {(calibration?.blocking_reasons ?? ['Waiting for backend diagnostics']).map(
                  (reason) => <li key={reason}>{zhBackendMessage(reason)}</li>,
                )}
              </ul>
            </div>
          </div>
        </div>
      </details>
    </div>
  );
}
