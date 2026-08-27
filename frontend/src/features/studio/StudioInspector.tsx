import {
  ArrowDownToLine,
  ArrowUpToLine,
  Copy,
  LocateFixed,
  RefreshCcw,
  Radio,
  Trash2,
  X,
} from 'lucide-react';
import { useEffect, useRef } from 'react';

import type { MotionEasing, MotionKeyframe, MotionMode } from '../../api/types';

interface StudioInspectorProps {
  busy: boolean;
  frame: MotionKeyframe | null;
  frameIndex: number;
  frameLimitReached: boolean;
  mobileOpen: boolean;
  motionDisabledReason: string | null;
  runtimeMode: 'DRY RUN' | 'REAL';
  onAddAfter: (frameId: string) => void;
  onAddBefore: (frameId: string) => void;
  onCaptureAfter: (frameId: string) => void;
  onCaptureBefore: (frameId: string) => void;
  onCloseMobile: () => void;
  onDelete: (frameId: string) => void;
  onDuplicate: (frameId: string) => void;
  onEasingChange: (frameId: string, easing: MotionEasing) => void;
  onGoto: (frameId: string) => void;
  onHoldChange: (frameId: string, holdS: number) => void;
  onLabelChange: (frameId: string, label: string) => void;
  onModeChange: (frameId: string, mode: MotionMode) => void;
  onReplace: (frameId: string) => void;
  onTransitionDurationChange: (frameId: string, durationS: number) => void;
}

function finite(value: number): string {
  return Number.isFinite(value) ? value.toFixed(2) : '—';
}

