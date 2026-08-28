import { Copy, Trash2, X } from 'lucide-react';
import { useEffect, useRef } from 'react';

import type { MotionKeyframe, MotionMode } from '../../api/types';

interface StudioInspectorProps {
  busy: boolean;
  frame: MotionKeyframe | null;
  frameCount: number;
  frameIndex: number;
  frameLimitReached: boolean;
  mobileOpen: boolean;
  onCloseMobile: () => void;
  onDelete: (frameId: string) => void;
  onDuplicate: (frameId: string) => void;
  onLabelChange: (frameId: string, label: string) => void;
  onModeChange: (frameId: string, mode: MotionMode) => void;
  onTransitionDurationChange: (frameId: string, durationS: number) => void;
}

export function StudioInspector({
  busy,
  frame,
  frameCount,
  frameIndex,
  frameLimitReached,
  mobileOpen,
  onCloseMobile,
  onDelete,
  onDuplicate,
  onLabelChange,
  onModeChange,
  onTransitionDurationChange,
}: StudioInspectorProps) {
  const inspectorRef = useRef<HTMLElement | null>(null);
  const closeRef = useRef(onCloseMobile);
  closeRef.current = onCloseMobile;
  const transition = frame?.incoming_transition;
  const deleteDisabled = busy || frameCount <= 2;

  useEffect(() => {
    if (!mobileOpen) return;
    const previousFocus = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    const inspector = inspectorRef.current;
    const focusable = () => Array.from(inspector?.querySelectorAll<HTMLElement>(
      'button:not(:disabled), input:not(:disabled), select:not(:disabled), [tabindex]:not([tabindex="-1"])',
    ) ?? []);
    (focusable()[0] ?? inspector)?.focus();
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
      const first = controls[0];
      const last = controls.at(-1);
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last?.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
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
      <div
        aria-hidden="true"
        className={`studio-inspector-scrim${mobileOpen ? ' studio-inspector-scrim--open' : ''}`}
        onClick={onCloseMobile}
      />
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
            <p className="section-kicker">Inspector</p>
            <h2 id="studio-inspector-heading">关键帧属性</h2>
          </div>
          <span className="studio-inspector__index">{frameIndex >= 0 ? `K${frameIndex + 1}` : '—'}</span>
          <button
            aria-label="关闭关键帧属性"
            className="mini-command studio-inspector__close"
            onClick={onCloseMobile}
            type="button"
          >
            <X aria-hidden="true" />
          </button>
        </header>

        {!frame ? (
          <div className="studio-inspector-empty">
            <strong>尚未选择关键帧</strong>
            <span>从下方时间轴选择一个姿态节点。</span>
          </div>
        ) : (
          <div className="studio-inspector__body">
            <label className="studio-field">
              <span>名称</span>
              <input
                aria-label="关键帧名称"
                disabled={busy}
                maxLength={200}
                onChange={(event) => onLabelChange(frame.id, event.target.value)}
                value={frame.label}
              />
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
            {!transition ? (
              <p className="studio-field-note" id="first-frame-transition-note">第一个关键帧从 00:00 开始。</p>
            ) : null}

            <label className="studio-field">
              <span>运动模式</span>
              <select
                aria-label="进入过渡的运动模式"
                disabled={busy || !transition}
                onChange={(event) => onModeChange(frame.id, event.target.value as MotionMode)}
                value={transition?.motion_mode ?? 'JOINT'}
              >
                <option value="JOINT">JOINT</option>
                <option value="CARTESIAN_LINEAR">CARTESIAN_LINEAR</option>
              </select>
            </label>

            <div className="studio-inspector__actions">
              <button
                className="command-button"
                disabled={busy || frameLimitReached}
                onClick={() => onDuplicate(frame.id)}
                type="button"
              >
                <Copy aria-hidden="true" /> 复制关键帧
              </button>
              <button
                className="command-button command-button--danger"
                disabled={deleteDisabled}
                onClick={() => onDelete(frame.id)}
                title={frameCount <= 2 ? '可播放运动至少需要两个关键帧' : '删除当前关键帧'}
                type="button"
              >
                <Trash2 aria-hidden="true" /> 删除关键帧
              </button>
            </div>
            {frameCount <= 2 ? <p className="studio-field-note">至少保留两个关键帧。</p> : null}
          </div>
        )}
      </aside>
    </>
  );
}
