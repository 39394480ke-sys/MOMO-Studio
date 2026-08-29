import { useCallback, useEffect, useState } from 'react';
import { CircleAlert, RotateCw, ShieldCheck, X } from 'lucide-react';

import { getRuntimeModeStatus, switchRuntimeMode } from '../../api/client';
import type { ControlMode, RuntimeModeStatus } from '../../api/types';
import { useRuntimeStatus } from '../../components/runtimeStatusContext';
import { zhBackendMessage } from '../../i18n/zh';

const RESTART_TIMEOUT_MS = 15_000;
const POLL_INTERVAL_MS = 350;

function wait(delayMs: number): Promise<void> {
  return new Promise((resolve) => window.setTimeout(resolve, delayMs));
}

export function RuntimeModeSwitch() {
  const runtime = useRuntimeStatus();
  const [status, setStatus] = useState<RuntimeModeStatus | null>(null);
  const [target, setTarget] = useState<ControlMode | null>(null);
  const [estopReady, setEstopReady] = useState(false);
  const [workspaceClear, setWorkspaceClear] = useState(false);
  const [phase, setPhase] = useState<'idle' | 'restarting' | 'submitting'>('idle');
  const [error, setError] = useState<string | null>(null);

  const loadStatus = useCallback(async (signal?: AbortSignal) => {
    const next = await getRuntimeModeStatus(signal);
    setStatus(next);
    return next;
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    void loadStatus(controller.signal).catch((reason: unknown) => {
      if (!controller.signal.aborted) {
        setError(reason instanceof Error ? reason.message : '运行模式状态不可用');
      }
    });
    return () => controller.abort();
  }, [loadStatus]);

  const closeDialog = () => {
    if (phase !== 'idle') return;
    setTarget(null);
    setEstopReady(false);
    setWorkspaceClear(false);
    setError(null);
  };

  const confirmSwitch = async () => {
    if (target === null) return;
    setPhase('submitting');
    setError(null);
    try {
      await switchRuntimeMode({
        target_mode: target,
        confirm_robot_disconnected: runtime.robot?.connected === false,
        confirm_physical_estop_ready: target === 'REAL' && estopReady,
        confirm_workspace_clear: target === 'REAL' && workspaceClear,
      });
      setPhase('restarting');
      const deadline = Date.now() + RESTART_TIMEOUT_MS;
      while (Date.now() < deadline) {
        await wait(POLL_INTERVAL_MS);
        try {
          const next = await getRuntimeModeStatus();
          if (next.active_mode === target && !next.restart_in_progress) {
            setStatus(next);
            setTarget(null);
            setEstopReady(false);
            setWorkspaceClear(false);
            setPhase('idle');
            await runtime.refresh();
            return;
          }
        } catch {
          // A short connection gap is expected while Uvicorn rebuilds the product graph.
        }
      }
      throw new Error('后端重启超时，请检查本地服务终端');
    } catch (reason) {
      setPhase('idle');
      setError(reason instanceof Error ? reason.message : '运行模式切换失败');
    }
  };

  const activeMode = status?.active_mode ?? (runtime.controlMode === 'DRY RUN' ? 'DRY_RUN' : 'REAL');
  const robotConnected = runtime.robot?.connected === true;
  const switchDisabled = !status?.switch_supported || robotConnected || phase !== 'idle';
  const realUnavailable = status !== null && !status.real_config_available;

  return (
    <section className="runtime-mode-card" aria-labelledby="runtime-mode-title">
      <div className="runtime-mode-card__copy">
        <span className="runtime-mode-card__eyebrow">Runtime</span>
        <h2 id="runtime-mode-title">运行模式</h2>
        <p>切换会重新装配后端，但不会自动连接、回零或移动机械臂。</p>
      </div>
      <div className="runtime-mode-card__control">
        <div aria-label="运行模式选择" className="runtime-mode-segment" role="group">
          <button
            aria-pressed={activeMode === 'DRY_RUN'}
            disabled={switchDisabled || activeMode === 'DRY_RUN'}
            onClick={() => setTarget('DRY_RUN')}
            type="button"
          >
            DRY RUN
          </button>
          <button
            aria-pressed={activeMode === 'REAL'}
            disabled={switchDisabled || activeMode === 'REAL' || realUnavailable}
            onClick={() => setTarget('REAL')}
            type="button"
          >
            REAL
          </button>
        </div>
        <span className={`runtime-mode-state runtime-mode-state--${activeMode === 'REAL' ? 'real' : 'dry'}`}>
          {activeMode === 'REAL'
            ? status?.configured_real_motion_enabled
              ? '真机生产控制'
              : '真机调试工作台'
            : '仿真执行器'}
        </span>
      </div>
      <div className="runtime-mode-card__meta">
        {robotConnected ? '请先断开机械臂再切换模式' : null}
        {!status?.switch_supported ? '请使用受支持的本地启动器开启一键切换' : null}
        {realUnavailable
          ? status.blocking_reasons.map((reason) => zhBackendMessage(reason)).join(' · ')
          : null}
        {error ? <span className="runtime-mode-error" role="alert">{error}</span> : null}
      </div>

      {target ? (
        <div aria-labelledby="runtime-mode-dialog-title" aria-modal="true" className="runtime-mode-dialog" role="dialog">
          <div className="runtime-mode-dialog__panel">
            <button aria-label="关闭运行模式切换" className="runtime-mode-dialog__close" disabled={phase !== 'idle'} onClick={closeDialog} type="button">
              <X aria-hidden="true" />
            </button>
            <div className="runtime-mode-dialog__icon">
              {target === 'REAL' ? <ShieldCheck aria-hidden="true" /> : <RotateCw aria-hidden="true" />}
            </div>
            <h2 id="runtime-mode-dialog-title">切换到 {target === 'REAL' ? 'REAL' : 'DRY RUN'}</h2>
            <p>
              {target === 'REAL'
                ? '将启用已配置的真实工作台。重启后机械臂仍保持断开，需要你主动点击连接。'
                : '将停止使用真实执行器并重新启动为仿真模式。'}
            </p>
            {target === 'REAL' ? (
              <div className="runtime-mode-confirmations">
                <label><input checked={estopReady} onChange={(event) => setEstopReady(event.target.checked)} type="checkbox" />物理急停已就绪</label>
                <label><input checked={workspaceClear} onChange={(event) => setWorkspaceClear(event.target.checked)} type="checkbox" />机械臂工作区已清空</label>
              </div>
            ) : (
              <div className="runtime-mode-dialog__notice"><CircleAlert aria-hidden="true" />切换过程不会提交任何运动命令。</div>
            )}
            <div className="runtime-mode-dialog__actions">
              <button className="command-button" disabled={phase !== 'idle'} onClick={closeDialog} type="button">取消</button>
              <button
                className="primary-button"
                disabled={phase !== 'idle' || (target === 'REAL' && (!estopReady || !workspaceClear))}
                onClick={() => void confirmSwitch()}
                type="button"
              >
                {phase === 'idle' ? '切换并重启' : phase === 'submitting' ? '正在提交…' : '正在重启…'}
              </button>
            </div>
          </div>
        </div>
      ) : null}
    </section>
  );
}
