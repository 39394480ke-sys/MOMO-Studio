import { FilePlus2, Redo2, Save, SaveAll, Undo2 } from 'lucide-react';

interface StudioToolbarProps {
  autosaveLabel: string;
  busy: boolean;
  canRedo: boolean;
  canSaveMotion: boolean;
  canUndo: boolean;
  dirty: boolean;
  draftName: string;
  saveDisabledReason: string | null;
  onNameChange: (name: string) => void;
  onNew: () => void;
  onRedo: () => void;
  onSave: () => void;
  onSaveAs: () => void;
  onUndo: () => void;
}

export function StudioToolbar({
  autosaveLabel,
  busy,
  canRedo,
  canSaveMotion,
  canUndo,
  dirty,
  draftName,
  saveDisabledReason,
  onNameChange,
  onNew,
  onRedo,
  onSave,
  onSaveAs,
  onUndo,
}: StudioToolbarProps) {
  return (
    <header className="studio-toolbar" aria-label="编排文档控制">
      <div className="studio-toolbar__identity">
        <label htmlFor="studio-motion-name">运动名称</label>
        <input
          autoComplete="off"
          disabled={busy}
          id="studio-motion-name"
          maxLength={200}
          onChange={(event) => onNameChange(event.target.value)}
          value={draftName}
        />
        <span className={`studio-autosave-state${dirty ? ' studio-autosave-state--dirty' : ''}`}>
          {dirty ? '运动有未保存修改' : autosaveLabel}
        </span>
      </div>

      <div className="studio-toolbar__actions">
        <button aria-label="撤销上一次编排修改" className="mini-command" disabled={busy || !canUndo} onClick={onUndo} type="button">
          <Undo2 aria-hidden="true" />
        </button>
        <button aria-label="重做上一次编排修改" className="mini-command" disabled={busy || !canRedo} onClick={onRedo} type="button">
          <Redo2 aria-hidden="true" />
        </button>
        <button className="command-button" disabled={busy} onClick={onNew} type="button">
          <FilePlus2 aria-hidden="true" /> 新建草稿
        </button>
        <button className="command-button command-button--primary" disabled={busy || !canSaveMotion} onClick={onSave} title={saveDisabledReason ?? '保存当前 Motion'} type="button">
          <Save aria-hidden="true" /> 保存
        </button>
        <button className="command-button" disabled={busy || !canSaveMotion} onClick={onSaveAs} title={saveDisabledReason ?? '另存为新的 Motion'} type="button">
          <SaveAll aria-hidden="true" /> 另存为
        </button>
      </div>
    </header>
  );
}
