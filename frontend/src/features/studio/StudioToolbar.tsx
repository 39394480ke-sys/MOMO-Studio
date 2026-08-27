import {
  ArrowLeft,
  FilePlus2,
  Library,
  Redo2,
  Save,
  SaveAll,
  Undo2,
} from 'lucide-react';
import { Link } from 'react-router-dom';

import type { RobotVariant } from '../../api/types';

interface StudioToolbarProps {
  autosaveLabel: string;
  busy: boolean;
  canRedo: boolean;
  canSaveMotion: boolean;
  canUndo: boolean;
  dirty: boolean;
  draftName: string;
  draftRevision: number | null;
  robotVariant: RobotVariant;
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
  draftRevision,
  robotVariant,
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
        <div className="studio-document-meta" aria-live="polite">
          <span className={`studio-dirty-state${dirty ? ' studio-dirty-state--dirty' : ''}`}>
            {dirty ? '运动有未保存修改' : '运动已是最新'}
          </span>
          <span>{autosaveLabel}</span>
          <span>{robotVariant}</span>
          {draftRevision ? <span>草稿版本 {draftRevision}</span> : null}
        </div>
      </div>

      <div className="studio-toolbar__actions">
        <button
          aria-label="撤销上一次编排修改"
          className="mini-command"
          disabled={busy || !canUndo}
          onClick={onUndo}
          title={canUndo ? '撤销上一次修改（Ctrl/⌘ Z）' : '没有可撤销的修改'}
          type="button"
        >
          <Undo2 aria-hidden="true" />
          <span>撤销</span>
        </button>
        <button
          aria-label="重做上一次编排修改"
          className="mini-command"
          disabled={busy || !canRedo}
          onClick={onRedo}
          title={canRedo ? '重做上一次修改（Ctrl/⌘ Shift Z）' : '没有可重做的修改'}
          type="button"
        >
          <Redo2 aria-hidden="true" />
          <span>重做</span>
        </button>
        <button className="command-button" disabled={busy} onClick={onNew} type="button">
          <FilePlus2 aria-hidden="true" />
          新建草稿
        </button>
        <button
          aria-describedby={saveDisabledReason ? 'studio-save-disabled-reason' : undefined}
          className="command-button command-button--primary"
          disabled={busy || !canSaveMotion}
          onClick={onSave}
          title={saveDisabledReason ?? '校验、编译并保存当前运动'}
          type="button"
        >
          <Save aria-hidden="true" />
          保存
        </button>
        <button
          aria-describedby={saveDisabledReason ? 'studio-save-disabled-reason' : undefined}
          className="command-button"
          disabled={busy || !canSaveMotion}
          onClick={onSaveAs}
          title={saveDisabledReason ?? '使用新的 UUID 另存一份运动'}
          type="button"
        >
          <SaveAll aria-hidden="true" />
          另存为
        </button>
        <Link className="command-button studio-library-link" to="/library">
          <Library aria-hidden="true" />
          资源库
        </Link>
      </div>

      {saveDisabledReason ? (
        <p className="studio-toolbar__reason" id="studio-save-disabled-reason">
          <ArrowLeft aria-hidden="true" /> 暂时无法保存 · {saveDisabledReason}
        </p>
      ) : null}
    </header>
  );
}
