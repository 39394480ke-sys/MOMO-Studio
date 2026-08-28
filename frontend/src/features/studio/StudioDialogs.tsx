import { AlertTriangle, FolderOpen, Plus, Radio, SaveAll, X } from 'lucide-react';
import { useLayoutEffect, useRef } from 'react';

import type { PoseSummary } from '../../api/types';

const KEEP_DIALOG_OPEN = () => undefined;

interface DialogFrameProps {
  children: React.ReactNode;
  labelledBy: string;
  onClose: () => void;
  variant?: 'modal' | 'drawer';
}

function DialogFrame({ children, labelledBy, onClose, variant = 'modal' }: DialogFrameProps) {
  const dialogRef = useRef<HTMLElement | null>(null);
  // Capture the trigger during render, before an autoFocus child is committed.
  // Reading it inside the effect is too late: React may already have focused the
  // drawer input, leaving no stable element to restore after Escape.
  const returnFocusRef = useRef<HTMLElement | null>(
    typeof document !== 'undefined' && document.activeElement instanceof HTMLElement
      ? document.activeElement
      : null,
  );
  const closeRef = useRef(onClose);
  closeRef.current = onClose;

  useLayoutEffect(() => {
    const previousFocus = returnFocusRef.current;
    const dialog = dialogRef.current;
    const focusable = () => Array.from(dialog?.querySelectorAll<HTMLElement>(
      'button:not(:disabled), input:not(:disabled), select:not(:disabled), [tabindex]:not([tabindex="-1"])',
    ) ?? []);
    if (!dialog?.contains(document.activeElement)) (focusable()[0] ?? dialog)?.focus();
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        event.preventDefault();
        closeRef.current();
        return;
      }
      if (event.key !== 'Tab') return;
      const controls = focusable();
      if (controls.length === 0) {
        event.preventDefault();
        dialog?.focus();
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
  }, []);

  return (
    <div className={`studio-dialog-backdrop studio-dialog-backdrop--${variant}`} role="presentation" onMouseDown={onClose}>
      <section
        aria-labelledby={labelledBy}
        aria-modal="true"
        className={`studio-dialog studio-dialog--${variant}`}
        onMouseDown={(event) => event.stopPropagation()}
        ref={dialogRef}
        role="dialog"
        tabIndex={-1}
      >
        {children}
      </section>
    </div>
  );
}

interface PosePickerProps {
  busy: boolean;
  error: string | null;
  placement: 'before' | 'after';
  poses: PoseSummary[];
  search: string;
  onChoose: (pose: PoseSummary) => void;
  onClose: () => void;
  onCapture: () => void;
  onSearchChange: (search: string) => void;
}

export function StudioPosePicker({
  busy,
  error,
  placement,
  poses,
  search,
  onChoose,
  onClose,
  onCapture,
  onSearchChange,
}: PosePickerProps) {
  return (
    <DialogFrame labelledBy="studio-pose-picker-heading" onClose={busy ? () => undefined : onClose} variant="drawer">
      <header className="studio-dialog__header">
        <div>
          <p className="section-kicker">机位资源库</p>
          <h2 id="studio-pose-picker-heading">在当前关键帧{placement === 'before' ? '前' : '后'}添加</h2>
        </div>
        <button aria-label="关闭机位选择器" className="mini-command" disabled={busy} onClick={onClose} type="button">
          <X aria-hidden="true" />
        </button>
      </header>
      <button
        className="studio-capture-card"
        disabled={busy}
        onClick={onCapture}
        type="button"
      >
        <span className="studio-capture-card__icon"><Radio aria-hidden="true" /></span>
        <span>
          <strong>捕获当前姿态</strong>
          <small>通过后端统一状态快照入口添加；不会直接读取或控制硬件。</small>
        </span>
        <Plus aria-hidden="true" />
      </button>
      <div className="studio-drawer-divider"><span>或从机位库选择</span></div>
      <label className="studio-field">
        <span>搜索已保存机位</span>
        <input
          autoFocus
          maxLength={200}
          onChange={(event) => onSearchChange(event.target.value)}
          placeholder="机位名称或标签"
          value={search}
        />
      </label>
      {error ? <p className="studio-dialog__error" role="alert">{error}</p> : null}
      <div className="studio-pose-picker-list" aria-busy={busy}>
        {busy ? <p>正在加载机位结果…</p> : null}
        {!busy && poses.length === 0 ? <p>没有找到匹配的机位。</p> : null}
        {poses.map((pose) => (
          <button disabled={busy} key={pose.id} onClick={() => onChoose(pose)} type="button">
            <span>
              <strong>{pose.name}</strong>
              <small>{pose.robot_variant} · 版本 {pose.revision} · {pose.tags.join(' · ') || '无标签'}</small>
            </span>
            <Plus aria-hidden="true" />
          </button>
        ))}
      </div>
    </DialogFrame>
  );
}

interface SaveAsDialogProps {
  busy: boolean;
  name: string;
  onClose: () => void;
  onNameChange: (name: string) => void;
  onSave: () => void;
}

