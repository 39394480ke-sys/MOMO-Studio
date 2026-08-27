import { Check, CircleAlert, Minus, ShieldCheck, X } from 'lucide-react';

import { PageIntro } from '../components/PageIntro';
import { useRuntimeStatus } from '../components/runtimeStatusContext';
import { LanSecuritySessionPanel } from '../features/settings/LanSecuritySessionPanel';
import { RealHardwarePanel } from '../features/settings/RealHardwarePanel';
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
    pendingAction,
    switchVariant,
  } = useRuntimeStatus();
  const switchingDisabled =
    backend !== 'connected' || robot?.connected === true || pendingAction !== null ||
    controlMode !== 'DRY RUN' || hardwareAccessPolicy !== 'DISABLED';
  const activeVariant = robot?.variant ?? profile?.profile.variant ?? 'V2';

  return (
    <div className="page">
      <PageIntro
        title="设置"
        description="查看机械臂身份、配置来源、标定兼容性和运行策略。"
        detail="只有当前机械臂断开连接时才能切换 V1/V2 型号。"
      />

      {(backend === 'unavailable' || error) && (
        <div className="settings-notice" role="status">
          <CircleAlert aria-hidden="true" />
          <span>
            {stale ? '后端不可用，当前设置可能已经过期' : zhBackendMessage(error, '后端不可用')}
          </span>
        </div>
      )}

      <section className="settings-section" aria-labelledby="robot-settings-title">
        <div className="settings-section__heading">
          <p className="section-kicker">机械臂</p>
          <h2 id="robot-settings-title">当前型号</h2>
        </div>
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
        <p className="variant-summary">
          {activeVariant === 'V1'
            ? 'V1 · 五个旋转关节 · 无直线导轨'
            : 'V2 · 一条直线导轨 + 五个旋转关节'}
        </p>
        <dl className="settings-list">
          <div>
            <dt>启用关节</dt>
            <dd>{profile?.profile.enabled_joints.join(', ').toUpperCase() ?? '待加载'}</dd>
          </div>
          <div>
            <dt>配置指纹</dt>
            <dd>
              <code>{profile?.fingerprint ?? '待加载'}</code>
            </dd>
          </div>
          <div>
            <dt>配置来源</dt>
            <dd>{profile?.profile.source ?? '待加载'}</dd>
          </div>
          <div>
            <dt>来源版本</dt>
            <dd>
              <code>{profile?.profile.source_revision ?? '待加载'}</code>
            </dd>
          </div>
          <div>
            <dt>验证状态</dt>
            <dd>{zhStatus(profile?.profile.verification_status)}</dd>
          </div>
          <div>
            <dt>是否模板</dt>
            <dd>{profile ? zhBoolean(profile.profile.template) : '待加载'}</dd>
          </div>
        </dl>
      </section>

      <section className="settings-section" aria-labelledby="calibration-settings-title">
        <div className="settings-section__heading settings-section__heading--inline">
          <div>
            <p className="section-kicker">标定</p>
            <h2 id="calibration-settings-title">兼容性</h2>
          </div>
          <strong className="settings-status">{zhStatus(calibration?.status)}</strong>
        </div>
        <dl className="compatibility-grid">
          <div>
            <dt>已配置</dt>
            <dd><MatchValue value={calibration?.configured} /></dd>
          </div>
          <div>
            <dt>模板标定</dt>
            <dd><MatchValue value={calibration?.template} /></dd>
          </div>
          <div>
            <dt>型号匹配</dt>
            <dd><MatchValue value={calibration?.variant_match} /></dd>
          </div>
          <div>
            <dt>配置匹配</dt>
            <dd><MatchValue value={calibration?.profile_match} /></dd>
          </div>
          <div>
            <dt>关节集合匹配</dt>
            <dd><MatchValue value={calibration?.joint_set_match} /></dd>
          </div>
          <div>
            <dt>硬件映射</dt>
            <dd><MatchValue value={calibration?.mapping_match} /></dd>
          </div>
          <div>
            <dt>数据完整</dt>
            <dd><MatchValue value={calibration?.complete} /></dd>
          </div>
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
      </section>

      <section className="settings-section" aria-labelledby="diagnostics-settings-title">
        <div className="settings-section__heading">
          <p className="section-kicker">诊断</p>
          <h2 id="diagnostics-settings-title">阶段策略</h2>
        </div>
        <dl className="settings-list">
          <div>
            <dt>硬件访问</dt>
            <dd>{zhStatus(diagnostics?.hardware_access_policy ?? 'DISABLED')}</dd>
          </div>
          <div>
            <dt>运行状态文件</dt>
            <dd><code>{diagnostics?.runtime_state_path ?? 'data/runtime/robots/primary.json'}</code></dd>
          </div>
          <div>
            <dt>运行状态有效</dt>
            <dd>{diagnostics ? zhBoolean(diagnostics.runtime_state_valid) : '待加载'}</dd>
          </div>
          <div>
            <dt>运行状态诊断</dt>
            <dd>{zhBackendMessage(diagnostics?.runtime_state_diagnostic, '待加载')}</dd>
          </div>
          <div>
            <dt>后端版本</dt>
            <dd>{diagnostics?.backend_version ?? '待加载'}</dd>
          </div>
          <div>
            <dt>旧项目来源</dt>
            <dd><code>{diagnostics?.legacy_source_commit ?? '待加载'}</code></dd>
          </div>
          <div>
            <dt>策略标识</dt>
            <dd>{diagnostics?.stage_policy ?? 'STAGE_4_DRY_RUN_ONLY'}</dd>
          </div>
        </dl>
      </section>

      <LanSecuritySessionPanel />
      <RealHardwarePanel />
    </div>
  );
}
