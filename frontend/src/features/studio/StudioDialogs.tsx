import { AlertTriangle, FolderOpen, Plus, SaveAll, X } from 'lucide-react';
import { useEffect, useRef } from 'react';

import type { PoseSummary } from '../../api/types';

const KEEP_DIALOG_OPEN = () => undefined;

interface DialogFrameProps {
  children: React.ReactNode;
  labelledBy: string;
  onClose: () => void;
}

function DialogFrame({ children, labelledBy, onClose }: DialogFrameProps) {
  const dialogRef = useRef<HTMLElement | null>(null);
  const closeRef = useRef(onClose);
  closeRef.current = onClose;

  useEffect(() => {
    const previousFocus = document.activeElement instanceof HTMLElement ? document.activeElement : null;
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
    <div className="studio-dialog-backdrop" role="presentation" onMouseDown={onClose}>
      <section
        aria-labelledby={labelledBy}
        aria-modal="true"
        className="studio-dialog"
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
  onSearchChange,
}: PosePickerProps) {
  return (
    <DialogFrame labelledBy="studio-pose-picker-heading" onClose={busy ? () => undefined : onClose}>
      <header className="studio-dialog__header">
        <div>
          <p className="section-kicker">Pose Library</p>
          <h2 id="studio-pose-picker-heading">Add keyframe {placement}</h2>
        </div>
        <button aria-label="Close Pose picker" className="mini-command" disabled={busy} onClick={onClose} type="button">
          <X aria-hidden="true" />
        </button>
      </header>
      <label className="studio-field">
        <span>Search saved Poses</span>
        <input
          autoFocus
          maxLength={200}
          onChange={(event) => onSearchChange(event.target.value)}
          placeholder="Pose name or tag"
          value={search}
        />
      </label>
      {error ? <p className="studio-dialog__error" role="alert">{error}</p> : null}
      <div className="studio-pose-picker-list" aria-busy={busy}>
        {busy ? <p>Loading bounded Pose results…</p> : null}
        {!busy && poses.length === 0 ? <p>No matching Pose was found.</p> : null}
        {poses.map((pose) => (
          <button disabled={busy} key={pose.id} onClick={() => onChoose(pose)} type="button">
            <span>
              <strong>{pose.name}</strong>
              <small>{pose.robot_variant} · rev {pose.revision} · {pose.tags.join(' · ') || 'no tags'}</small>
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
          <p className="section-kicker">New immutable identity</p>
          <h2 id="studio-save-as-heading">Save Motion As</h2>
        </div>
        <button aria-label="Close Save As dialog" className="mini-command" onClick={onClose} type="button">
          <X aria-hidden="true" />
        </button>
      </header>
      <p className="studio-dialog__copy">
        A new Motion UUID and revision 1 will be created. Embedded keyframe snapshots are preserved; the source Motion is not overwritten.
      </p>
      <label className="studio-field">
        <span>New Motion name</span>
        <input
          autoFocus
          maxLength={200}
          onChange={(event) => onNameChange(event.target.value)}
          value={name}
        />
      </label>
      <div className="studio-dialog__actions">
        <button className="command-button" disabled={busy} onClick={onClose} type="button">Cancel</button>
        <button className="command-button command-button--primary" disabled={busy || !valid} onClick={onSave} type="button">
          <SaveAll aria-hidden="true" /> {busy ? 'Saving…' : 'Save new Motion'}
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
          <p className="section-kicker">Revision conflict</p>
          <h2 id="studio-conflict-heading">The stored entity changed</h2>
        </div>
      </header>
      <p className="studio-dialog__copy">
        Expected revision {expectedRevision ?? 'unknown'}, but the repository reports {actualRevision ?? 'a newer revision'}. MOMO Studio did not overwrite it.
      </p>
      <div className="studio-dialog__actions studio-dialog__actions--three">
        <button className="command-button" disabled={busy} onClick={onCancel} type="button">Keep editing</button>
        <button className="command-button" disabled={busy} onClick={onReload} type="button">
          <FolderOpen aria-hidden="true" /> Reload
        </button>
        <button className="command-button command-button--primary" disabled={busy} onClick={onSaveAs} type="button">
          <SaveAll aria-hidden="true" /> Save As
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
          <p className="section-kicker">Fail-closed recovery</p>
          <h2 id="studio-formal-save-recovery-heading">Formal save needs attention</h2>
        </div>
      </header>
      <p className="studio-dialog__copy">
        Studio cannot prove that an interrupted {kind === 'SAVE_AS' ? 'Save As' : 'Save'} operation matches its target Motion, so the editor remains locked. The target Motion remains untouched.
      </p>
      <dl className="studio-dialog__details">
        <div><dt>Draft</dt><dd>{draftId} · revision {draftRevision}</dd></div>
        <div><dt>Target Motion</dt><dd>{targetMotionId} · intended revision {targetMotionRevision}</dd></div>
        {actualTargetRevision === null ? null : (
          <div><dt>Observed target</dt><dd>revision {actualTargetRevision}</dd></div>
        )}
        <div><dt>Recovery reason</dt><dd>{reason}</dd></div>
      </dl>
      <p className="studio-dialog__copy">
        Release draft clears only this recovery marker and reloads the autosaved draft. It does not retry, force, overwrite, or delete the target Motion.
      </p>
      {error ? <p className="studio-dialog__error" role="alert">{error}</p> : null}
      <div className="studio-dialog__actions">
        <button
          className="command-button command-button--danger-solid"
          disabled={busy}
          onClick={onRelease}
          type="button"
        >
          {busy ? 'Releasing…' : 'Release draft'}
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
          <p className="section-kicker">Confirm action</p>
          <h2 id="studio-confirm-heading">{title}</h2>
        </div>
      </header>
      <p className="studio-dialog__copy">{description}</p>
      <div className="studio-dialog__actions">
        <button className="command-button" disabled={busy} onClick={onCancel} type="button">Cancel</button>
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