export function StudioInspector({
  busy,
  frame,
  frameIndex,
  frameLimitReached,
  mobileOpen,
  motionDisabledReason,
  runtimeMode,
  onAddAfter,
  onAddBefore,
  onCaptureAfter,
  onCaptureBefore,
  onCloseMobile,
  onDelete,
  onDuplicate,
  onEasingChange,
  onGoto,
  onHoldChange,
  onLabelChange,
  onModeChange,
  onReplace,
  onTransitionDurationChange,
}: StudioInspectorProps) {
  const inspectorRef = useRef<HTMLElement | null>(null);
  const closeRef = useRef(onCloseMobile);
  closeRef.current = onCloseMobile;
  const position = frame?.pose_snapshot.tcp_pose.position_mm;
  const orientation = frame?.pose_snapshot.tcp_pose.orientation_quaternion_xyzw;
  const transition = frame?.incoming_transition;

  useEffect(() => {
    if (!mobileOpen) return;
    const previousFocus = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    const inspector = inspectorRef.current;
    const focusable = () => Array.from(inspector?.querySelectorAll<HTMLElement>(
      'button:not(:disabled), input:not(:disabled), select:not(:disabled), [tabindex]:not([tabindex="-1"])',
    ) ?? []);
    const first = focusable()[0] ?? inspector;
    first?.focus();
    const onKeyDown = (event: globalThis.KeyboardEvent) => {
      if (event.key === 'Escape') {
        event.preventDefault();
        closeRef.current();
        return;
      }
      if (event.key !== 'Tab') return;
      const controls = focusable();
      if (controls.length === 0) {
        event.preventDefault();
        inspector?.focus();
        return;
      }
      const firstControl = controls[0];
      const lastControl = controls.at(-1);
      if (event.shiftKey && document.activeElement === firstControl) {
        event.preventDefault();
        lastControl?.focus();
      } else if (!event.shiftKey && document.activeElement === lastControl) {
        event.preventDefault();
        firstControl.focus();
      }
    };
    document.addEventListener('keydown', onKeyDown);
    return () => {
      document.removeEventListener('keydown', onKeyDown);
      previousFocus?.focus();
    };
  }, [mobileOpen]);

  return (
    <>
    <div aria-hidden="true" className={`studio-inspector-scrim${mobileOpen ? ' studio-inspector-scrim--open' : ''}`} onClick={onCloseMobile} />
    <aside
      aria-labelledby="studio-inspector-heading"
      aria-modal={mobileOpen ? 'true' : undefined}
      className={`studio-inspector${mobileOpen ? ' studio-inspector--mobile-open' : ''}`}
      ref={inspectorRef}
      role={mobileOpen ? 'dialog' : undefined}
      tabIndex={-1}
    >
      <header className="studio-panel-heading">
        <div>
          <p className="section-kicker">关键帧详情</p>
          <h2 id="studio-inspector-heading">检查器</h2>
        </div>
        <button
          aria-label="关闭检查器"
          className="mini-command studio-inspector__close"
          onClick={onCloseMobile}
          type="button"
        >
          <X aria-hidden="true" />
        </button>
      </header>

      {!frame ? (
        <p className="studio-inspector-empty">选择一个关键帧，以查看和编辑其不可变快照的元数据。</p>
      ) : (
        <div className="studio-inspector__body">
          <label className="studio-field">
            <span>关键帧名称</span>
            <input
              aria-label="关键帧名称"
              disabled={busy}
              maxLength={200}
              onChange={(event) => onLabelChange(frame.id, event.target.value)}
              value={frame.label}
            />
          </label>

          <div className="studio-field-grid">
            <label className="studio-field">
              <span>停留时长</span>
              <span className="studio-number-field">
                <input
                  aria-label="关键帧停留秒数"
                  disabled={busy}
                  max="600"
                  min="0"
                  onChange={(event) => onHoldChange(frame.id, Number(event.target.value))}
                  step="0.05"
                  type="number"
                  value={frame.hold_s}
                />
                <span>s</span>
              </span>
            </label>
            <label className="studio-field">
              <span>进入过渡时长</span>
              <span className="studio-number-field">
                <input
                  aria-describedby={!transition ? 'first-frame-transition-note' : undefined}
                  aria-label="进入过渡时长（秒）"
                  disabled={busy || !transition}
                  max="600"
                  min="0.05"
                  onChange={(event) => onTransitionDurationChange(frame.id, Number(event.target.value))}
                  step="0.05"
                  type="number"
                  value={transition?.duration_s ?? 0}
                />
                <span>s</span>
              </span>
            </label>
          </div>
          {!transition ? (
            <p className="studio-field-note" id="first-frame-transition-note">
              第一个关键帧没有进入过渡。
            </p>
          ) : null}

          <div className="studio-field-grid">
            <label className="studio-field">
              <span>运动模式</span>
              <select
                aria-label="进入过渡的运动模式"
                disabled={busy || !transition}
                onChange={(event) => onModeChange(frame.id, event.target.value as MotionMode)}
                value={transition?.motion_mode ?? 'JOINT'}
              >
                <option value="JOINT">关节插值（JOINT）</option>
                <option value="CARTESIAN_LINEAR">笛卡尔直线（CARTESIAN LINEAR）</option>
              </select>
            </label>
            <label className="studio-field">
              <span>缓动</span>
              <select
                aria-label="进入过渡的缓动方式"
                disabled={busy || !transition}
                onChange={(event) => onEasingChange(frame.id, event.target.value as MotionEasing)}
                value={transition?.easing ?? 'SMOOTHSTEP'}
              >
                <option value="LINEAR">线性</option>
                <option value="SMOOTHSTEP">平滑步进</option>
                <option value="EASE_IN_OUT">缓入缓出</option>
              </select>
            </label>
          </div>

          <section className="studio-snapshot" aria-labelledby="studio-tcp-heading">
            <header>
              <strong id="studio-tcp-heading">TCP · {frame.pose_snapshot.tcp_pose.frame}</strong>
              <span>{frame.pose_snapshot.robot_variant}</span>
            </header>
            <dl>
              <div><dt>X</dt><dd>{finite(position?.x ?? Number.NaN)} mm</dd></div>
              <div><dt>Y</dt><dd>{finite(position?.y ?? Number.NaN)} mm</dd></div>
              <div><dt>Z</dt><dd>{finite(position?.z ?? Number.NaN)} mm</dd></div>
              <div className="studio-snapshot__wide">
                <dt>四元数 XYZW</dt>
                <dd>
                  {finite(orientation?.x ?? Number.NaN)}, {finite(orientation?.y ?? Number.NaN)}, {finite(orientation?.z ?? Number.NaN)}, {finite(orientation?.w ?? Number.NaN)}
                </dd>
              </div>
            </dl>
          </section>

          <section className="studio-snapshot" aria-labelledby="studio-joints-heading">
            <header>
              <strong id="studio-joints-heading">关节快照</strong>
              <span>启用 {Object.keys(frame.pose_snapshot.joint_state.positions).length} 个关节</span>
            </header>
            <dl>
              {Object.entries(frame.pose_snapshot.joint_state.positions).map(([jointId, value]) => (
                <div key={jointId}>
                  <dt>{jointId.toUpperCase()}</dt>
                  <dd>{finite(value)} {frame.pose_snapshot.joint_state.units[jointId]}</dd>
                </div>
              ))}
            </dl>
          </section>

          <dl className="studio-provenance">
            <div>
              <dt>来源机位</dt>
              <dd>{frame.source_pose_id ?? '现场捕获 / 内嵌快照'}</dd>
            </div>
            <div>
              <dt>捕获时间</dt>
              <dd>{frame.pose_snapshot.captured_at}</dd>
            </div>
            <div>
              <dt>配置指纹</dt>
              <dd>{frame.pose_snapshot.profile_fingerprint}</dd>
            </div>
          </dl>

          <div className="studio-inspector__actions">
            <button className="command-button" disabled={busy || frameLimitReached} onClick={() => onAddBefore(frame.id)} type="button">
              <ArrowUpToLine aria-hidden="true" /> 插入到前面
            </button>
            <button className="command-button" disabled={busy || frameLimitReached} onClick={() => onAddAfter(frame.id)} type="button">
              <ArrowDownToLine aria-hidden="true" /> 插入到后面
            </button>
            <button className="command-button" disabled={busy || frameLimitReached} onClick={() => onDuplicate(frame.id)} type="button">
              <Copy aria-hidden="true" /> 复制
            </button>
            <button className="command-button" disabled={busy || frameLimitReached || motionDisabledReason !== null} onClick={() => onCaptureBefore(frame.id)} type="button">
              <Radio aria-hidden="true" /> 捕获到前面
            </button>
            <button className="command-button" disabled={busy || frameLimitReached || motionDisabledReason !== null} onClick={() => onCaptureAfter(frame.id)} type="button">
              <Radio aria-hidden="true" /> 捕获到后面
            </button>
            <button
              className="command-button command-button--primary"
              disabled={busy || motionDisabledReason !== null}
              onClick={() => onGoto(frame.id)}
              title={motionDisabledReason ?? `通过${runtimeMode === 'REAL' ? '真机能力' : '仿真'}安全入口前往此快照`}
              type="button"
            >
              <LocateFixed aria-hidden="true" /> {runtimeMode === 'REAL' ? '真机' : '仿真'}前往
            </button>
            <button
              className="command-button"
              disabled={busy || motionDisabledReason !== null}
              onClick={() => onReplace(frame.id)}
              title={motionDisabledReason ?? `使用当前${runtimeMode === 'REAL' ? '真机' : '仿真'}完整快照替换`}
              type="button"
            >
              <RefreshCcw aria-hidden="true" /> 替换为当前状态
            </button>
            <button className="command-button command-button--danger" disabled={busy} onClick={() => onDelete(frame.id)} type="button">
              <Trash2 aria-hidden="true" /> 删除
            </button>
          </div>
          <p className="studio-field-note">关键帧 {frameIndex + 1} · 快照数据已内嵌，不会随来源机位改变。</p>
          {motionDisabledReason ? <p className="studio-field-note">机械臂操作不可用 · {motionDisabledReason}</p> : null}
          {frameLimitReached ? <p className="studio-field-note">不能继续插入或复制 · 已达到 1000 个关键帧上限。</p> : null}
        </div>
      )}
    </aside>
    </>
  );
}