export function StudioSaveAsDialog({
  busy,
  name,
  onClose,
  onNameChange,
  onSave,
}: SaveAsDialogProps) {
  const valid = name.trim().length > 0 && name.trim().length <= 200;
  return (
    <DialogFrame labelledBy="studio-save-as-heading" onClose={onClose}>
      <header className="studio-dialog__header">
        <div>
          <p className="section-kicker">创建新的不可变资源</p>
          <h2 id="studio-save-as-heading">运动另存为</h2>
        </div>
        <button aria-label="关闭另存为对话框" className="mini-command" onClick={onClose} type="button">
          <X aria-hidden="true" />
        </button>
      </header>
      <p className="studio-dialog__copy">
        系统会创建新的运动 UUID 和版本 1。内嵌关键帧快照会完整保留，原运动不会被覆盖。
      </p>
      <label className="studio-field">
        <span>新运动名称</span>
        <input
          autoFocus
          maxLength={200}
          onChange={(event) => onNameChange(event.target.value)}
          value={name}
        />
      </label>
      <div className="studio-dialog__actions">
        <button className="command-button" disabled={busy} onClick={onClose} type="button">取消</button>
        <button className="command-button command-button--primary" disabled={busy || !valid} onClick={onSave} type="button">
          <SaveAll aria-hidden="true" /> {busy ? '正在保存…' : '保存为新运动'}
        </button>
      </div>
    </DialogFrame>
  );
}

interface ConflictDialogProps {
  actualRevision: number | null;
  busy: boolean;
  expectedRevision: number | null;
  onCancel: () => void;
  onReload: () => void;
  onSaveAs: () => void;
}

export function StudioConflictDialog({
  actualRevision,
  busy,
  expectedRevision,
  onCancel,
  onReload,
  onSaveAs,
}: ConflictDialogProps) {
  return (
    <DialogFrame labelledBy="studio-conflict-heading" onClose={onCancel}>
      <header className="studio-dialog__header studio-dialog__header--warning">
        <AlertTriangle aria-hidden="true" />
        <div>
          <p className="section-kicker">版本冲突</p>
          <h2 id="studio-conflict-heading">已保存的数据发生变化</h2>
        </div>
      </header>
      <p className="studio-dialog__copy">
        预期版本为 {expectedRevision ?? '未知'}，但资源库当前为 {actualRevision ?? '更新版本'}。MOMO Studio 没有覆盖它。
      </p>
      <div className="studio-dialog__actions studio-dialog__actions--three">
        <button className="command-button" disabled={busy} onClick={onCancel} type="button">继续本地编辑</button>
        <button className="command-button" disabled={busy} onClick={onReload} type="button">
          <FolderOpen aria-hidden="true" /> 重新加载
        </button>
        <button className="command-button command-button--primary" disabled={busy} onClick={onSaveAs} type="button">
          <SaveAll aria-hidden="true" /> 另存为
        </button>
      </div>
    </DialogFrame>
  );
}

interface FormalSaveRecoveryDialogProps {
  actualTargetRevision: number | null;
  busy: boolean;
  draftId: string;
  draftRevision: number;
  error: string | null;
  kind: 'SAVE' | 'SAVE_AS';
  reason: string;
  targetMotionId: string;
  targetMotionRevision: number;
  onRelease: () => void;
}

export function StudioFormalSaveRecoveryDialog({
  actualTargetRevision,
  busy,
  draftId,
  draftRevision,
  error,
  kind,
  reason,
  targetMotionId,
  targetMotionRevision,
  onRelease,
}: FormalSaveRecoveryDialogProps) {
  return (
    <DialogFrame labelledBy="studio-formal-save-recovery-heading" onClose={KEEP_DIALOG_OPEN}>
      <header className="studio-dialog__header studio-dialog__header--warning">
        <AlertTriangle aria-hidden="true" />
        <div>
          <p className="section-kicker">安全恢复</p>
          <h2 id="studio-formal-save-recovery-heading">需要处理未完成的正式保存</h2>
        </div>
      </header>
      <p className="studio-dialog__copy">
        编排器无法确认中断的{kind === 'SAVE_AS' ? '另存为' : '保存'}操作是否与目标运动一致，因此暂时锁定编辑器；目标运动不会被修改。
      </p>
      <dl className="studio-dialog__details">
        <div><dt>草稿</dt><dd>{draftId} · 版本 {draftRevision}</dd></div>
        <div><dt>目标运动</dt><dd>{targetMotionId} · 计划版本 {targetMotionRevision}</dd></div>
        {actualTargetRevision === null ? null : (
          <div><dt>实际目标</dt><dd>版本 {actualTargetRevision}</dd></div>
        )}
        <div><dt>恢复原因</dt><dd>{reason}</dd></div>
      </dl>
      <p className="studio-dialog__copy">
        “解除草稿锁定”只会清除此恢复标记并重新加载自动保存草稿，不会重试、强制覆盖或删除目标运动。
      </p>
      {error ? <p className="studio-dialog__error" role="alert">{error}</p> : null}
      <div className="studio-dialog__actions">
        <button
          className="command-button command-button--danger-solid"
          disabled={busy}
          onClick={onRelease}
          type="button"
        >
          {busy ? '正在解除…' : '解除草稿锁定'}
        </button>
      </div>
    </DialogFrame>
  );
}

interface ConfirmDialogProps {
  busy?: boolean;
  confirmLabel: string;
  danger?: boolean;
  description: string;
  title: string;
  onCancel: () => void;
  onConfirm: () => void;
}

export function StudioConfirmDialog({
  busy = false,
  confirmLabel,
  danger = false,
  description,
  title,
  onCancel,
  onConfirm,
}: ConfirmDialogProps) {
  return (
    <DialogFrame labelledBy="studio-confirm-heading" onClose={onCancel}>
      <header className="studio-dialog__header">
        <div>
          <p className="section-kicker">确认操作</p>
          <h2 id="studio-confirm-heading">{title}</h2>
        </div>
      </header>
      <p className="studio-dialog__copy">{description}</p>
      <div className="studio-dialog__actions">
        <button className="command-button" disabled={busy} onClick={onCancel} type="button">取消</button>
        <button
          className={`command-button ${danger ? 'command-button--danger-solid' : 'command-button--primary'}`}
          disabled={busy}
          onClick={onConfirm}
          type="button"
        >
          {confirmLabel}
        </button>
      </div>
    </DialogFrame>
  );
}
